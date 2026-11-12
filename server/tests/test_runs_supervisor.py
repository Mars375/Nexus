"""The supervisor: dispatches, publishes translated events, loses track on restart."""

from datetime import datetime

from runs_support import T1, T2, T3, FakeAdapter, dispatch, events_of, make_task, register, tick

from nexus.adapters.base import RunEvent
from nexus.models import Event, Run
from nexus.runs import supervisor


def run_row(client, run_id=1) -> Run:
    with client.app.state.sessionmaker() as session:
        return session.get(Run, run_id)


def test_a_dispatched_run_is_dispatched_then_watched_to_its_end(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)

    tick(client)

    assert adapter.dispatched == ["nx-run-1"]
    got = events_of(client, task)
    assert [(e["actor"], e["kind"], e["run"], e["origin"]) for e in got] == [
        ("codex", "claimed", "nx-run-1", "fake"),
        ("codex", "working", "nx-run-1", "fake"),
        ("codex", "done", "nx-run-1", "fake"),
    ]
    assert [e["actor_event_id"] for e in got] == ["nx-run-1-1", "nx-run-1-2", "nx-run-1-3"]
    assert [datetime.fromisoformat(e["at"]) for e in got] == [T1, T2, T3]
    row = run_row(client)
    assert (row.status, row.external_ref, row.native_status, row.watch_cursor) == (
        "done", "ext-1", "seen", "c1")
    assert row.ended_at is not None
    assert client.get(f"/api/tasks/{task}").json()["status"] == "done"


