"""POST /api/tasks/<ref>/status: fields that apply to the target status."""

from datetime import datetime

import pytest

from nexus.tasks import service
from nexus.tasks.rules import STATUS_CHANGE_TARGETS, STATUSES, RuleViolation

SECRET = "ghp_" + "A" * 36


def create(client, **fields):
    body = {"title": "Pont lecture", "objective": "Lire les runs Hermes"} | fields
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def move(client, ref, status, **fields):
    return client.post(f"/api/tasks/{ref}/status", json={"status": status} | fields)


STATUS_FIELD_VALUES = {
    "reason": "motif",
    "block_cause": "cause",
    "block_plan": "plan",
    "follow_up_at": "2026-11-01T09:00:00+01:00",
    "evidence": ["commit:a1b2c3d"],
    "role": "main",
}

INAPPLICABLE_FIELDS = [
    (target, field, STATUS_FIELD_VALUES[field])
    for field, targets in STATUS_CHANGE_TARGETS.items()
    for target in STATUSES
    if target not in targets
]


@pytest.mark.parametrize(("target", "field", "value"), INAPPLICABLE_FIELDS)
def test_field_inapplicable_to_the_target_is_refused(client, target, field, value):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")

    res = move(client, ref, target, **{field: value})

    assert res.status_code == 422, res.text
    (error,) = res.json()["detail"]
    assert error["loc"] == ["body", field]
    assert error["msg"] == f"{field} : champ inapplicable au statut « {target} »"
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "in_progress"


def test_every_inapplicable_field_is_named(client):
    ref = create(client, next_action="x")["id"]

    res = move(client, ref, "backlog", evidence=["commit:a1b2c3d"], block_cause="c", role="main")

    assert res.status_code == 422, res.text
    assert {error["loc"][-1] for error in res.json()["detail"]} == {
        "evidence",
        "block_cause",
        "role",
    }


def test_inapplicable_field_never_echoes_its_value(client):
    ref = create(client, next_action="x")["id"]

    res = move(client, ref, "todo", evidence=[f"token={SECRET}"])

    assert res.status_code == 422
    assert SECRET not in res.text


def test_a_provided_but_null_field_is_refused_too(client):
    ref = create(client, next_action="x")["id"]

    res = move(client, ref, "todo", evidence=None)

    assert res.status_code == 422, res.text
    assert res.json()["detail"][0]["loc"] == ["body", "evidence"]


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("todo", "evidence", "pas-une-liste"),
        ("todo", "follow_up_at", "pas-une-date"),
        ("todo", "role", 3),
    ],
)
def test_inapplicable_field_is_refused_before_its_type_is_judged(client, target, field, value):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")

    res = move(client, ref, target, **{field: value})

    assert res.status_code == 422, res.text
    (error,) = res.json()["detail"]
    assert error["loc"] == ["body", field]
    assert error["msg"] == f"{field} : champ inapplicable au statut « {target} »"


def test_invalid_value_on_an_applicable_field_keeps_its_own_error(client):
    ref = create(client, next_action="x")["id"]
    move(client, ref, "in_progress")

    res = move(client, ref, "done", evidence="pas-une-liste")

    assert res.status_code == 422, res.text
    (error,) = res.json()["detail"]
    assert error["loc"] == ["body", "evidence"]
    assert "champ inapplicable" not in error["msg"]


def test_applicable_fields_are_accepted_per_target(client):
    ref = create(client, next_action="x")["id"]

    prepared = move(client, ref, "in_progress", role="main", next_action="suite")
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["operation_role"] == "main"
    blocked = move(
        client,
        ref,
        "blocked",
        block_cause="SSH",
        block_plan="clé",
        follow_up_at="2026-11-01T09:00:00+01:00",
    )
    assert blocked.status_code == 200, blocked.text
    assert move(client, ref, "in_progress").status_code == 200
    reviewed = move(client, ref, "review", evidence=["commit:a1b2c3d"])
    assert reviewed.json()["evidence"] == ["commit:a1b2c3d"]
    dropped = move(client, ref, "dropped", reason="doublon")
    assert dropped.json()["drop_reason"] == "doublon"


