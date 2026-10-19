"""Tests for event validation: redaction, secrets, malformed values and adapters."""

from datetime import datetime

import pytest
from events_support import AT, SECRET, publish, task


def test_invalid_event_is_refused_with_reason(client):
    ref = task(client)
    res = publish(client, "handoff", task=ref, needs=["aether"])

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "next_action_required"

def test_secrets_never_reach_the_database(client):
    ref = task(client)
    event = publish(client, "progress", f"clé {SECRET}", task=ref, body=f"token={SECRET}",
                    payload={"note": SECRET, "percent": 40}).json()

    stored = client.get(f"/api/events/{event['id']}").text
    assert SECRET not in stored
    assert event["redacted"] == ["github_token"]

def test_unknown_event_field_is_refused(client):
    ref = task(client)
    res = publish(client, "claimed", task=ref, statut="x")
    assert res.status_code == 422
    assert "champ inconnu" in res.text

def test_secret_only_cause_or_evidence_does_not_count(client):
    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r"})

    blocked = publish(client, "blocked", task=ref, body=SECRET, payload={"plan": "p"})
    assert blocked.json()["detail"]["code"] == "block_cause_required"

    done = publish(client, "done", "Fini", task=ref, evidence=[SECRET]).json()
    assert done["kind"] == "review"

def test_secret_in_event_id_is_refused(client):
    ref = task(client, next_action="x")
    refused = publish(client, "claimed", task=ref, id=f"evt {SECRET}")
    assert refused.json()["detail"]["code"] == "secret_in_event_id"
    assert SECRET not in refused.text

@pytest.mark.parametrize(
    "fields",
    [
        {"run": SECRET},
        {"payload": {"run_ref": SECRET}},
        # Masquées, ces deux références deviendraient la même : "run token=[REDACTED]".
        {"run": "run token=alpha"},
        {"payload": {"run_ref": "run token=beta"}},
    ],
)
def test_run_reference_containing_a_secret_is_refused(client, fields):
    ref = task(client, next_action="x")
    res = publish(client, "working", task=ref, **fields)

    assert res.json()["detail"]["code"] == "secret_in_run_ref"
    assert SECRET not in res.text and "alpha" not in res.text and "beta" not in res.text
    assert client.get("/api/events", params={"task": ref}).json() == []

def test_non_string_run_ref_is_refused_not_500(client):
    ref = task(client)
    res = publish(client, "progress", task=ref, payload={"percent": 40, "run_ref": {}})
    assert res.json()["detail"]["code"] == "invalid_run_ref"

def test_secret_used_as_payload_key_is_redacted(client):
    ref = task(client)
    event = publish(client, "progress", task=ref, payload={"percent": 10, SECRET: "x"}).json()

    assert SECRET not in client.get(f"/api/events/{event['id']}").text
    assert event["redacted"] == ["github_token"]

def test_handoff_needs_exactly_one_recipient(client):
    ref = task(client)
    res = publish(client, "handoff", task=ref, needs=["aether", "mnema"],
                  payload={"next_action": "poser la clé"})
    assert res.json()["detail"]["code"] == "single_recipient_required"

def test_values_under_credential_keys_are_redacted(client):
    ref = task(client)
    event = publish(client, "progress", task=ref,
                    payload={"percent": 5, "password": "hunter2", "db": {"api_key": "abc"}}).json()

    stored = client.get(f"/api/events/{event['id']}").text
    assert "hunter2" not in stored and '"abc"' not in stored
    assert event["redacted"] == ["credential"]

@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_refused_not_stored(client, literal):
    ref = task(client)
    # Corps écrit à la main : json.dumps refuserait de produire NaN/Infinity en JSON strict.
    body = (
        f'{{"id": "evt_nan", "at": "{AT}", "actor": "helios", "kind": "progress", '
        f'"subject": "s", "task": "{ref}", "payload": {{"percent": 5, "x": {literal}}}}}'
    )
    res = client.post("/api/events", content=body, headers={"Content-Type": "application/json"})

    assert res.status_code == 422
    assert client.get("/api/events", params={"task": ref}).json() == []

@pytest.mark.parametrize(
    ("kind", "payload", "code"),
    [
        ("blocked", {"follow_up_at": "2026-09-29T09:00:00+02:00", "plan": {}}, "invalid_plan"),
        ("blocked", {"plan": "p", "cause": ["c"]}, "invalid_cause"),
        ("handoff", {"next_action": {"x": 1}}, "invalid_next_action"),
    ],
)
def test_non_text_workflow_fields_are_refused_not_500(client, kind, payload, code):
    ref = task(client, next_action="x")
    publish(client, "working", task=ref, payload={"run_ref": "r1"})

    res = publish(client, kind, task=ref, body="cause écrite", needs=["aether"], payload=payload)

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == code

def test_working_whose_run_reads_as_redacted_is_refused(client):
    ref = task(client, next_action="x")
    res = publish(client, "working", task=ref, payload={"run_ref": "[REDACTED]"})
    assert res.json()["detail"]["code"] == "run_ref_required"

def test_unknown_field_named_like_a_secret_is_not_echoed(client):
    ref = task(client)
    res = client.post("/api/events", json={
        "id": "evt_x", "at": AT, "actor": "helios", "kind": "claimed", "subject": "s",
        "task": ref, SECRET: "x",
    })
    assert res.status_code == 422
    assert SECRET not in res.text
    assert "champ inconnu" in res.text

