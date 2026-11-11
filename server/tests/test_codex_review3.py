"""Third hardening of the Codex adapter (review of #170): crash recovery, text, shutdown."""

import json
import threading
from dataclasses import replace

import pytest
from codex_support import OK_LINES, THREAD, TURN, make_fake_codex, make_repo, run_info
from conftest import ActorClient, tailscale_json
from runs_support import dispatch, events_of, make_task, register, tick
from sqlalchemy.exc import OperationalError

from nexus.adapters.codex import CodexAdapter
from nexus.adapters.codex_translate import translate_line
from nexus.adapters.registry import AdapterRegistry
from nexus.app import create_app
from nexus.config import Settings
from nexus.models import Run
from nexus.runs import supervisor


def adapter_for(tmp_path, **scenario):
    binary = make_fake_codex(tmp_path / "fake", **scenario)
    repo = make_repo(tmp_path / "repo")
    return CodexAdapter(str(binary), [repo], tmp_path / "data"), repo, binary


# --- A1: an interrupted launch is a launch -----------------------------------------------------


def test_an_interrupted_launch_is_not_taken_for_a_run_never_launched(tmp_path):
    _, repo, binary = adapter_for(tmp_path, lines=[])
    reborn = CodexAdapter(str(binary), [repo], tmp_path / "data")
    interrupted = replace(run_info(5, external_ref=None), native_status="dispatching")

    with pytest.raises(RuntimeError):
        reborn.cancel(interrupted)


# --- A2 and CodeRabbit: text is cleaned before anything else -------------------------------------


def test_a_lone_surrogate_never_reaches_the_protocol():
    line = '{"type": "error", "message": "boom \\ud800 fin"}'

    fact = translate_line(line)

    assert fact.kind == "error"
    fact.body.encode("utf-8")  # encodable: publish() would refuse it otherwise


def test_a_secret_straddling_the_cut_is_masked_before_truncating():
    secret = "ghp_" + "A" * 36
    text = "x" * 489 + " " + secret + " et la suite"
    line = json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": text}})

    fact = translate_line(line)

    assert "ghp_" not in fact.body and "AAAA" not in fact.body


# --- A3, A4: bounded memory --------------------------------------------------------------------


def test_a_cancelled_job_is_closed_so_it_can_be_pruned(tmp_path):
    adapter, _, _ = adapter_for(tmp_path, lines=[THREAD, TURN], hang=True)
    adapter.keep_finished = 0
    adapter.dispatch(run_info(1))

    adapter.cancel(run_info(1, external_ref="x"))
    adapter.dispatch(run_info(2))

    assert "nx-run-1" not in adapter._jobs


def test_repeated_claimed_and_working_lines_are_kept_once(tmp_path):
    lines = [THREAD, TURN] * 500 + OK_LINES[-1:]
    adapter, _, _ = adapter_for(tmp_path, lines=lines, commit=True)
    adapter.dispatch(run_info(1))
    adapter.join("nx-run-1", 30)

    kinds = [e.kind for e in adapter.watch(run_info(1, external_ref="x")).events]

    assert kinds.count("claimed") == 1 and kinds.count("working") == 1


# --- CodeRabbit: shutdown ---------------------------------------------------------------------


def test_one_job_that_cannot_be_noted_does_not_stop_the_others_from_being_stopped(
    tmp_path, monkeypatch
):
    adapter, _, _ = adapter_for(tmp_path, lines=[THREAD, TURN], hang=True)
    adapter.dispatch(run_info(1))
    adapter.dispatch(run_info(2))

    def failing(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(type(adapter._stopped_marker("x")), "touch", failing)

    adapter.close()

    assert adapter.is_finished("nx-run-1") and adapter.is_finished("nx-run-2")


def test_a_failing_close_is_logged_by_the_registry(caplog):
    class Broken:
        name = "broken"

        def close(self):
            raise RuntimeError("secret detail")

    registry = AdapterRegistry()
    registry.register("codex", Broken())

    registry.close_all()

    assert any("RuntimeError" in r.getMessage() for r in caplog.records)
    assert not any("secret detail" in r.getMessage() for r in caplog.records)


def test_no_launch_happens_once_the_shutdown_has_begun(client):
    adapter = register(client)
    dispatch(client, make_task(client))

    client.app.state.adapters.close_all()
    tick(client)

    assert adapter.dispatched == []


def test_the_shutdown_waits_for_the_tick_in_progress(client):
    adapter = register(client)
    dispatch(client, make_task(client))
    inside, release = threading.Event(), threading.Event()

    def blocking():
        inside.set()
        release.wait(10)

    adapter.on_watch = blocking
    ticker = threading.Thread(target=tick, args=(client,))
    ticker.start()
    assert inside.wait(10)
    closed = threading.Event()

    def shut():
        client.app.state.adapters.close_all()
        closed.set()

    closer = threading.Thread(target=shut)
    closer.start()

    assert not closed.wait(0.3)  # the tick still runs: close_all waits for it
    release.set()
    ticker.join(10)
    closer.join(10)
    assert closed.is_set()


# --- CodeRabbit: a cancel asked during the launch wins over a lost reference ---------------------


def test_a_cancel_asked_during_dispatch_ends_cancelled_even_if_the_reference_is_lost(
    client, monkeypatch
):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    adapter.on_dispatch = lambda: client.post("/api/runs/nx-run-1/cancel")
    real = supervisor._finish

    def failing(factory, run, **changes):
        if changes.get("external_ref"):
            raise OperationalError("UPDATE", {}, Exception("disk I/O error"))
        return real(factory, run, **changes)

    monkeypatch.setattr(supervisor, "_finish", failing)

    tick(client)

    with client.app.state.sessionmaker() as session:
        assert session.get(Run, 1).status == "cancelled"
    assert events_of(client, task)[-1]["actor_event_id"] == "nx-run-1-cancelled"


def test_settings_and_app_are_unchanged_by_all_this(tmp_path):
    # Guard: the default app still has no adapter and starts normally.
    with ActorClient(create_app(Settings(data_dir=tmp_path), nodes_runner=tailscale_json)) as c:
        assert c.app.state.adapters.executors() == []
