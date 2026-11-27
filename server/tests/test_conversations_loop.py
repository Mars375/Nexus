"""The `conversations_loop` task (spec §6.1; plan PR 2 §5.8): idle by default, one pass at a
time, a clean stop before the engines are disposed, failures logged by class only."""

import asyncio
import logging
import threading
import time
from dataclasses import replace

import pytest
from claude_sessions_support import NOW, conversation, migrated, user, write_session
from conftest import ActorClient, tailscale_json
from conversations_support import recording, under

from nexus.app import create_app
from nexus.conversations import loop, store
from nexus.conversations.loop import Conversations


@pytest.fixture
def db(tmp_path):
    database = migrated(tmp_path)
    yield database
    database.engine.dispose()


@pytest.fixture
def root(tmp_path):
    path = tmp_path / ".claude" / "projects"
    path.mkdir(parents=True)
    return path


def test_without_a_root_a_tick_lists_and_opens_nothing(db, root, tmp_path, monkeypatch):
    home = tmp_path / "home"
    write_session(home / ".claude" / "projects", [user("jamais lu")])
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    write_session(root, [user("jamais lu non plus")])

    with recording() as events:
        Conversations(db.factory, db.settings).tick(NOW)

    assert not under(events, home) and not under(events, root.parent)
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 0


def test_with_a_root_a_tick_reads_the_sessions(db, root):
    write_session(root, conversation(3))

    conv = Conversations(db.factory, db.with_settings(conv_claude_root=root))
    conv.tick(NOW)

    assert db.scalar("SELECT count(*) FROM conversation_messages") == 3
    assert conv.state.status["claude-code"].state == "ok"


def test_the_lifespan_creates_the_loop_and_runs_no_pass_at_startup(settings, root):
    app = create_app(replace(settings, conv_claude_root=root), nodes_runner=tailscale_json)
    write_session(root, conversation(2))

    with ActorClient(app):
        conv = app.state.conversations
        assert isinstance(conv, Conversations) and conv.state.status == {}
        assert conv.state.last_purge_at is None
    assert conv.stopping.is_set()


def test_a_failing_tick_is_logged_by_its_class_and_the_loop_goes_on(monkeypatch, caplog):
    ticks = []

    class Failing:
        def tick(self):
            ticks.append(1)
            raise ValueError("C:\\Users\\x\\.claude\\projects\\secret.jsonl")

    sleeps = []

    async def fake_sleep(_seconds):
        sleeps.append(1)
        if len(sleeps) > 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(loop.asyncio, "sleep", fake_sleep)
    with caplog.at_level(logging.DEBUG, logger="nexus.conversations"), pytest.raises(
            asyncio.CancelledError):
        asyncio.run(loop.loop(Failing(), 60))

    assert len(ticks) == 3
    records = [r for r in caplog.records if r.name == "nexus.conversations"]
    assert records and all(r.exc_info is None for r in records)
    assert all("ValueError" in r.getMessage() and ".claude" not in r.getMessage()
               for r in records)


def blocking_batches(monkeypatch, gate: threading.Event, order: list):
    real = store.write_batch

    def blocked(*args, **kwargs):
        order.append("batch")
        gate.wait(10)
        time.sleep(0.1)
        result = real(*args, **kwargs)
        order.append("batch done")
        return result

    monkeypatch.setattr(store, "write_batch", blocked)


def test_stop_raises_the_flag_and_waits_for_the_pass(db, root, monkeypatch):
    for n in range(2):
        write_session(root, conversation(3), session=f"0000000{n}-0000-4000-8000-000000000000")
    conv = Conversations(db.factory, db.with_settings(conv_claude_root=root))
    order: list = []
    blocking_batches(monkeypatch, conv.stopping, order)
    thread = threading.Thread(target=conv.tick, args=(NOW,))
    thread.start()
    while not order:
        time.sleep(0.01)

    assert conv.stop(5) is True
    thread.join(5)

    assert order == ["batch", "batch done"]  # the second file was never read
    conv.tick(NOW)  # after stop: nothing
    assert order == ["batch", "batch done"]


def test_stop_gives_up_after_its_timeout(db, root, monkeypatch):
    write_session(root, conversation(3))
    conv = Conversations(db.factory, db.with_settings(conv_claude_root=root))
    release, order = threading.Event(), []
    blocking_batches(monkeypatch, release, order)
    thread = threading.Thread(target=conv.tick, args=(NOW,))
    thread.start()
    while not order:
        time.sleep(0.01)

    try:
        assert conv.stop(0.2) is False
    finally:
        release.set()
        thread.join(5)


def test_the_lifespan_disposes_the_engine_only_after_the_pass(settings, root, monkeypatch):
    write_session(root, conversation(3))
    app = create_app(replace(settings, conv_claude_root=root), nodes_runner=tailscale_json)
    order: list = []
    with ActorClient(app):
        conv = app.state.conversations
        blocking_batches(monkeypatch, conv.stopping, order)
        real_dispose = app.state.engine.dispose
        monkeypatch.setattr(app.state.engine, "dispose",
                            lambda: (order.append("dispose"), real_dispose())[1])
        thread = threading.Thread(target=conv.tick, args=(NOW,))
        thread.start()
        while not order:
            time.sleep(0.01)
    thread.join(5)

    assert order == ["batch", "batch done", "dispose"]


def test_two_ticks_from_two_threads_run_one_after_the_other(db, root, monkeypatch):
    write_session(root, conversation(6))
    conv = Conversations(db.factory, db.with_settings(conv_claude_root=root))
    inside, overlaps = [], []
    real = store.write_batch

    def watched(*args, **kwargs):
        inside.append(1)
        overlaps.append(len(inside))
        time.sleep(0.05)
        try:
            return real(*args, **kwargs)
        finally:
            inside.pop()

    monkeypatch.setattr(store, "write_batch", watched)
    threads = [threading.Thread(target=conv.tick, args=(NOW,)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert max(overlaps) == 1
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 6
    assert db.scalar("SELECT message_count FROM conversations") == 6


def test_an_api_write_goes_through_between_two_batches(settings, root, monkeypatch):
    write_session(root, conversation(1200))
    app = create_app(replace(settings, conv_claude_root=root), nodes_runner=tailscale_json)
    paused, resume, answered = threading.Event(), threading.Event(), []
    real = store.write_batch
    calls = []

    def pausing(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            paused.set()
            resume.wait(10)
        return real(*args, **kwargs)

    with ActorClient(app) as client:
        monkeypatch.setattr(store, "write_batch", pausing)
        thread = threading.Thread(target=app.state.conversations.tick, args=(NOW,))
        thread.start()
        assert paused.wait(10)
        started = time.perf_counter()
        res = client.post("/api/tasks", json={"title": "pendant la passe", "objective": "o"})
        answered.append((res.status_code, time.perf_counter() - started))
        resume.set()
        thread.join(10)

    assert answered[0][0] == 201 and answered[0][1] < 1.0
    status = app.state.conversations.state.status["claude-code"]
    assert status.messages_written == 1200 and status.state == "ok"
