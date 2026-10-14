"""Completing a task's evidence without changing its status (ADR-022, #65)."""

from datetime import datetime

import pytest

from nexus.models import Task
from nexus.tasks import service
from nexus.tasks.rules import RuleViolation
from nexus.validation import API_STRIP

SECRET = "ghp_" + "A" * 36
AT = "2026-10-14T09:00:00+02:00"


def made(client, **fields):
    body = {"title": "Pont", "objective": "Lire", "next_action": "x"} | fields
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def move(client, ref, status, **fields):
    return client.post(f"/api/tasks/{ref}/status", json={"status": status} | fields)


def closed(client, evidence=("commit:abc",)):
    ref = made(client)
    move(client, ref, "in_progress")
    assert move(client, ref, "done", evidence=list(evidence)).status_code == 200
    return ref


def post(client, ref, evidence, **kwargs):
    return client.post(f"/api/tasks/{ref}/evidence", json={"evidence": evidence}, **kwargs)


def code(res, status=409):
    assert res.status_code == status, res.text
    return res.json()["detail"]["code"]


def test_evidence_is_appended_to_a_done_task_with_provenance(client):
    ref = closed(client)
    res = post(client, ref, ["PR #12"])
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "done" and body["evidence"] == ["commit:abc", "PR #12"]
    assert body["source"] == "nexus.db"
    assert datetime.fromisoformat(body["measured_at"]).tzinfo is not None
    updated = [h for h in client.get(f"/api/tasks/{ref}/history").json()
               if h["action"] == "updated"]
    assert updated[-1]["changes"] == {"evidence": [["commit:abc"], ["commit:abc", "PR #12"]]}


def test_evidence_can_be_added_to_a_done_task_without_any(client):
    ref = made(client)
    move(client, ref, "in_progress")
    assert move(client, ref, "done").status_code == 200  # no expectation: closes bare
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == []
    assert post(client, ref, ["commit:late"]).json()["evidence"] == ["commit:late"]
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "done"


@pytest.mark.parametrize("status", ["backlog", "in_progress", "review", "dropped"])
def test_evidence_is_accepted_whatever_the_status(client, status):
    ref = made(client)
    if status == "dropped":
        move(client, ref, "dropped", reason="r")
    elif status != "backlog":
        move(client, ref, "in_progress")
        if status == "review":
            move(client, ref, "review")
    assert post(client, ref, ["commit:x"]).json()["status"] == status


def test_an_agent_may_attach_evidence_too(client):
    ref = closed(client)
    res = post(client, ref, ["commit:agent"], headers={"X-Nexus-Actor": "helios"})
    assert res.status_code == 200
    updated = [h for h in client.get(f"/api/tasks/{ref}/history").json()
               if h["action"] == "updated"]
    assert updated[-1]["actor"] == "helios"


def test_a_secret_is_masked_traced_and_never_echoed(client):
    ref = closed(client)
    res = post(client, ref, [f"commit:abc2 token={SECRET}"])
    assert res.status_code == 200 and SECRET not in res.text
    assert "[REDACTED]" in res.json()["evidence"][-1]
    history = client.get(f"/api/tasks/{ref}/history").json()
    assert "secret_redacted" in [h["action"] for h in history]
    assert SECRET not in str(history)


def test_evidence_reduced_to_a_masked_label_is_not_evidence(client):
    ref = closed(client)
    assert code(post(client, ref, ["commit: [REDACTED]"])) == "evidence_required"
    assert code(post(client, ref, [f"commit: {SECRET}"])) == "evidence_required"
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:abc"]


def test_the_same_evidence_twice_is_refused(client):
    ref = closed(client)
    assert code(post(client, ref, ["commit:abc"])) == "evidence_unchanged"
    assert code(post(client, ref, ["  commit:abc  "])) == "evidence_unchanged"


@pytest.mark.parametrize("body", [
    {"evidence": ["a"], "status": "todo"},
    {"evidence": []},
    {"evidence": [""]},
    {"evidence": ["   "]},
    {"evidence": ["x" * 513]},
    {"evidence": [5]},
    {"evidence": "commit:abc"},
    {},
])
def test_the_body_is_validated(client, body):
    ref = closed(client)
    res = client.post(f"/api/tasks/{ref}/evidence", json=body)
    assert res.status_code == 422, res.text
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:abc"]


