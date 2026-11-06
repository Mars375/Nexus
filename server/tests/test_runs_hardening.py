"""Review hardening of the runs (#167): admission, journal agreement, uncertain outcomes."""

from datetime import datetime

from events_support import AT, publish
from runs_support import (
    T1,
    T2,
    FakeAdapter,
    code_of,
    dispatch,
    events_of,
    make_task,
    register,
    tick,
)
from test_runs_races import race

from nexus.adapters.base import RunEvent
from nexus.models import Event, Run
from nexus.runs import supervisor


def row(client, run_id=1) -> Run:
    with client.app.state.sessionmaker() as session:
        return session.get(Run, run_id)


def as_codex(client, kind, task, **fields):
    publish.n = getattr(publish, "n", 0) + 1
    body = {"id": f"c{publish.n}", "at": AT, "actor": "codex", "kind": kind, "subject": "s",
            "task": task} | fields
    return client.post("/api/events", json=body)


# --- Admission: one active run per executor, whatever the task (ADR-023, D7) ----------------


def test_an_executor_runs_one_thing_at_a_time_across_tasks(client):
    register(client)
    dispatch(client, make_task(client))

    res = dispatch(client, make_task(client, title="Autre"), client_key="k2")

    assert (res.status_code, code_of(res)) == (409, "executor_busy")


