"""Hermes through the run supervisor, `publish` and the API (spec §8, tests 36-41)."""

from datetime import UTC, datetime

import pytest
from conftest import ActorClient, tailscale_json
from hermes_support import (
    T0,
    TASK_ID,
    assignees,
    attachment,
    calls,
    created,
    event,
    make_fake_hermes,
    reply,
    run_row,
    show_payload,
    subcommands,
)
from runs_support import code_of, dispatch, events_of, make_task, tick
from sqlalchemy.exc import OperationalError

from nexus.app import create_app
from nexus.config import Settings
from nexus.runs import supervisor

TERMINATED = event("archive_worker_termination", T0 + 9, {"terminated": True, "prev_pid": 5})


def start(tmp_path, **scenario):
    binary = make_fake_hermes(
        tmp_path / "fake", **({"assignees": [reply(assignees())],
                               "create": [reply(created())]} | scenario))
    settings = Settings(data_dir=tmp_path / "data", hermes_bin=str(binary), run_max_minutes=10)
    app = create_app(settings, nodes_runner=tailscale_json)
    adapter = app.state.adapters.get("hermes")
    adapter.watch_seconds = 0.0
    adapter.clock = lambda: datetime.fromtimestamp(T0 + 60, UTC)
    return app, binary


def hand_over(client, **fields):
    task = make_task(client)
    res = dispatch(client, task, executor="hermes", agent="helios", **fields)
    assert res.status_code == 201, res.text
    return task


def finished(tmp_path):
    f = tmp_path / "rapport.md"
    f.write_text("cinq lignes", encoding="utf-8")
    story = [event("created"), event("claimed", T0 + 1), event("spawned", T0 + 2, run_id=1),
             event("completed", T0 + 5, {"summary": "ok"}, 1)]
    return (reply(show_payload("done", events=story, runs=[run_row(1, "completed", "ok")])),
            reply([attachment(f, f.stat().st_size)]))


def test_a_whole_run_is_published_through_the_protocol(tmp_path):
    show, files = finished(tmp_path)
    app, binary = start(tmp_path, show=[show], attachments=[files])
    with ActorClient(app) as client:
        task = hand_over(client)

        tick(client)

        run = client.get("/api/runs/nx-run-1").json()
        assert run["status"] == "done" and run["external_ref"] == TASK_ID
        got = events_of(client, task)
        assert [e["kind"] for e in got] == ["claimed", "working", "done"]
        assert {e["origin"] for e in got} == {"hermes"} and {e["actor"] for e in got} == {"hermes"}
        assert [e["actor_event_id"] for e in got] == ["nx-run-1-2", "nx-run-1-3", "nx-run-1-4"]
        assert client.get(f"/api/tasks/{task}").json()["status"] == "done"
        before = len(calls(binary))

        tick(client)  # a settled run is not read again
        assert len(calls(binary)) == before and len(events_of(client, task)) == 3


CLOSES = {
    "review": ([event("spawned", T0 + 2), event("completed", T0 + 5, None, 1)],
               "done", "review"),
    "blocked": ([event("spawned", T0 + 2), event("blocked", T0 + 5, {"reason": "clé ?"})],
                "blocked", "blocked"),
    "failed": ([event("spawn_failed", T0 + 2, {"error": "boum"}), event("gave_up", T0 + 3)],
                "blocked", "failed"),
}


@pytest.mark.parametrize("name", CLOSES)
def test_each_close_is_accepted_by_publish(tmp_path, name):
    events, status, expected = CLOSES[name]
    first = show_payload(status, events=events, runs=[run_row(1, "completed", "résumé")])
    archived = show_payload("archived", events=[*events, TERMINATED])
    app, _ = start(tmp_path, show=[reply(first), reply(archived)], archive=[reply("")],
                   attachments=[reply([])])
    with ActorClient(app) as client:
        hand_over(client)
        tick(client)
        assert client.get("/api/runs/nx-run-1").json()["status"] == expected


def test_the_maximum_duration_and_a_vanished_task_close_the_run(tmp_path):
    old = show_payload("ready")
    archived = show_payload("archived", events=[TERMINATED])
    app, _ = start(tmp_path, show=[reply(old), reply(archived)], archive=[reply("")])
    with ActorClient(app) as client:
        hand_over(client)
        client.app.state.adapters.get("hermes").clock = lambda: datetime.fromtimestamp(
            T0 + 10_000, UTC)
        tick(client)
        assert client.get("/api/runs/nx-run-1").json()["status"] == "failed"

    gone = reply(exit=1, stderr=f"no such task {TASK_ID}")
    app, _ = start(tmp_path / "b", show=[gone])
    with ActorClient(app) as client:
        hand_over(client)
        tick(client)
        assert client.get("/api/runs/nx-run-1").json()["status"] == "failed"


def test_an_uncertain_launch_holds_the_run_until_it_is_cancelled(tmp_path):
    app, binary = start(tmp_path, create=[reply("illisible")], list=[reply([])])
    with ActorClient(app) as client:
        task = hand_over(client)

        tick(client)

        run = client.get("/api/runs/nx-run-1").json()
        assert run["status"] == "unknown" and run["native_status"] == "dispatching"
        got = events_of(client, task)
        assert got[-1]["kind"] == "unknown" and got[-1]["subject"] == "lancement incertain"
        assert subcommands(binary).count("create") == 2

        tick(client)  # never repeated
        assert subcommands(binary).count("create") == 2

        assert client.post("/api/runs/nx-run-1/cancel").status_code == 200
        tick(client)
        assert client.get("/api/runs/nx-run-1").json()["status"] == "cancelled"
        assert "list" in subcommands(binary)


def test_a_reference_that_cannot_be_written_is_used_to_archive(tmp_path, monkeypatch):
    archived = show_payload("archived", events=[TERMINATED])
    app, binary = start(tmp_path, show=[reply(archived)], archive=[reply("")])
    real = supervisor._finish

    def failing(factory, run, **changes):
        if changes.get("external_ref"):
            raise OperationalError("UPDATE", {}, Exception("disk I/O error"))
        return real(factory, run, **changes)

    with ActorClient(app) as client:
        hand_over(client)
        monkeypatch.setattr(supervisor, "_finish", failing)
        tick(client)
        assert [c["argv"][-1] for c in calls(binary) if c["argv"][3] == "archive"] == [TASK_ID]


def test_a_restart_makes_the_run_unknown_and_the_cancel_archives(tmp_path):
    running = show_payload("running", events=[event("claimed", T0 + 1), event("spawned", T0 + 2)])
    archived = show_payload("archived", events=[TERMINATED])
    app, binary = start(tmp_path, show=[reply(running), reply(archived)], archive=[reply("")])
    with ActorClient(app) as client:
        hand_over(client)
        tick(client)
        assert client.get("/api/runs/nx-run-1").json()["status"] == "running"

        supervisor.mark_lost(client.app.state.sessionmaker)
        assert client.get("/api/runs/nx-run-1").json()["status"] == "unknown"

        client.post("/api/runs/nx-run-1/cancel")
        tick(client)
        assert client.get("/api/runs/nx-run-1").json()["status"] == "cancelled"
        assert "archive" in subcommands(binary)


def test_a_second_run_while_one_is_active_is_busy(tmp_path):
    running = show_payload("running", events=[event("claimed", T0 + 1)])
    app, _ = start(tmp_path, show=[reply(running)])
    with ActorClient(app) as client:
        hand_over(client)
        tick(client)
        other = make_task(client, title="Autre")
        res = dispatch(client, other, executor="hermes", agent="helios", client_key="k2")
        assert (res.status_code, code_of(res)) == (409, "executor_busy")
