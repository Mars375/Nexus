"""The optional « suite de » link (ADR-022, #65): from the task that corrects to a done one."""

import pytest
from sqlalchemy import select

from nexus.models import Task
from nexus.tasks import service
from nexus.tasks.rules import RuleViolation

SECRET = "ghp_" + "A" * 36


def create(client, **fields):
    body = {"title": "Pont lecture", "objective": "Lire les runs Hermes",
            "next_action": "relever"} | fields
    return client.post("/api/tasks", json=body)


def made(client, **fields):
    res = create(client, **fields)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def move(client, ref, status, **fields):
    return client.post(f"/api/tasks/{ref}/status", json={"status": status} | fields)


def done(client):
    ref = made(client)
    move(client, ref, "in_progress")
    assert move(client, ref, "done", evidence=["commit:abc"]).status_code == 200
    return ref


def padded(ref, width=4):
    return f"nx-task-{int(ref[8:]):0{width}d}"


def code(res, status=409):
    assert res.status_code == status, res.text
    return res.json()["detail"]["code"]


def snapshot(client, ref):
    history = [{k: v for k, v in h.items() if k != "measured_at"}
               for h in client.get(f"/api/tasks/{ref}/history").json()]
    with client.app.state.sessionmaker() as session:
        version = session.scalar(select(Task.version).where(Task.id == int(ref[8:])))
    task = client.get(f"/api/tasks/{ref}").json()
    task.pop("measured_at")
    return task, history, version


def test_a_task_has_no_link_by_default(client):
    assert client.get(f"/api/tasks/{made(client)}").json()["follows"] is None


def test_a_follow_up_is_created_against_a_done_task(client):
    target = done(client)
    res = create(client, follows=target)
    assert res.status_code == 201
    assert res.json()["follows"] == target
    ref = res.json()["id"]
    assert client.get(f"/api/tasks/{ref}").json()["follows"] == target
    [created] = client.get(f"/api/tasks/{ref}/history").json()
    assert created["changes"]["follows"] == [None, target]
    # Nothing is written on the old task, and the link is not a dependency.
    assert client.get(f"/api/tasks/{target}").json()["depends_on"] == []
    assert client.get(f"/api/tasks/{ref}").json()["depends_on"] == []
    assert move(client, ref, "in_progress").status_code == 200


def test_the_reference_is_read_as_a_number_and_stored_without_its_zeros(client):
    target = done(client)
    res = create(client, follows=padded(target))
    assert res.status_code == 201 and res.json()["follows"] == target
    [created] = client.get(f"/api/tasks/{res.json()['id']}/history").json()
    assert created["changes"]["follows"] == [None, target]


@pytest.mark.parametrize("value", [
    "nx-task-" + "1" * 13, "nx-task-²", "nx-task-1\n", 5, "", "task-1", "nx-task-", SECRET,
])
def test_an_invalid_reference_is_a_422_that_does_not_echo_it(client, value):
    ref = made(client)
    for res in (create(client, follows=value),
                client.patch(f"/api/tasks/{ref}", json={"follows": value})):
        assert res.status_code == 422, res.text
        assert "follows" in res.text
        if isinstance(value, str) and value:
            assert value not in res.text


def test_an_unknown_target_is_a_404_with_the_reformatted_reference(client):
    res = create(client, follows="nx-task-0999")
    assert code(res, 404) == "not_found"
    assert res.json()["detail"]["message"].endswith("nx-task-999")
    assert "0999" not in res.text
    ref = made(client)
    res = client.patch(f"/api/tasks/{ref}", json={"follows": "nx-task-999"})
    assert code(res, 404) == "not_found"


def targets(client):
    out = {"backlog": made(client)}
    out["todo"] = made(client, status="todo")
    out["in_progress"] = made(client)
    move(client, out["in_progress"], "in_progress")
    out["blocked"] = made(client)
    move(client, out["blocked"], "in_progress")
    move(client, out["blocked"], "blocked", block_cause="c", block_plan="p")
    out["review"] = made(client)
    move(client, out["review"], "in_progress")
    move(client, out["review"], "review")
    out["dropped"] = made(client)
    move(client, out["dropped"], "dropped", reason="r")
    return out


def test_only_a_done_task_can_be_followed(client):
    for status, target in targets(client).items():
        res = create(client, follows=target)
        assert code(res) == "follows_not_done", status
        assert res.json()["detail"]["message"] == (
            f"follows : {target} n'est pas terminée ; une tâche de suite ne suit qu'une tâche "
            "terminée"
        )
        ref = made(client)
        res = client.patch(f"/api/tasks/{ref}", json={"follows": target})
        assert code(res) == "follows_not_done", status
        assert client.get(f"/api/tasks/{ref}").json()["follows"] is None