DIRECT_FIELD_VALUES = {
    "reason": "motif",
    "block_cause": "cause",
    "block_plan": "plan",
    "follow_up_at": datetime.fromisoformat("2026-11-01T09:00:00+01:00"),
    "role": "main",
}

DIRECT_INAPPLICABLE_FIELDS = [
    ("done", field) for field in DIRECT_FIELD_VALUES if "done" not in STATUS_CHANGE_TARGETS[field]
]


@pytest.mark.parametrize(("target", "field"), DIRECT_INAPPLICABLE_FIELDS)
def test_a_direct_status_change_refuses_an_inapplicable_field(client, target, field):
    ref = create(client, next_action="x")["id"]
    assert move(client, ref, "in_progress").status_code == 200
    history_before = client.get(f"/api/tasks/{ref}/history").json()

    make = client.app.state.sessionmaker
    with make() as session:
        task = service.get_task(session, int(ref.removeprefix("nx-task-")))
        with pytest.raises(RuleViolation) as exc:
            service.change_status(
                session, task, target, "loic", **{field: DIRECT_FIELD_VALUES[field]}
            )
        assert exc.value.code == "field_inapplicable"
        assert exc.value.message == f"{field} : champ inapplicable au statut « {target} »"
        session.rollback()

    got = client.get(f"/api/tasks/{ref}").json()
    assert got["status"] == "in_progress"
    history_after = client.get(f"/api/tasks/{ref}/history").json()
    assert [h["action"] for h in history_after] == [h["action"] for h in history_before]


# The applicability table written by hand: INAPPLICABLE_FIELDS above is derived from
# STATUS_CHANGE_TARGETS, so widening that table by mistake would shrink the tested pairs
# instead of failing a test. This one pins the table itself.
EXPECTED_STATUS_CHANGE_TARGETS = {
    "reason": {"dropped"},
    "block_cause": {"blocked"},
    "block_plan": {"blocked"},
    "follow_up_at": {"blocked"},
    "evidence": {"done", "review"},
    "role": {"in_progress"},
}


def test_the_applicability_table_is_the_documented_one():
    assert {f: set(t) for f, t in STATUS_CHANGE_TARGETS.items()} == EXPECTED_STATUS_CHANGE_TARGETS


DIRECT_EXTRA_INAPPLICABLE = [
    ("todo", "evidence", ["commit:a1b2c3d"]),
    ("in_progress", "evidence", ["commit:a1b2c3d"]),
    ("blocked", "evidence", ["commit:a1b2c3d"]),
    ("blocked", "reason", "motif"),
    ("review", "reason", "motif"),
    ("done", "role", "main"),
]


@pytest.mark.parametrize(("target", "field", "value"), DIRECT_EXTRA_INAPPLICABLE)
def test_a_direct_status_change_refuses_more_inapplicable_pairs(client, target, field, value):
    ref = create(client, next_action="x")["id"]
    assert move(client, ref, "in_progress").status_code == 200
    make = client.app.state.sessionmaker
    with make() as session:
        task = service.get_task(session, int(ref.removeprefix("nx-task-")))
        with pytest.raises(RuleViolation) as exc:
            service.change_status(session, task, target, "loic", **{field: value})
        assert exc.value.code == "field_inapplicable"
        session.rollback()
    assert client.get(f"/api/tasks/{ref}").json()["status"] == "in_progress"


@pytest.mark.parametrize(
    "target",
    [SECRET, ["done"], {"a": 1}, 7, "inconnu"],
    ids=["secret-looking", "list", "dict", "int", "unknown-word"],
)
def test_a_direct_unknown_target_is_refused_without_quoting_it(client, target):
    ref = create(client, next_action="x")["id"]
    make = client.app.state.sessionmaker
    with make() as session:
        task = service.get_task(session, int(ref.removeprefix("nx-task-")))
        with pytest.raises(RuleViolation) as exc:
            service.change_status(session, task, target, "loic", evidence=["commit:a1b2c3d"])
        assert exc.value.code == "unknown_status"
        assert SECRET not in exc.value.message
        session.rollback()
