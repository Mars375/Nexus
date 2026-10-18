"""A done task is final (ADR-022, #65): no transition out, no edit, no new dependency."""

import pytest
from sqlalchemy import select

from nexus.models import Task
from nexus.tasks import rules, service
from nexus.tasks.rules import RuleViolation

DONE_IS_FINAL = (
    "tâche terminée : elle ne se modifie plus ; commente-la, joins-lui une preuve ou ouvre "
    "une tâche de suite"
)
SECRET = "ghp_" + "A" * 36


def create(client, **fields):
    body = {"title": "Pont lecture", "objective": "Lire les runs Hermes",
            "next_action": "relever"} | fields
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def move(client, ref, status, **fields):
    return client.post(f"/api/tasks/{ref}/status", json={"status": status} | fields)


def close(client, **fields):
    """A task closed with evidence, with every optional field filled."""
    ref = create(
        client, lead_agent="helios", collaborators=["claude"], due_at="2030-01-01T00:00:00+00:00",
        follow_up_at="2030-02-01T00:00:00+00:00", expected_evidence="commit", origin="issue",
        context=["a"], **fields,
    )
    assert move(client, ref, "in_progress").status_code == 200
    res = move(client, ref, "done", evidence=["commit:abc"])
    assert res.status_code == 200 and res.json()["status"] == "done", res.text
    return ref


def code(res):
    assert res.status_code == 409, res.text
    return res.json()["detail"]["code"]


def state(client, ref):
    task = client.get(f"/api/tasks/{ref}").json()
    task.pop("measured_at")
    history = [{k: v for k, v in h.items() if k != "measured_at"}
               for h in client.get(f"/api/tasks/{ref}/history").json()]
    with client.app.state.sessionmaker() as session:
        version = session.scalar(select(Task.version).where(Task.id == int(ref[8:])))
    return task, history, version


# --- Rules ---------------------------------------------------------------------------------


@pytest.mark.parametrize("target", [s for s in rules.STATUSES if s != "done"])
def test_nothing_leaves_done(target):
    assert rules.TRANSITIONS["done"] == frozenset()
    with pytest.raises(RuleViolation) as exc:
        rules.check_transition("done", target)
    assert exc.value.code == "task_done" and exc.value.message == DONE_IS_FINAL


def test_done_to_done_is_still_the_same_status():
    with pytest.raises(RuleViolation) as exc:
        rules.check_transition("done", "done")
    assert exc.value.code == "same_status"


def test_unknown_status_wins_over_done():
    with pytest.raises(RuleViolation) as exc:
        rules.check_transition("done", "archived")
    assert exc.value.code == "unknown_status"


def test_the_message_names_no_received_value_and_is_not_read_as_already_done():
    assert rules.DONE_IS_FINAL == DONE_IS_FINAL
    assert not DONE_IS_FINAL.startswith(("déjà en ", "la tâche est déjà en "))
    assert not DONE_IS_FINAL.endswith("est déjà l'agent principal")
    rules.check_not_done("in_progress")
    with pytest.raises(RuleViolation) as exc:
        rules.check_not_done("done")
    assert exc.value.code == "task_done"


# The payload only carries the fields its target applies (#17): a field sent to the wrong target
# is refused with 422 before the done-task rule could ever fire.
@pytest.mark.parametrize(
    ("target", "fields"),
    [
        ("in_progress", {}),
        ("todo", {}),
        ("blocked", {"block_cause": "c", "block_plan": "p"}),
        ("review", {}),
        ("backlog", {}),
    ],
)
def test_a_status_change_on_a_done_task_is_refused(client, target, fields):
    ref = close(client)
    before = state(client, ref)
    assert code(move(client, ref, target, **fields)) == "task_done"
    assert state(client, ref) == before


def test_an_agent_aiming_at_dropped_still_gets_403_before_the_state(client):
    ref = close(client)
    res = client.post(f"/api/tasks/{ref}/status", json={"status": "dropped", "reason": "r"},
                      headers={"X-Nexus-Actor": "helios"})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "human_only"


def test_dropped_can_still_be_taken_back(client):
    ref = create(client)
    assert move(client, ref, "dropped", reason="plus utile").status_code == 200
    assert move(client, ref, "backlog").status_code == 200


def test_a_comment_on_a_done_task_is_accepted(client):
    ref = close(client)
    res = client.post(f"/api/tasks/{ref}/comments", json={"body": "Relu : tout est bon"})
    assert res.status_code == 201


# --- PATCH ---------------------------------------------------------------------------------