def test_two_simultaneous_dispatches_on_two_tasks_leave_one_active_run(client):
    register(client)
    one, two = make_task(client), make_task(client, title="Autre")
    client.token_for("loic")

    results = race([
        lambda: dispatch(client, one, client_key="a"),
        lambda: dispatch(client, two, client_key="b"),
    ])

    assert sorted(r.status_code for r in results) == [201, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert code_of(loser) == "executor_busy"


def test_an_open_run_in_the_journal_refuses_the_dispatch(client):
    register(client)
    task = make_task(client)
    assert as_codex(client, "working", task, run="r1").status_code == 201

    res = dispatch(client, task)

    assert (res.status_code, code_of(res)) == (409, "run_already_active")


# --- Events: the reserved prefix is judged after the idempotent read-back -----------------


def test_a_historic_event_naming_a_run_is_still_replayed(client):
    task = make_task(client)
    body = {"id": "old", "at": AT, "actor": "codex", "kind": "progress", "subject": "s",
            "body": "x", "task": task, "run": "nx-run-7"}
    with client.app.state.sessionmaker() as session:
        session.add(Event(
            actor="codex", actor_event_id="old", at=datetime.fromisoformat(AT),
            received_at=datetime.fromisoformat(AT), task_id=1, run_ref="nx-run-7",
            kind="progress", subject="s", body="x", payload={}, evidence=[], needs=[],
            redacted=[], origin="api", effects=[]))
        session.commit()

    res = client.post("/api/events", json=body)

    assert res.status_code == 200


# --- Supervisor ---------------------------------------------------------------------------


def test_a_reference_the_scanner_would_mask_fails_the_run_and_stops_the_executor(client):
    adapter = register(client)
    adapter.external_ref = "ghp_" + "D" * 36
    dispatch(client, make_task(client))

    tick(client)

    assert row(client).status == "failed" and row(client).external_ref is None
    assert adapter.cancelled == ["nx-run-1"]


def test_the_launch_is_marked_before_the_executor_is_reached(client):
    adapter = register(client)
    seen = []
    adapter.on_dispatch = lambda: seen.append(row(client).native_status)
    dispatch(client, make_task(client))

    tick(client)

    assert seen == ["dispatching"]


def test_an_uncertain_launch_is_never_repeated(client):
    adapter = register(client)
    dispatch(client, make_task(client))
    with client.app.state.sessionmaker() as session:
        session.get(Run, 1).native_status = "dispatching"  # the process died after the marker
        session.commit()

    tick(client)

    assert adapter.dispatched == [] and row(client).status == "unknown"


def test_a_late_event_does_not_reopen_a_settled_run(client):
    script = [RunEvent(seq=1, at=T1, kind="done", subject="fini", evidence=["commit:abc"]),
              RunEvent(seq=2, at=T2, kind="working", subject="encore")]
    register(client, adapter=FakeAdapter(script))
    dispatch(client, make_task(client))

    tick(client)

    assert row(client).status == "done"


def test_a_closer_published_through_the_api_settles_the_run_before_any_launch(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    assert as_codex(client, "failed", task, run="nx-run-1", body="cause").status_code == 201

    tick(client)

    assert adapter.dispatched == [] and adapter.watched == []
    assert row(client).status == "failed" and row(client).ended_at is not None


def test_a_restart_keeps_the_end_already_recorded_in_the_journal(client):
    register(client)
    task = make_task(client)
    dispatch(client, task)
    done = as_codex(client, "done", task, run="nx-run-1", evidence=["commit:abc"])
    assert done.status_code == 201

    supervisor.mark_lost(client.app.state.sessionmaker)

    assert row(client).status == "done" and row(client).ended_at is not None
    assert [e["kind"] for e in events_of(client, task)] == ["done"]


def test_a_task_finished_before_the_launch_fails_the_run_without_the_adapter(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    client.post(f"/api/tasks/{task}/status", json={"status": "in_progress"})
    client.post(f"/api/tasks/{task}/status", json={"status": "done"})

    tick(client)

    assert adapter.dispatched == [] and row(client).status == "failed"


def test_a_cancel_the_executor_could_not_perform_keeps_the_run_open(client):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    client.post("/api/runs/nx-run-1/cancel")
    adapter.fail_cancel = True

    tick(client)

    assert row(client).status == "dispatched" and events_of(client, task) == []
    adapter.fail_cancel = False
    tick(client)
    assert row(client).status == "cancelled"


def test_a_cancel_of_a_run_never_launched_needs_no_adapter(client):
    register(client)
    dispatch(client, make_task(client))
    client.app.state.adapters.unregister("codex")
    client.post("/api/runs/nx-run-1/cancel")

    tick(client)

    assert row(client).status == "cancelled"


# --- Third review: cancel never overwritten, the journal wins, resends always replayed ------


def test_a_cancel_posed_before_the_launch_marker_stops_the_launch(client, monkeypatch):
    adapter = register(client)
    dispatch(client, make_task(client))
    real = supervisor._ready_code

    def cancelled_meanwhile(*args):
        client.post("/api/runs/nx-run-1/cancel")
        return real(*args)

    monkeypatch.setattr(supervisor, "_ready_code", cancelled_meanwhile)

    tick(client)

    assert adapter.dispatched == [] and row(client).cancel_requested_at is not None
    monkeypatch.setattr(supervisor, "_ready_code", real)
    tick(client)
    assert row(client).status == "cancelled"


def test_a_failed_launch_never_overwrites_a_concurrent_cancel(client):
    adapter = register(client)
    dispatch(client, make_task(client))
    adapter.fail_dispatch = True
    adapter.on_dispatch = lambda: client.post("/api/runs/nx-run-1/cancel")

    tick(client)

    first = row(client)
    assert first.status != "failed" and first.cancel_requested_at is not None
    adapter.on_dispatch = None
    tick(client)
    assert row(client).status == "cancelled"


def test_a_late_working_does_not_reopen_a_run_the_journal_already_closed(client):
    adapter = register(client, adapter=FakeAdapter(
        [RunEvent(seq=1, at=T1, kind="working", subject="encore")]))
    task = make_task(client)
    dispatch(client, task)
    adapter.on_watch = lambda: as_codex(client, "failed", task, run="nx-run-1", body="cause")

    tick(client)

    assert row(client).status == "failed"


def test_a_lost_run_with_a_cancel_already_in_the_journal_is_not_marked_unknown(client):
    register(client)
    task = make_task(client)
    dispatch(client, task)
    client.post("/api/runs/nx-run-1/cancel")
    closed = as_codex(
        client, "failed", task, run="nx-run-1", body="annulé", id="nx-run-1-cancelled")
    assert closed.status_code == 201

    supervisor.mark_lost(client.app.state.sessionmaker)

    assert row(client).status == "cancelled"
    assert [e["kind"] for e in events_of(client, task)] == ["failed"]


def test_a_resend_is_replayed_whatever_rule_the_winner_changed(client, monkeypatch):
    from nexus.runs import rules
    from nexus.tasks.rules import RuleViolation

    register(client)
    task = make_task(client)
    real = rules.check_dispatchable
    state = {"first": True}

    def winner_first(*args, **kwargs):
        if state["first"]:
            state["first"] = False
            assert dispatch(client, task).status_code == 201  # the click that won the race
            raise RuleViolation("executor_busy", "pris par le gagnant")
        return real(*args, **kwargs)

    monkeypatch.setattr(rules, "check_dispatchable", winner_first)

    res = dispatch(client, task)

    assert res.status_code == 200 and res.json()["id"] == "nx-run-1"


# --- Fourth review ------------------------------------------------------------------------


def test_a_closer_of_another_task_with_the_same_reference_does_not_settle_the_run(client):
    adapter = register(client)
    dispatch(client, make_task(client))
    other = make_task(client, title="Autre")  # nx-task-2, with a historic close naming nx-run-1
    with client.app.state.sessionmaker() as session:
        session.add(Event(
            actor="codex", actor_event_id="old-done", at=datetime.fromisoformat(AT),
            received_at=datetime.fromisoformat(AT), task_id=int(other.removeprefix("nx-task-")),
            run_ref="nx-run-1", kind="done", subject="s", body=None, payload={},
            evidence=["commit:abc"], needs=[], redacted=[], origin="api", effects=[]))
        session.commit()

    tick(client)

    assert adapter.dispatched == ["nx-run-1"]
    assert row(client).status == "done"  # settled by ITS script, not by the foreign close
    assert adapter.watched == ["nx-run-1"]


def test_a_workdir_with_a_secret_is_refused_without_echo(client):
    register(client)
    secret = "ghp_" + "E" * 36

    res = dispatch(client, make_task(client), workdir=f"F:/Projet/{secret}")

    assert (res.status_code, code_of(res)) == (409, "secret_in_workdir")
    assert secret not in res.text


def test_an_adapter_name_the_events_would_refuse_is_not_registered(client):
    import pytest

    class Named(FakeAdapter):
        name = "Bad Name"

    with pytest.raises(ValueError, match="nom"):
        client.app.state.adapters.register("codex", Named())
    assert client.app.state.adapters.executors() == []


def test_a_failing_mark_lost_still_releases_the_engines(settings, monkeypatch):
    import pytest
    from conftest import ActorClient, tailscale_json
    from sqlalchemy.engine import Engine

    from nexus.app import create_app

    disposed = []
    real = Engine.dispose

    def counting(self, *args, **kwargs):
        disposed.append(1)
        return real(self)

    monkeypatch.setattr(Engine, "dispose", counting)

    def boom(_factory):
        raise RuntimeError("mark_lost failed")

    monkeypatch.setattr(supervisor, "mark_lost", boom)

    with pytest.raises(RuntimeError, match="mark_lost failed"), ActorClient(
        create_app(settings, nodes_runner=tailscale_json)
    ):
        pass

    assert len(disposed) >= 2