def test_a_lone_surrogate_is_a_422(client):
    ref = closed(client)
    res = client.post(f"/api/tasks/{ref}/evidence", content=r'{"evidence": ["commit:\ud800"]}',
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 422
    assert client.get(f"/api/tasks/{ref}").status_code == 200


def test_the_limit_is_measured_after_stripping(client):
    ref = closed(client)
    assert post(client, ref, ["  " + "x" * 512 + "  "]).status_code == 200


def test_an_unknown_task_is_a_404(client):
    assert code(post(client, "nx-task-999", ["commit:x"]), 404) == "not_found"


# --- Direct calls ----------------------------------------------------------------------------


def direct(client, ref):
    session = client.app.state.sessionmaker()
    return session, session.get(Task, int(ref[8:]))


def test_a_direct_call_checks_what_the_api_checks(client):
    ref = closed(client)
    session, task = direct(client, ref)
    with session:
        with pytest.raises(RuleViolation) as exc:
            service.attach_evidence(session, task, "commit:abc", "loic")
        assert exc.value.code == "invalid_evidence"
        with pytest.raises(RuleViolation) as exc:
            service.attach_evidence(session, task, ["x" * 513], "loic")
        assert exc.value.code == "too_long_evidence"
        for bad in ([5], ["commit:ok", None], {"a": "b"}, None):
            with pytest.raises(RuleViolation) as exc:
                service.attach_evidence(session, task, bad, "loic")
            assert exc.value.code == "invalid_evidence"
        session.rollback()
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:abc"]


def test_a_lone_surrogate_gives_invalid_value_with_the_event_message(client):
    ref = closed(client)
    session, task = direct(client, ref)
    with session:
        for bad in (["commit:a\ud800"], ("commit:\udfff",)):
            with pytest.raises(RuleViolation) as exc:
                service.attach_evidence(session, task, bad, "loic")
            assert exc.value.code == "invalid_value"
            assert exc.value.message == (
                "valeur non encodable : demi-paire UTF-16, NaN ou Infinity"
            )


def test_a_tuple_is_accepted_and_stored_as_a_list(client):
    ref = closed(client)
    session, task = direct(client, ref)
    with session:
        service.attach_evidence(session, task, ("commit:t",), "loic")
        session.commit()
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:abc", "commit:t"]


def test_a_direct_call_masks_secrets_itself(client):
    ref = closed(client)
    session, task = direct(client, ref)
    with session:
        service.attach_evidence(session, task, [f"commit:def token={SECRET}"], "loic")
        session.commit()
    assert SECRET not in client.get(f"/api/tasks/{ref}").text
    actions = [h["action"] for h in client.get(f"/api/tasks/{ref}/history").json()]
    assert "secret_redacted" in actions


# --- Stripping: the stored value is the one measured -----------------------------------------


@pytest.mark.parametrize("raw", [" commit:abc ", "\x1ccommit:abc", "commit:abc "])
def test_every_path_strips_like_the_api(client, raw):
    expected = API_STRIP.validate_python(raw)
    by_service = made(client)
    session, task = direct(client, by_service)
    with session:
        service.attach_evidence(session, task, [raw], "loic")
        session.commit()
    assert client.get(f"/api/tasks/{by_service}").json()["evidence"] == [expected]

    by_status = made(client)
    session, task = direct(client, by_status)
    with session:
        service.change_status(session, task, "in_progress", "loic")
        service.change_status(session, task, "done", "loic", evidence=[raw])
        session.commit()
    assert client.get(f"/api/tasks/{by_status}").json()["evidence"] == [expected]


def test_the_same_evidence_through_status_then_the_route_is_stored_once(client):
    ref = made(client)
    move(client, ref, "in_progress")
    session, task = direct(client, ref)
    with session:
        service.change_status(session, task, "review", "loic", evidence=["\x1ccommit:abc"])
        session.commit()
    assert code(post(client, ref, ["\x1ccommit:abc"])) == "evidence_unchanged"


def test_evidence_joined_by_an_event_then_posted_again_is_unchanged(client):
    ref = made(client, status="todo")
    event = client.post("/api/events", json={
        "id": "e1", "at": AT, "actor": "helios", "kind": "working", "subject": "s", "task": ref,
        "payload": {"run_ref": "r1"}})
    assert event.status_code == 201
    done = client.post("/api/events", json={
        "id": "e2", "at": AT, "actor": "helios", "kind": "done", "subject": "fini", "task": ref,
        "run": "r1", "evidence": ["commit:evt"]})
    assert done.json()["effects"] == [{"action": "status:done", "applied": True}]
    assert code(post(client, ref, ["commit:evt"])) == "evidence_unchanged"
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:evt"]


# --- Concurrency -----------------------------------------------------------------------------


def test_two_concurrent_posts_do_not_lose_evidence(client, monkeypatch):
    ref = closed(client)
    real = service.attach_evidence

    def wrapper(session, task, evidence, actor):
        with client.app.state.sessionmaker() as other:
            real(other, other.get(Task, int(ref[8:])), ["commit:first"], "helios")
            other.commit()
        return real(session, task, evidence, actor)

    monkeypatch.setattr(service, "attach_evidence", wrapper)
    res = post(client, ref, ["commit:second"])
    assert res.status_code == 409 and res.json()["detail"]["code"] == "concurrent_update"

    monkeypatch.setattr(service, "attach_evidence", real)
    assert post(client, ref, ["commit:second"]).status_code == 200
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == [
        "commit:abc", "commit:first", "commit:second"
    ]


# --- Review follow-ups ---------------------------------------------------------------------


def test_a_direct_call_refuses_a_blank_item_like_the_api(client):
    ref = closed(client)
    assert post(client, ref, ["   ", "commit:a"]).status_code == 422
    session, task = direct(client, ref)
    with session:
        for bad in (["   ", "commit:a"], [""], ["\n\t"]):
            with pytest.raises(RuleViolation) as exc:
                service.attach_evidence(session, task, bad, "loic")
            assert exc.value.code == "invalid_evidence"  # as publish() answers
        session.rollback()
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:abc"]


def test_an_item_blank_only_after_masking_is_dropped_and_the_others_kept(client):
    # Spec §3: masking comes first, then the readable-reference filter (as for an event).
    ref = closed(client)
    session, task = direct(client, ref)
    with session:
        service.attach_evidence(session, task, [f"commit: {SECRET}", "commit:a"], "loic")
        session.commit()
    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == ["commit:abc", "commit:a"]


@pytest.mark.parametrize("raw", [
    "commit:abc token=" + SECRET,  # masked form is already attached below
    "commit: " + SECRET,  # reduced to a label: evidence_required
])
def test_the_secret_alert_fires_even_when_the_request_is_refused(client, caplog, raw):
    ref = closed(client)
    assert post(client, ref, ["commit:abc token=" + SECRET]).status_code == 200
    caplog.clear()
    with caplog.at_level("WARNING", logger="nexus.tasks"):
        res = post(client, ref, [raw])
    assert res.status_code == 409
    alerts = [r for r in caplog.records if "secret masqué" in r.getMessage()]
    assert len(alerts) == 1
    assert SECRET not in caplog.text and SECRET not in res.text
    # The history line stays success-only: the 409 rolled the transaction back.
    secret_lines = [h for h in client.get(f"/api/tasks/{ref}/history").json()
                    if h["action"] == "secret_redacted"]
    assert len(secret_lines) == 1


def test_a_lone_surrogate_in_a_direct_call_stores_nothing_and_the_task_still_reads(client):
    ref = closed(client)
    session, task = direct(client, ref)
    with session:
        with pytest.raises(RuleViolation) as exc:
            service.attach_evidence(session, task, ["commit:a\ud800"], "loic")
        assert exc.value.code == "invalid_value"
        session.commit()
    res = client.get(f"/api/tasks/{ref}")
    assert res.status_code == 200 and res.json()["evidence"] == ["commit:abc"]
    assert client.get(f"/api/tasks/{ref}/history").status_code == 200