def test_a_task_cannot_follow_itself(client):
    ref = made(client)
    assert code(client.patch(f"/api/tasks/{ref}", json={"follows": ref})) == "follows_not_done"


def test_the_link_is_set_changed_and_removed_with_patch(client):
    first, second = done(client), done(client)
    ref = made(client)
    assert client.patch(f"/api/tasks/{ref}", json={"follows": first}).json()["follows"] == first
    res = client.patch(f"/api/tasks/{ref}", json={"follows": padded(second)})
    assert res.json()["follows"] == second
    assert client.patch(f"/api/tasks/{ref}", json={"follows": None}).json()["follows"] is None
    updates = [h["changes"] for h in client.get(f"/api/tasks/{ref}/history").json()
               if h["action"] == "updated"]
    assert updates == [
        {"follows": [None, first]}, {"follows": [first, second]}, {"follows": [second, None]},
    ]


@pytest.mark.parametrize("closed", [False, True])
def test_the_same_reference_written_differently_changes_nothing(client, closed):
    target = done(client)
    ref = made(client, follows=target)
    if closed:
        move(client, ref, "in_progress")
        move(client, ref, "done", evidence=["commit:abc"])
    before = snapshot(client, ref)
    for value in (padded(target, 2), padded(target, 6), target):
        assert client.patch(f"/api/tasks/{ref}", json={"follows": value}).status_code == 200
    assert snapshot(client, ref) == before


def test_a_follow_up_can_be_followed_in_a_chain_and_a_task_by_several(client):
    a = done(client)
    b = made(client, follows=a)
    move(client, b, "in_progress")
    move(client, b, "done", evidence=["commit:b"])
    c = made(client, follows=b)
    d = made(client, follows=a)
    assert client.get(f"/api/tasks/{c}").json()["follows"] == b
    assert client.get(f"/api/tasks/{d}").json()["follows"] == a


# --- On a done task: the state is judged before the target ---------------------------------


def test_on_a_done_task_the_state_is_judged_before_the_target(client):
    own = done(client)
    other_done = done(client)
    open_task = made(client)
    for value in ("nx-task-999", open_task, other_done):
        assert code(client.patch(f"/api/tasks/{own}", json={"follows": value})) == "task_done"
    before = snapshot(client, own)
    assert client.patch(f"/api/tasks/{own}", json={"follows": None}).status_code == 200
    assert snapshot(client, own) == before


def test_on_an_open_task_an_unknown_target_is_a_404(client):
    ref = made(client)
    assert code(client.patch(f"/api/tasks/{ref}", json={"follows": "nx-task-999"}), 404) == (
        "not_found"
    )


# --- Direct calls ----------------------------------------------------------------------------


def test_a_direct_call_with_a_non_text_reference_is_refused(client):
    with client.app.state.sessionmaker() as session:
        with pytest.raises(RuleViolation) as exc:
            service.create_task(
                session, {"title": "t", "objective": "o", "follows": 5}, "loic"
            )
        assert exc.value.code == "invalid_follows"
        ref = made(client)
        task = session.get(Task, int(ref[8:]))
        for bad in (5, "nx-task-x", "nx-task-1\n", "nx-task-²", ["nx-task-1"]):
            with pytest.raises(RuleViolation) as exc:
                service.update_task(session, task, {"follows": bad}, "loic")
            assert exc.value.code == "invalid_follows"
            assert exc.value.message == "follows : référence de tâche invalide"


# --- Concurrency -----------------------------------------------------------------------------


def test_a_follows_patch_racing_the_closing_loses_then_gets_task_done(client, monkeypatch):
    target = done(client)
    ref = made(client)
    move(client, ref, "in_progress")
    real = service.update_task

    def wrapper(session, task, *args, **kwargs):
        with client.app.state.sessionmaker() as other:
            service.change_status(other, other.get(Task, int(ref[8:])), "done", "loic",
                                  evidence=["commit:abc"])
            other.commit()
        return real(session, task, *args, **kwargs)

    monkeypatch.setattr(service, "update_task", wrapper)
    res = client.patch(f"/api/tasks/{ref}", json={"follows": target})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "concurrent_update"
    assert client.get(f"/api/tasks/{ref}").json()["follows"] is None

    monkeypatch.setattr(service, "update_task", real)
    assert code(client.patch(f"/api/tasks/{ref}", json={"follows": target})) == "task_done"
