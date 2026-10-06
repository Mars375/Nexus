"""Direct service calls by an adapter (no HTTP layer): containers must be normalised or refused."""

from datetime import datetime

import pytest

from nexus.events import service
from nexus.events.rules import Envelope
from nexus.models import Event
from nexus.tasks.rules import RuleViolation

AT = datetime.fromisoformat("2026-09-28T09:05:00+02:00")


def make_task(client, **fields):
    body = {"title": "Pont lecture", "objective": "Lire les runs"} | fields
    return client.post("/api/tasks", json=body).json()["id"]


def direct(client, envelope, id):
    """Publish through the service on its own session, as an adapter would."""
    with client.app.state.sessionmaker() as session:
        event, created = service.publish(session, envelope, id, AT)
        session.commit()
        return event.id, created


def question(ref=None, **fields):
    base = {"actor": "helios", "kind": "question", "subject": "Où est la clé ?", "task": ref,
            "needs": ["loic"]}
    return Envelope(**(base | fields))


def test_needs_tuple_resent_identically_is_a_read_back(client):
    first = direct(client, question(needs=("loic",)), "evt_a")
    second = direct(client, question(needs=("loic",)), "evt_a")

    assert first[1] is True
    assert second == (first[0], False)


@pytest.mark.parametrize(
    ("first", "second"),
    [(("loic",), ("loic",)), (["loic"], ("loic",)), (("loic",), ["loic"])],
)
def test_same_fact_with_needs_tuple_under_another_id_is_noise(client, first, second):
    ref = make_task(client)
    direct(client, question(ref, needs=first), "evt_a")

    with pytest.raises(RuleViolation) as exc:
        direct(client, question(ref, needs=second), "evt_b")

    assert exc.value.code == "noise"


def test_needs_and_evidence_tuples_are_stored_as_lists(client):
    with client.app.state.sessionmaker() as session:
        event, _ = service.publish(
            session, question(needs=("loic",), evidence=("commit:abc",)), "evt_a", AT
        )
        assert type(event.needs) is list
        assert type(event.evidence) is list


def test_handoff_with_needs_tuple_resent_is_a_read_back(client):
    ref = make_task(client, next_action="x")
    envelope = dict(kind="handoff", subject="À toi", needs=("aether",),
                    payload={"next_action": "poser la clé"})
    first = direct(client, question(ref, **envelope), "evt_a")
    second = direct(client, question(ref, **envelope), "evt_a")

    assert second == (first[0], False)
    task = client.get(f"/api/tasks/{ref}").json()
    assert task["lead_agent"] == "aether"
    history = client.get(f"/api/tasks/{ref}/history").json()
    assert [h["action"] for h in history].count("updated") == 1


def test_nested_tuples_in_payload_keep_idempotency_and_noise(client):
    ref = make_task(client)
    payload = {"steps": (("a", 1), ("b", 2))}
    first = direct(client, question(ref, payload=payload), "evt_a")
    assert direct(client, question(ref, payload=payload), "evt_a") == (first[0], False)

    with pytest.raises(RuleViolation) as exc:
        direct(client, question(ref, payload=payload), "evt_b")
    assert exc.value.code == "noise"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("needs", None, "invalid_needs"),
        ("needs", "loic", "invalid_needs"),
        ("needs", [["loic"]], "invalid_needs"),
        ("needs", [1], "invalid_needs"),
        ("evidence", None, "invalid_evidence"),
        ("evidence", "commit:abc", "invalid_evidence"),
        ("evidence", [1], "invalid_evidence"),
        ("payload", None, "invalid_payload"),
        ("payload", [1], "invalid_payload"),
        ("payload", (("a", 1),), "invalid_payload"),
    ],
)
def test_malformed_containers_from_an_adapter_are_refused_not_crash(client, field, value, code):
    envelope = question(**{field: value})

    with pytest.raises(RuleViolation) as exc:
        direct(client, envelope, "evt_a")

    assert exc.value.code == code
    if isinstance(value, str):
        assert value not in exc.value.message  # the received value is never echoed
    with client.app.state.sessionmaker() as session:
        assert session.query(Event).count() == 0


def test_evidence_string_never_reaches_the_task_char_by_char(client):
    ref = make_task(client, next_action="x")
    direct(client, question(ref, kind="working", subject="r1", payload={"run_ref": "r1"}), "evt_a")

    with pytest.raises(RuleViolation):
        direct(client, question(ref, kind="review", subject="fini", run="r1",
                                evidence="commit:abc"), "evt_b")

    assert client.get(f"/api/tasks/{ref}").json()["evidence"] == []
    assert client.get("/api/events").status_code == 200


# Truthy and falsy alike: a check written as `if value and not isinstance(...)` must not pass.
WRONG_TYPES = [42, True, ["x"], {"a": 1}, b"x", 0, False, [], {}, b""]