@pytest.mark.parametrize(
    "fragment",
    [
        r'"payload": {"percent": 5, "x": "\ud800"}',
        r'"payload": {"percent": 5, "\udfff": 1}',
        r'"body": "a\ud800b"',
    ],
)
def test_lone_surrogates_are_refused_before_storage(client, fragment):
    ref = task(client)
    raw = (
        f'{{"id": "evt_s", "at": "{AT}", "actor": "helios", "kind": "progress", '
        f'"subject": "s", "task": "{ref}", {fragment}}}'
    )
    res = client.post("/api/events", content=raw, headers={"Content-Type": "application/json"})

    assert res.status_code == 422, res.text
    assert client.get("/api/events", params={"task": ref}).status_code == 200
    assert client.get("/api/events", params={"task": ref}).json() == []

def test_valid_surrogate_pair_is_an_ordinary_character(client):
    ref = task(client)
    raw = (
        f'{{"id": "evt_e", "at": "{AT}", "actor": "helios", "kind": "progress", '
        rf'"subject": "fusée \ud83d\ude80", "task": "{ref}", "payload": {{"percent": 5}}}}'
    )
    res = client.post("/api/events", content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 201, res.text
    assert res.json()["subject"] == "fusée 🚀"

@pytest.mark.parametrize(
    "fields", [{"actor": "codx"}, {"kind": "termine"}, {"needs": ["loic", "codx"]}]
)
def test_http_api_refuses_unknown_actor_kind_or_recipient_with_422(client, fields):
    ref = task(client)
    body = {"id": "evt_bad", "at": AT, "actor": "helios", "kind": "question",
            "subject": "s", "task": ref, "needs": ["loic"]} | fields
    res = client.post("/api/events", json=body, headers=client.headers_for("helios"))
    assert res.status_code == 422, res.text
    assert client.get("/api/events", params={"task": ref}).json() == []

@pytest.mark.parametrize("actor", [[], {}, ["loic"], 7])
def test_a_non_text_actor_is_refused_with_422(client, actor):
    """The test client signs as loic when the body actor is not a name: the API validates."""
    ref = task(client)
    body = {"id": "evt_bad", "at": AT, "actor": actor, "kind": "question",
            "subject": "s", "task": ref, "needs": ["loic"]}
    res = client.post("/api/events", json=body)
    assert res.status_code == 422, res.text
    assert [e["loc"] for e in res.json()["detail"]] == [["body", "actor"]]
    assert client.get("/api/events", params={"task": ref}).json() == []

@pytest.mark.parametrize(
    "origin",
    ["token=ghp_" + "S" * 36, "Hermes Adapter!", "", "sk-proj-" + "a1b2c3d4e5f6g7h8i9j0k1l2"],
)
def test_adapter_origin_must_be_a_plain_adapter_name(client, origin):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation) as refused:
            service.publish(session, Envelope(actor="helios", kind="claimed", subject="s",
                                              task=ref), "evt_o", datetime.fromisoformat(AT),
                            origin=origin)
    assert refused.value.code == "invalid_origin"
    assert "S" * 36 not in refused.value.message

@pytest.mark.parametrize(
    "fields",
    [
        {"payload": {"x": "\ud800"}},
        {"payload": {"x": float("nan")}},
        {"body": "a\udfffb"},
        {"payload": {"\ud800": 1}},
        {"payload": {"x": ("\ud800",)}},
    ],
)
def test_adapter_payload_is_checked_like_the_api(client, fields):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    envelope = Envelope(actor="helios", kind="progress", subject="s", task=ref,
                        **({"body": "avance"} | fields))
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation):
            service.publish(session, envelope, "evt_adapter", datetime.fromisoformat(AT),
                            origin="hermes")
    assert client.get("/api/events", params={"task": ref}).status_code == 200

@pytest.mark.parametrize("event_id", ["   ", "[REDACTED]"])
def test_blank_or_redacted_event_id_is_refused(client, event_id):
    ref = task(client)
    res = publish(client, "claimed", task=ref, id=event_id)
    assert res.status_code in (409, 422), res.text
    assert client.get("/api/events", params={"task": ref}).json() == []

def test_naive_timestamp_from_an_adapter_is_refused(client):
    from datetime import datetime

    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation) as refused:
            service.publish(session, Envelope(actor="helios", kind="claimed", subject="s",
                                              task=ref), "evt_naive", datetime(2026, 9, 29, 9, 0),
                            origin="hermes")
    assert refused.value.code == "invalid_instant"

def test_unreadable_evidence_on_a_task_already_in_review_is_refused(client):
    ref = task(client, status="todo", next_action="x", expected_evidence="le commit")
    client.post(f"/api/tasks/{ref}/status", json={"status": "in_progress"})
    client.post(f"/api/tasks/{ref}/status", json={"status": "review"})

    res = publish(client, "review", "preuve", task=ref, evidence=["commit: token=hunter2"])

    # Une preuve illisible est refusée dès la validation de l'événement, avant tout effet.
    assert res.json()["detail"]["code"] == "evidence_required"
    assert "hunter2" not in res.text
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == []

def test_attach_evidence_refuses_references_without_identifier(client):
    from nexus.models import Task
    from nexus.tasks import service as tasks
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        row = session.get(Task, int(ref.removeprefix("nx-task-")))
        with pytest.raises(RuleViolation) as refused:
            tasks.attach_evidence(session, row, ["commit: [REDACTED]"], "helios")
    assert refused.value.code == "evidence_required"

@pytest.mark.parametrize(
    "payload", [{"tags": {"a", "b"}}, {"blob": b"\x00"}, {"quand": datetime(2026, 9, 29)}]
)
def test_adapter_payload_must_be_plain_json(client, payload):
    from nexus.events import service
    from nexus.events.rules import Envelope
    from nexus.tasks.rules import RuleViolation

    ref = task(client)
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation) as refused:
            service.publish(session, Envelope(actor="helios", kind="progress", subject="s",
                                              task=ref, body="b", payload=payload),
                            "evt_json", datetime.fromisoformat(AT), origin="hermes")
    assert refused.value.code == "invalid_value"
