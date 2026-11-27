"""What a purge leaves on disk (spec §6.6 as corrected by plan PR 2 §5.9): no purged byte in
`nexus.db` nor in its `-wal`, read as raw files. 4 000 invented messages, half of them purged,
in two layouts: alternating (one line in two) and random. Markers are 12 random letters, looked
for by their last 9 (FTS leaves compress the prefix shared with the neighbouring terms)."""

import random
import sqlite3
import string
import threading
import time
from datetime import timedelta

import pytest
from claude_sessions_support import NOW, migrated, raw_bytes, title, user, write_session
from conftest import ActorClient, tailscale_json
from sqlalchemy import text

from nexus.app import create_app
from nexus.conversations import retention
from nexus.conversations.loop import Conversations
from nexus.tasks.api import TaskCreate
from nexus.tasks.service import create_task

EARLY = NOW - timedelta(days=20)
SESSIONS, PER_SESSION = 20, 200


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


def word(rng: random.Random) -> str:
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(12))


def fill(root, layout: str) -> tuple[list[str], list[str]]:
    """4 000 messages; returns (purged markers, kept markers)."""
    rng = random.Random(204)
    purged, kept = [], []
    for s in range(SESSIONS):
        lines = []
        for i in range(PER_SESSION):
            old = i % 2 == 0 if layout == "alternating" else rng.random() < 0.5
            marker = word(rng)
            (purged if old else kept).append(marker)
            lines.append(user(f"réunion {marker} fin",
                              line_id=f"00000000-0000-4000-{s:04d}-{i:012d}",
                              at=NOW - timedelta(days=40 if old else 1, seconds=PER_SESSION - i)))
        write_session(root, lines, session=f"00000000-0000-4000-8000-{s:012d}",
                      mtime=NOW - timedelta(days=1))
    return purged, kept


def found(data: bytes, markers: list[str]) -> list[str]:
    return [m for m in markers if m[-9:].encode() in data]


def ingest_then_purge(db, root, layout):
    purged, kept = fill(root, layout)
    settings = db.with_settings(conv_claude_root=root)
    early = Conversations(db.factory, settings)
    for _ in range(3):  # 2 000 messages per pass
        early.tick(EARLY)
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 4000
    conv = Conversations(db.factory, settings)
    conv.tick(NOW)
    return conv, purged, kept


def test_secure_delete_is_on_for_every_connection_of_the_app(settings):
    app = create_app(settings, nodes_runner=tailscale_json)
    with ActorClient(app):
        for factory in (app.state.sessionmaker, app.state.touch_sessionmaker,
                        app.state.conversations.factory):
            with factory() as session:
                assert session.execute(text("PRAGMA secure_delete")).scalar() == 1


@pytest.mark.parametrize("layout", ["alternating", "random"])
def test_no_purged_marker_is_left_in_the_raw_bytes(db, root, layout):
    conv, purged, kept = ingest_then_purge(db, root, layout)

    data = raw_bytes(db.path)

    assert db.scalar("SELECT count(*) FROM conversation_messages") == len(kept)
    assert not found(data, purged)
    assert len(found(data, kept)) == len(kept)  # the search itself works
    assert not conv.state.checkpoint_pending
    assert db.path.with_name("nexus.db-wal").stat().st_size == 0
    with db.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO conversation_fts(conversation_fts) VALUES('integrity-check')")
    assert not db.rows("SELECT rowid FROM conversation_fts WHERE conversation_fts MATCH ?",
                       purged[0])


def test_a_blocked_checkpoint_is_short_and_retried_at_the_next_tick(db, root):
    write_session(root, [user(f"vieux {i}", at=NOW - timedelta(days=40, seconds=i))
                         for i in range(50)] + [user("récent")], mtime=NOW - timedelta(days=1))
    settings = db.with_settings(conv_claude_root=root)
    Conversations(db.factory, settings).tick(EARLY)
    reader = sqlite3.connect(db.path)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM conversation_messages").fetchone()
    conv = Conversations(db.factory, settings)

    started = time.perf_counter()
    conv.tick(NOW)
    took = time.perf_counter() - started

    assert conv.state.checkpoint_pending and took < 1.0
    reader.close()
    conv.tick(NOW + timedelta(minutes=1))
    assert not conv.state.checkpoint_pending
    assert db.path.with_name("nexus.db-wal").stat().st_size == 0


def test_a_writer_waits_little_during_a_blocked_checkpoint(db, root):
    with db.factory() as session:
        create_task(session, TaskCreate(title="t", objective="o").model_dump(), "loic")
        session.commit()
    reader = sqlite3.connect(db.path)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM tasks").fetchone()
    with db.factory() as session:  # a frame after the reader's snapshot
        create_task(session, TaskCreate(title="t2", objective="o").model_dump(), "loic")
        session.commit()
    waits = []

    def writer():
        time.sleep(0.05)
        started = time.perf_counter()
        with db.factory() as session:
            create_task(session, TaskCreate(title="t3", objective="o").model_dump(), "loic")
            session.commit()
        waits.append(time.perf_counter() - started)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        assert retention.checkpoint(db.path) is False
    finally:
        thread.join(5)
        reader.close()
    assert waits and waits[0] < 0.5


def test_titles_rewritten_by_every_batch_leave_nothing_once_purged(db, root):
    rng = random.Random(7)
    titles = [word(rng) for _ in range(4)]
    lines = []
    for n, value in enumerate(titles):
        lines.append(title(value))
        lines += [user(f"lot {n} message {i}", line_id=f"00000000-0000-4000-{n:04d}-{i:012d}")
                  for i in range(500)]
    write_session(root, lines)
    settings = db.with_settings(conv_claude_root=root)
    conv = Conversations(db.factory, settings)
    conv.tick(NOW)
    assert db.scalar("SELECT title FROM conversations") == titles[-1]

    Conversations(db.factory, db.with_settings()).tick(NOW)  # source switched off

    assert db.scalar("SELECT count(*) FROM conversations") == 0
    assert not found(raw_bytes(db.path), titles)