@pytest.mark.parametrize("value", WRONG_TYPES)
@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("actor", "invalid_actor"),
        ("kind", "invalid_kind"),
        ("subject", "invalid_subject"),
        ("task", "invalid_task"),
        ("run", "invalid_run"),
        ("body", "invalid_body"),
    ],
)
def test_wrong_scalar_types_from_an_adapter_are_refused_not_crash(client, field, code, value):
    with pytest.raises(RuleViolation) as exc:
        direct(client, question(**{field: value}), "evt_a")

    assert exc.value.code == code
    assert str(value) not in exc.value.message  # the received value is never echoed
    with client.app.state.sessionmaker() as session:
        assert session.query(Event).count() == 0
    assert client.get("/api/events").status_code == 200


@pytest.mark.parametrize("value", [*WRONG_TYPES, None])
def test_wrong_event_id_type_from_an_adapter_is_refused_not_crash(client, value):
    with pytest.raises(RuleViolation) as exc:
        direct(client, question(), value)

    assert exc.value.code == "invalid_event_id"
    assert str(value) not in exc.value.message
    with client.app.state.sessionmaker() as session:
        assert session.query(Event).count() == 0


def test_valid_scalars_and_unknown_values_keep_their_behaviour(client):
    ref = make_task(client)
    _, created = direct(client, question(ref, run="r1", body="détail"), "evt_a")
    assert created is True
    _, created = direct(client, question(None, task=None, run=None, body=None,
                                         subject="Autre question"), "evt_b")
    assert created is True

    for fields, code in [({"actor": "zzz"}, "unknown_actor"), ({"kind": "zzz"}, "unknown_kind"),
                         ({"subject": "  "}, "subject_required")]:
        with pytest.raises(RuleViolation) as exc:
            direct(client, question(**fields), "evt_c")
        assert exc.value.code == code
    with pytest.raises(RuleViolation) as exc:
        direct(client, question(), "")
    assert exc.value.code == "event_id_required"


# Limits the HTTP model caps (#42): (field, limit, code, how to build the direct call).
LIMITS = [
    ("id", 128, "too_long_id"),
    ("run", 128, "too_long_run"),
    ("subject", 500, "too_long_subject"),
    ("evidence", 512, "too_long_evidence"),
]


def _direct_call(field, size):
    """Direct-call arguments (envelope, id) with one field of `size` characters."""
    value = "x" * size
    if field == "id":
        return question(), value
    if field == "evidence":
        return question(evidence=[value]), "evt_a"
    return question(**{field: value}), "evt_a"


def _http_body(field, size):
    value = "x" * size
    body = {"id": "evt_a", "at": AT.isoformat(), "actor": "helios", "kind": "question",
            "subject": "Où est la clé ?", "needs": ["loic"]}
    body["evidence" if field == "evidence" else field] = [value] if field == "evidence" else value
    return body


@pytest.mark.parametrize(("field", "limit", "code"), LIMITS)
def test_value_at_the_limit_is_accepted_from_an_adapter(client, field, limit, code):
    envelope, event_id = _direct_call(field, limit)

    _, created = direct(client, envelope, event_id)

    assert created is True


@pytest.mark.parametrize(("field", "limit", "code"), LIMITS)
def test_value_over_the_limit_is_refused_from_an_adapter(client, field, limit, code):
    envelope, event_id = _direct_call(field, limit + 1)

    with pytest.raises(RuleViolation) as exc:
        direct(client, envelope, event_id)

    assert exc.value.code == code
    assert str(limit) in exc.value.message
    assert "xxxxx" not in exc.value.message  # the received value is never echoed
    with client.app.state.sessionmaker() as session:
        assert session.query(Event).count() == 0
    assert client.get("/api/events").status_code == 200


@pytest.mark.parametrize(("field", "limit", "code"), LIMITS)
def test_http_route_refuses_the_same_overlong_values(client, field, limit, code):
    # Proves the service and the API enforce the same limits (shared constants).
    assert client.post("/api/events", json=_http_body(field, limit)).status_code == 201
    over = _http_body(field, limit + 1)
    if field != "id":
        over["id"] = "evt_b"

    assert client.post("/api/events", json=over).status_code == 422


def test_evidence_length_is_measured_after_stripping_like_the_api(client):
    padded = "  " + "e" * 512 + "  "

    assert client.post("/api/events", json=_http_body("evidence", 0) | {"evidence": [padded]}
                       ).status_code == 201
    _, created = direct(client, question(evidence=[padded], subject="Autre"), "evt_c")
    assert created is True

    with pytest.raises(RuleViolation) as exc:
        direct(client, question(evidence=["  " + "e" * 513 + "  "]), "evt_b")
    assert exc.value.code == "too_long_evidence"
