"""`run_changed` (ADR-023, lot D): the live feed says a run of a task moved, never its content."""

from runs_support import dispatch, make_task, register, tick

from nexus.live import changes_since, current_cursor


def messages_after(client, start):
    with client.app.state.sessionmaker() as s:
        return changes_since(s, start)[0]


def run_changed(messages):
    return [m for m in messages if m["type"] == "run_changed"]


def test_handing_a_task_over_says_the_runs_of_that_task_changed(client):
    register(client)
    task = make_task(client)
    with client.app.state.sessionmaker() as s:
        start = current_cursor(s)

    dispatch(client, task)

    [message] = run_changed(messages_after(client, start))
    assert message["task"] == task and "cursor" in message
    assert set(message) == {"type", "task", "cursor"}  # no brief, no status, no reference


def test_asking_for_a_cancel_says_it_too(client):
    register(client)
    task = make_task(client)
    dispatch(client, task)
    with client.app.state.sessionmaker() as s:
        start = current_cursor(s)

    client.post("/api/runs/nx-run-1/cancel")

    assert [m["task"] for m in run_changed(messages_after(client, start))] == [task]


def test_what_the_supervisor_publishes_for_a_run_says_it_too(client):
    register(client)
    task = make_task(client)
    dispatch(client, task)
    with client.app.state.sessionmaker() as s:
        start = current_cursor(s)

    tick(client)  # claimed, working, done: events carrying nx-run-1

    assert [m["task"] for m in run_changed(messages_after(client, start))] == [task]


def test_a_plain_task_change_says_nothing_about_runs(client):
    task = make_task(client)
    with client.app.state.sessionmaker() as s:
        start = current_cursor(s)

    client.patch(f"/api/tasks/{task}", json={"title": "Autre"})

    assert run_changed(messages_after(client, start)) == []


def test_a_status_written_by_the_supervisor_is_announced_after_its_commit(client):
    from sqlalchemy import select

    from nexus.models import TaskHistory

    register(client)
    task = make_task(client)
    dispatch(client, task)

    tick(client)  # the run goes from dispatched to done

    with client.app.state.sessionmaker() as s:
        actions = list(s.scalars(select(TaskHistory.action).order_by(TaskHistory.id)))
    assert "run_status" in actions  # the live feed says it AFTER the run row is written
    assert actions.index("run_status") > actions.index("run_created")