CHANGES = {
    "title": "Autre titre", "objective": "Autre objectif", "lead_agent": "aether",
    "collaborators": ["codex"], "next_action": "autre", "due_at": "2031-01-01T00:00:00+00:00",
    "follow_up_at": "2031-02-01T00:00:00+00:00", "expected_evidence": "autre",
    "priority": "high", "operation_role": "main", "origin": "autre", "context": ["b"],
}
UNCHANGEABLE = ("human_owner",)  # the only human is Loïc: no other value exists


def test_every_updatable_field_has_a_case():
    assert set(CHANGES) | set(UNCHANGEABLE) | {"follows"} == service.UPDATABLE


@pytest.mark.parametrize("field", sorted(CHANGES))
def test_changing_any_field_of_a_done_task_is_refused_and_writes_nothing(client, field):
    ref = close(client)
    before = state(client, ref)
    res = client.patch(f"/api/tasks/{ref}", json={field: CHANGES[field]})
    assert code(res) == "task_done"
    assert res.json()["detail"]["message"] == DONE_IS_FINAL
    assert state(client, ref) == before


def test_a_patch_returning_the_same_values_changes_nothing_on_a_done_task(client):
    ref = close(client)
    before = state(client, ref)
    task = before[0]
    same = {f: task[f] for f in service.UPDATABLE - {"follows", "operation_role"}
            if f in task} | {"operation_role": None, "follows": None}
    assert client.patch(f"/api/tasks/{ref}", json=same).status_code == 200
    assert client.patch(f"/api/tasks/{ref}", json={}).status_code == 200
    assert state(client, ref) == before


def test_a_mixed_patch_is_refused_whole(client):
    ref = close(client)
    before = state(client, ref)
    res = client.patch(f"/api/tasks/{ref}", json={"title": before[0]["title"], "priority": "high"})
    assert code(res) == "task_done"
    assert state(client, ref) == before


def test_a_secret_pasted_again_in_a_masked_field_is_traced_but_changes_nothing(client):
    ref = create(client, objective=f"clé {SECRET}")
    move(client, ref, "in_progress")
    assert move(client, ref, "done", evidence=["commit:abc"]).status_code == 200
    task, history, version = state(client, ref)
    assert SECRET not in task["objective"]

    res = client.patch(f"/api/tasks/{ref}", json={"objective": f"clé {SECRET}"})

    assert res.status_code == 200 and SECRET not in res.text
    after, after_history, after_version = state(client, ref)
    assert after_version == version and after["updated_at"] == task["updated_at"]
    assert after["objective"] == task["objective"]
    assert len(after_history) == len(history) + 1
    assert after_history[-1]["action"] == "secret_redacted"


def test_a_working_event_refused_on_a_done_task_leaves_updated_at(client):
    ref = close(client)
    before = client.get(f"/api/tasks/{ref}").json()["updated_at"]
    res = client.post("/api/events", json={
        "id": "e1", "at": "2026-10-14T09:00:00+02:00", "actor": "helios", "kind": "working",
        "subject": "Je reprends", "task": ref, "payload": {"run_ref": "r1"}})
    assert res.status_code == 201
    assert res.json()["effects"] == [
        {"action": "status:in_progress", "applied": False, "reason": DONE_IS_FINAL}
    ]
    after = client.get(f"/api/tasks/{ref}").json()
    assert after["updated_at"] == before and after["status"] == "done"


# --- Dependencies --------------------------------------------------------------------------


def test_a_done_task_takes_no_new_dependency_but_a_repeated_put_is_a_noop(client):
    dep = create(client)
    other = create(client)
    done = create(client)
    client.put(f"/api/tasks/{done}/dependencies/{dep}")
    move(client, dep, "dropped", reason="plus utile")
    move(client, done, "in_progress")
    move(client, done, "done", evidence=["commit:abc"])
    before = state(client, done)

    assert client.put(f"/api/tasks/{done}/dependencies/{dep}").status_code == 204
    assert state(client, done) == before
    assert code(client.put(f"/api/tasks/{done}/dependencies/{other}")) == "task_done"
    assert client.put(f"/api/tasks/{done}/dependencies/{done}").status_code == 409
    assert client.put(f"/api/tasks/{done}/dependencies/{done}").json()["detail"]["code"] == (
        "self_dependency"
    )
    assert state(client, done) == before