def test_replaying_the_same_events_adds_nothing(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    tick(client)
    first = events_of(client, task)

    # A watcher that re-reads its whole log: force the run back to a watched state.
    with client.app.state.sessionmaker() as session:
        session.get(Run, 1).status = "running"
        session.get(Run, 1).ended_at = None
        session.commit()
    tick(client)

    again = events_of(client, task)
    assert [e["id"] for e in again] == [e["id"] for e in first]
    assert [e["received_at"] for e in again] == [e["received_at"] for e in first]
    assert adapter.dispatched == ["nx-run-1"]  # never dispatched twice


def test_a_run_status_follows_the_last_event(client):
    script = [RunEvent(seq=1, at=T1, kind="working", subject="go")]
    register(client, adapter=FakeAdapter(script))
    dispatch(client, make_task(client))

    tick(client)

    assert run_row(client).status == "running"


def test_a_noise_refusal_does_not_stop_the_supervisor(client):
    script = [
        RunEvent(seq=1, at=T1, kind="progress", subject="même fait", body="50 %"),
        RunEvent(seq=2, at=T2, kind="progress", subject="même fait", body="50 %"),  # noise
        RunEvent(seq=3, at=T3, kind="working", subject="go"),
    ]
    register(client, adapter=FakeAdapter(script))
    task = make_task(client)
    dispatch(client, task)

    tick(client)

    assert [e["kind"] for e in events_of(client, task)] == ["progress", "working"]
    assert run_row(client).status == "running"


def test_a_failing_dispatch_fails_the_run_without_echoing_the_error(client):
    adapter = register(client)
    adapter.fail_dispatch = True
    task = make_task(client)
    dispatch(client, task)

    tick(client)

    assert run_row(client).status == "failed"
    [failed] = events_of(client, task)
    assert failed["kind"] == "failed" and "secret" not in str(failed)


def test_restart_puts_unfinished_runs_in_unknown_with_an_event(client):
    register(client)
    register(client, "orca")
    task = make_task(client)
    dispatch(client, task)
    other = make_task(client, title="Fini")
    dispatch(client, other, client_key="k2", executor="orca", agent="orca")
    with client.app.state.sessionmaker() as session:
        session.get(Run, 2).status = "done"
        session.commit()

    supervisor.mark_lost(client.app.state.sessionmaker)

    assert run_row(client, 1).status == "unknown" and run_row(client, 2).status == "done"
    [lost] = events_of(client, task)
    assert (lost["kind"], lost["run"], lost["actor"]) == ("unknown", "nx-run-1", "codex")
    assert "redémarrage" in lost["subject"]
    assert events_of(client, other) == []
    # Nothing is relaunched on its own.
    tick(client)
    assert run_row(client, 1).status == "unknown"


def test_the_lifespan_marks_lost_runs_at_startup(settings):
    from conftest import ActorClient, tailscale_json

    from nexus.app import create_app

    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as first:
        register(first)
        dispatch(first, make_task(first))
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as second:
        assert run_row(second).status == "unknown"
        with second.app.state.sessionmaker() as session:
            assert session.query(Event).filter_by(kind="unknown").count() == 1


def test_a_cancel_request_stops_the_executor_and_closes_the_run(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    client.post("/api/runs/nx-run-1/cancel")

    tick(client)

    # Never launched: cancelled on our side, the executor is not even called.
    assert adapter.cancelled == [] and adapter.watched == []
    assert run_row(client).status == "cancelled" and run_row(client).ended_at is not None
    [closer] = events_of(client, task)
    assert (closer["kind"], closer["run"]) == ("failed", "nx-run-1")
    # The event journal now lets the executor open another run.
    again = dispatch(client, task, client_key="k2")
    assert again.status_code == 201


def test_a_lost_run_can_be_cancelled_to_free_the_agent(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    supervisor.mark_lost(client.app.state.sessionmaker)

    assert client.post("/api/runs/nx-run-1/cancel").status_code == 200
    tick(client)

    assert adapter.cancelled == [] and run_row(client).status == "cancelled"


def test_a_run_whose_adapter_is_gone_is_left_alone(client):
    register(client)
    dispatch(client, make_task(client))
    client.app.state.adapters.unregister("codex")

    tick(client)

    assert run_row(client).status == "dispatched"



def test_a_cancel_posed_while_the_executor_is_watched_wins_over_its_end(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    adapter.on_watch = lambda: client.post("/api/runs/nx-run-1/cancel")

    tick(client)  # the executor says "done" after the human clicked cancel

    row = run_row(client)
    assert row.status != "done" and row.cancel_requested_at is not None
    adapter.on_watch = None
    tick(client)
    assert run_row(client).status == "cancelled"
    assert adapter.cancelled == ["nx-run-1"]


def test_a_cancel_posed_while_the_executor_is_dispatched_stops_it_at_once(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    adapter.on_dispatch = lambda: client.post("/api/runs/nx-run-1/cancel")

    tick(client)

    row = run_row(client)
    assert (row.status, row.external_ref) == ("cancelled", "ext-1")  # the reference is kept
    assert adapter.cancelled == ["nx-run-1"] and adapter.watched == []


def test_after_blocked_the_agent_is_free_for_a_new_run(client):
    script = [
        RunEvent(seq=1, at=T1, kind="working", subject="go"),
        RunEvent(seq=2, at=T2, kind="blocked", subject="bloqué", body="attente",
                 payload={"plan": "relancer"}),
    ]
    register(client, adapter=FakeAdapter(script))
    task = make_task(client)
    dispatch(client, task)
    tick(client)
    first = run_row(client)
    assert first.status == "blocked" and first.ended_at is not None

    again = dispatch(client, task, client_key="k2")

    assert again.status_code == 201
    tick(client)
    working = [e for e in events_of(client, task) if e["run"] == "nx-run-2"][0]
    assert working["kind"] == "working" and working["effects"][0]["applied"] is True


def test_a_lost_run_keeps_the_agent_until_it_is_cancelled(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    supervisor.mark_lost(client.app.state.sessionmaker)

    refused = dispatch(client, task, client_key="k2")
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "run_already_active")

    client.post("/api/runs/nx-run-1/cancel")
    tick(client)
    assert adapter.cancelled == []  # it was never launched
    assert dispatch(client, task, client_key="k2").status_code == 201
    tick(client)
    working = [e for e in events_of(client, task) if e["run"] == "nx-run-2"]
    assert [e["kind"] for e in working][:2] == ["claimed", "working"]
    assert working[1]["effects"][0]["applied"] is True