def test_a_done_task_keeps_its_dependencies(client):
    dep = create(client)
    done = create(client)
    client.put(f"/api/tasks/{done}/dependencies/{dep}")
    move(client, dep, "dropped", reason="r")
    move(client, done, "in_progress")
    move(client, done, "done", evidence=["commit:abc"])
    before = state(client, done)

    assert code(client.delete(f"/api/tasks/{done}/dependencies/{dep}")) == "task_done"
    assert state(client, done) == before
    assert client.get(f"/api/tasks/{done}").json()["depends_on"] == [dep]
    other = create(client)
    assert client.delete(f"/api/tasks/{done}/dependencies/{other}").status_code == 404


def test_other_tasks_may_still_depend_on_a_done_task(client):
    done = close(client)
    dependent = create(client)
    assert client.put(f"/api/tasks/{dependent}/dependencies/{done}").status_code == 204
    assert move(client, dependent, "in_progress").status_code == 200
    assert client.delete(f"/api/tasks/{dependent}/dependencies/{done}").status_code == 204


def test_a_dependent_of_a_done_task_still_advances(client):
    done = close(client)
    dependent = create(client)
    client.put(f"/api/tasks/{dependent}/dependencies/{done}")
    assert move(client, dependent, "in_progress").status_code == 200


# --- Concurrency ---------------------------------------------------------------------------


def close_elsewhere(client, ref, monkeypatch, function):
    """Run `service.<function>` after another session has committed the closing of `ref`."""
    real = getattr(service, function)

    def wrapper(session, task, *args, **kwargs):
        with client.app.state.sessionmaker() as other:
            service.change_status(other, other.get(Task, int(ref[8:])), "done", "loic",
                                  evidence=["commit:abc"])
            other.commit()
        return real(session, task, *args, **kwargs)

    monkeypatch.setattr(service, function, wrapper)
    return lambda: monkeypatch.setattr(service, function, real)


def test_a_patch_racing_the_closing_loses_then_gets_task_done(client, monkeypatch):
    ref = create(client)
    move(client, ref, "in_progress")
    undo = close_elsewhere(client, ref, monkeypatch, "update_task")

    res = client.patch(f"/api/tasks/{ref}", json={"title": "Autre titre"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "concurrent_update"
    assert client.get(f"/api/tasks/{ref}").json()["title"] == "Pont lecture"

    undo()
    assert code(client.patch(f"/api/tasks/{ref}", json={"title": "Autre titre"})) == "task_done"


def test_a_dependency_racing_the_closing_loses_then_gets_task_done(client, monkeypatch):
    ref = create(client)
    other = create(client)
    move(client, other, "dropped", reason="r")  # resolved: an advanced task may depend on it
    move(client, ref, "in_progress")
    undo = close_elsewhere(client, ref, monkeypatch, "add_dependency")

    res = client.put(f"/api/tasks/{ref}/dependencies/{other}")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "concurrent_update"
    assert client.get(f"/api/tasks/{ref}").json()["depends_on"] == []

    undo()
    assert code(client.put(f"/api/tasks/{ref}/dependencies/{other}")) == "task_done"


def test_an_unlink_racing_the_closing_loses_then_gets_task_done(client, monkeypatch):
    ref = create(client)
    other = create(client)
    client.put(f"/api/tasks/{ref}/dependencies/{other}")
    move(client, other, "dropped", reason="r")
    move(client, ref, "in_progress")
    undo = close_elsewhere(client, ref, monkeypatch, "remove_dependency")

    res = client.delete(f"/api/tasks/{ref}/dependencies/{other}")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "concurrent_update"
    assert client.get(f"/api/tasks/{ref}").json()["depends_on"] == [other]

    undo()
    assert code(client.delete(f"/api/tasks/{ref}/dependencies/{other}")) == "task_done"


# --- Review follow-ups ---------------------------------------------------------------------


def test_a_refused_direct_update_task_leaves_the_done_task_untouched_even_after_a_commit(client):
    # The diff is computed before any setattr: a refusal must not leave a dirty task behind,
    # or the caller's next commit would write it.
    ref = close(client)
    before = state(client, ref)
    with client.app.state.sessionmaker() as session:
        task = session.get(Task, int(ref[8:]))
        with pytest.raises(RuleViolation) as exc:
            service.update_task(session, task, {"title": "Autre", "next_action": "ailleurs"},
                                "loic")
        assert exc.value.code == "task_done"
        session.commit()
    assert state(client, ref) == before


def test_a_done_task_takes_no_dependency_on_a_done_target_either(client):
    done = close(client)
    other_done = close(client)
    before = state(client, done)
    assert code(client.put(f"/api/tasks/{done}/dependencies/{other_done}")) == "task_done"
    assert state(client, done) == before
