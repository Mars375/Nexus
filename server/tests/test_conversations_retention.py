"""Purge rules of the conversation index (spec §6.6; plan PR 2 §5.7): gone sessions, disabled
sources, retention and `covered_since`, in batches. The clock is injected through `now`: rows to
purge are ingested under an earlier `now`, then purged under a later one."""

import threading
from datetime import datetime, timedelta

import pytest
from claude_sessions_support import NOW, conversation, migrated, raw_bytes, user, write_session
from conversations_support import recording, under
from sqlalchemy import event

from nexus.conversations import ingest, retention
from nexus.conversations.cursor_rules import Policy
from nexus.conversations.loop import Conversations
from nexus.tasks.api import TaskCreate
from nexus.tasks.service import create_task

EARLY = NOW - timedelta(days=20)


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


def conversations(db, **settings) -> Conversations:
    return Conversations(db.factory, db.with_settings(**settings))


def count(db, table="conversation_messages") -> int:
    return db.scalar(f"SELECT count(*) FROM {table}")


def integrity(db) -> None:
    with db.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO conversation_fts(conversation_fts) VALUES('integrity-check')")


def after_a_deletion(db, action):
    """`action` runs at every commit that leaves fewer messages than at the start: the purge
    moves `covered_since` first, in a commit that deletes nothing."""
    start = count(db)

    def after(_session):
        if count(db) < start:
            action()

    event.listen(db.factory, "after_commit", after)
    return after


def aged(root, days_old: list[int], *, body="message", session=None):
    """One session whose messages are `days_old` days older than NOW."""
    lines = [user(f"{body} {i}", at=NOW - timedelta(days=d, seconds=i),
                  line_id=f"00000000-0000-4000-8000-{i:012d}") for i, d in enumerate(days_old)]
    return write_session(root, lines, session=session, mtime=NOW - timedelta(days=1))


def test_a_session_missing_for_24_hours_is_deleted_with_its_fts_rows(db, root):
    write_session(root, [user("zqdisparu")])
    conv = conversations(db, conv_claude_root=root)
    conv.tick(NOW)
    with db.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE conversations SET missing_since = ?",
                             ((NOW - timedelta(hours=23)).isoformat(),))
    state = conv.state

    retention.purge(db.factory, now=NOW, retention_days=31, disabled=frozenset(),
                    state=state, stopping=threading.Event())
    assert count(db) == 1
    retention.purge(db.factory, now=NOW + timedelta(hours=2), retention_days=31,
                    disabled=frozenset(), state=state, stopping=threading.Event())

    assert count(db) == 0 and count(db, "conversations") == 0
    retention.rebuild(db.factory, state)
    assert not db.rows(
        "SELECT rowid FROM conversation_fts WHERE conversation_fts MATCH 'zqdisparu'")
    integrity(db)


def test_a_session_back_after_its_deletion_gets_a_new_handle(db, root):
    path = write_session(root, [user("retour")])
    conv = conversations(db, conv_claude_root=root)
    conv.tick(NOW)
    first = db.scalar("SELECT id FROM conversations")
    saved = path.read_bytes()
    path.unlink()
    for hours in (1, 2, 27):
        conv.state.last_purge_at = None
        conv.tick(NOW + timedelta(hours=hours))
    assert count(db, "conversations") == 0 and count(db, "conversation_cursors") == 0

    path.write_bytes(saved)
    conv.tick(NOW + timedelta(hours=28))

    assert db.scalar("SELECT id FROM conversations") > first and count(db) == 1


def test_a_disabled_source_is_emptied_and_read_again_once_enabled(db, root):
    write_session(root, conversation(4))
    conversations(db, conv_claude_root=root).tick(NOW)
    assert count(db) == 4

    off = conversations(db)
    off.tick(NOW)
    assert count(db) == 0 and count(db, "conversation_cursors") == 0
    assert count(db, "conversations") == 0

    conversations(db, conv_claude_root=root).tick(NOW)
    assert count(db) == 4


def test_a_set_but_refused_source_is_never_purged(db, root):
    write_session(root, conversation(4))
    conversations(db, conv_claude_root=root).tick(NOW)
    root.rename(root.with_name("projets"))

    conv = conversations(db, conv_claude_root=root)
    conv.tick(NOW)

    assert conv.state.status["claude-code"].state == "unavailable"
    assert count(db) == 4 and count(db, "conversation_cursors") == 1


def test_codex_settings_are_ignored_neither_read_nor_purged(db, tmp_path):
    codex = tmp_path / ".codex" / "sessions"
    (codex / "2026" / "11" / "27").mkdir(parents=True)
    with db.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO conversations (source, external_id, message_count, measured_at) "
            "VALUES ('codex', 's', 0, ?)", (NOW.isoformat(),))

    with recording() as events:
        conversations(db, conv_codex_root=codex).tick(NOW)

    assert not under(events, codex)
    assert count(db, "conversations") == 1


def test_messages_past_the_retention_are_deleted_and_counts_recomputed(db, root):
    aged(root, [40, 10, 40])
    aged(root, [40, 40])
    early = conversations(db, conv_claude_root=root)
    early.tick(EARLY)
    assert count(db) == 5

    conversations(db, conv_claude_root=root).tick(NOW)

    assert db.rows("SELECT message_count, started_at = last_message_at FROM conversations") == [
        (1, 1)]
    assert db.scalar("SELECT body FROM conversation_messages") == "message 1"
    integrity(db)


def test_a_purge_moves_covered_since_to_its_threshold(db, root):
    aged(root, [40, 10])
    conversations(db, conv_claude_root=root).tick(EARLY)
    assert db.scalar("SELECT covered_since FROM conversation_cursors") == (
        EARLY - timedelta(days=31)).isoformat()

    conversations(db, conv_claude_root=root).tick(NOW)

    assert db.scalar("SELECT covered_since FROM conversation_cursors") == (
        NOW - timedelta(days=31)).isoformat()


def test_a_retention_widened_during_a_partial_read_reads_from_zero(db, root):
    aged(root, [45, 45, 5, 4, 3, 2, 1])
    narrow = Policy.at(NOW, since_days=31, retention_days=31)
    ingest.claude_pass(db.factory, root, narrow, stopping=threading.Event(),
                       state=conversations(db).state, now=NOW, message_budget=2)
    assert db.scalar("SELECT state FROM conversation_cursors") == "partial"

    wide = Policy.at(NOW, since_days=31, retention_days=60)
    statuses = [ingest.claude_pass(db.factory, root, wide, stopping=threading.Event(),
                                   state=conversations(db).state, now=NOW, message_budget=3)
                for _ in range(4)]

    assert statuses[0].reads_from_zero == 1
    assert sum(s.reads_from_zero for s in statuses) == 1
    assert count(db) == 7 and db.scalar("SELECT state FROM conversation_cursors") == "ok"


def test_a_retention_widened_after_a_purge_brings_the_purged_messages_back(db, root):
    aged(root, [40, 10])
    conversations(db, conv_claude_root=root).tick(EARLY)
    conversations(db, conv_claude_root=root).tick(NOW)
    assert count(db) == 1

    conv = conversations(db, conv_claude_root=root, conv_retention_days=60)
    conv.tick(NOW)

    assert conv.state.status["claude-code"].reads_from_zero == 1 and count(db) == 2


def test_the_purge_goes_by_batches_and_lets_a_writer_in_between(db, root):
    aged(root, [40] * 1300 + [1])
    conversations(db, conv_claude_root=root).tick(EARLY)
    commits, writer, started = [], [], []

    def write_task():
        with db.factory() as session:
            body = TaskCreate(title="entre deux lots", objective="o").model_dump()
            create_task(session, body, "loic")
            session.commit()
        writer.append(count(db))  # messages left when the task committed

    @event.listens_for(db.factory, "after_commit")
    def after(_session):
        commits.append(count(db))
        if commits[-1] < 1301 and not started:  # after the first deletion batch
            started.append(1)
            thread = threading.Thread(target=write_task)
            thread.start()
            thread.join(5)

    result = retention.purge(db.factory, now=NOW, retention_days=31, disabled=frozenset(),
                             state=conversations(db).state, stopping=threading.Event())

    assert result.messages == 1300 and count(db) == 1
    # Three deletion batches (1 301 -> 801 -> 301 -> 1); the task got in after the first one.
    assert {801, 301, 1} <= set(commits)
    assert writer == [801]


def test_an_interrupted_purge_resumes_and_does_not_move_its_clock(db, root):
    aged(root, [40] * 600 + [1])
    conv = conversations(db, conv_claude_root=root)
    conv.tick(EARLY)
    conv.state.last_purge_at = None

    after = after_a_deletion(db, conv.stopping.set)

    result = retention.purge(db.factory, now=NOW, retention_days=31, disabled=frozenset(),
                             state=conv.state, stopping=conv.stopping)
    event.remove(db.factory, "after_commit", after)

    assert not result.complete and conv.state.last_purge_at is None and count(db) == 101
    conv.stopping.clear()
    conv.tick(NOW)
    assert conv.state.last_purge_at == NOW and count(db) == 1


def test_a_purge_stopped_after_its_last_batch_still_rebuilds_at_the_next_tick(db, root):
    markers = [f"zqpurge{i:05d}" for i in range(0, 200, 2)]
    lines = []
    for i in range(200):  # alternate: one line in two is purged
        old = i % 2 == 0
        lines.append(user(f"réunion {'zqpurge' if old else 'zqgarde'}{i:05d} fin",
                          at=NOW - timedelta(days=40 if old else 1, seconds=-i),
                          line_id=f"00000000-0000-4000-8000-{i:012d}"))
    write_session(root, lines, mtime=NOW - timedelta(days=1))
    conv = conversations(db, conv_claude_root=root)
    conv.tick(EARLY)
    conv.state.last_purge_at = None

    after = after_a_deletion(db, conv.stopping.set)

    conv.tick(NOW)
    event.remove(db.factory, "after_commit", after)
    assert count(db) == 100 and conv.state.rebuild_pending

    conv.stopping.clear()
    conv.tick(NOW + timedelta(minutes=1))

    data = raw_bytes(db.path)
    assert not [m for m in markers if m[-9:].encode() in data]
    assert not conv.state.rebuild_pending


def test_the_purge_runs_at_the_first_tick_then_every_24_hours(db):
    conv = conversations(db)
    conv.tick(NOW)
    assert conv.state.last_purge_at == NOW
    conv.tick(NOW + timedelta(hours=1))
    assert conv.state.last_purge_at == NOW
    conv.tick(NOW + timedelta(hours=24))
    assert conv.state.last_purge_at == NOW + timedelta(hours=24)


def test_without_source_and_with_an_empty_index_a_tick_writes_nothing(db):
    statements = []

    @event.listens_for(db.engine, "before_cursor_execute")
    def seen(_conn, _cursor, statement, *_args):
        statements.append(statement.split()[0].upper())

    conv = conversations(db)
    conv.tick(NOW)

    assert statements and set(statements) <= {"SELECT", "PRAGMA"}
    assert not conv.state.rebuild_pending and not conv.state.checkpoint_pending


def test_a_purge_that_emptied_the_index_and_stopped_rebuilds_after_a_restart(db, root):
    markers = [f"zqvide{i:05d}" for i in range(100)]
    lines = [user(f"réunion {m} fin", at=NOW - timedelta(days=40, seconds=-i),
                  line_id=f"00000000-0000-4000-8000-{i:012d}") for i, m in enumerate(markers)]
    write_session(root, lines, mtime=NOW - timedelta(days=1))
    first = conversations(db, conv_claude_root=root)
    first.tick(EARLY)
    first.state.last_purge_at = None

    after = after_a_deletion(db, first.stopping.set)

    first.tick(NOW)
    event.remove(db.factory, "after_commit", after)
    assert count(db) == 0 and first.state.rebuild_pending

    restarted = conversations(db)  # a new process: no state kept, no source read
    restarted.tick(NOW + timedelta(minutes=1))

    data = raw_bytes(db.path)
    assert not [m for m in markers if m[-9:].encode() in data]
    assert not restarted.state.rebuild_pending


def test_the_24_hours_between_two_purges_are_real_hours_across_a_dst_change():
    from zoneinfo import ZoneInfo

    from nexus.conversations.state import ProcessState
    paris = ZoneInfo("Europe/Paris")
    state = ProcessState()
    state.last_purge_at = datetime(2026, 10, 25, 0, 30, tzinfo=paris)  # 22:30Z the day before
    later = datetime(2026, 10, 25, 23, 45, tzinfo=paris)  # 22:45Z: 24 h 15 min have passed

    assert retention.purge_due(state, later)


def test_a_purge_stopped_after_its_first_deletion_has_moved_covered_since(db, root):
    aged(root, [40] * 600 + [1])
    conv = conversations(db, conv_claude_root=root)
    conv.tick(EARLY)
    conv.state.last_purge_at = None
    after = after_a_deletion(db, conv.stopping.set)
    result = retention.purge(db.factory, now=NOW, retention_days=31, disabled=frozenset(),
                             state=conv.state, stopping=conv.stopping)
    event.remove(db.factory, "after_commit", after)
    assert not result.complete and count(db) == 101

    # 45 days: past the 40-day messages, short of the 51 days the first pass covered.
    conversations(db, conv_claude_root=root, conv_retention_days=45).tick(NOW)

    assert count(db) == 601


def test_a_purge_leaves_codex_rows_alone_until_their_reader_lands(db):
    old = (NOW - timedelta(days=40)).isoformat()
    with db.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO conversations (source, external_id, message_count, missing_since, "
            "measured_at) VALUES ('codex', 's', 1, ?, ?)", (old, old))
        conn.exec_driver_sql(
            "INSERT INTO conversation_messages (conversation_id, external_id, role, author, at, "
            "body, truncated, redacted) VALUES (1, 'm', 'user', 'loic', ?, 'ancien', 0, 0)",
            (old,))
        conn.exec_driver_sql(
            "INSERT INTO conversation_cursors (source, path_key, byte_offset, covered_since, "
            "state, updated_at) VALUES ('codex', 'k', 0, ?, 'ok', ?)", (old, old))
    tables = ("conversations", "conversation_messages", "conversation_cursors")
    before = [db.rows(f"SELECT * FROM {table}") for table in tables]
    state = conversations(db).state
    state.listed["codex"] = frozenset()  # a listing that would name no Codex file

    result = retention.purge(db.factory, now=NOW, retention_days=31, disabled=frozenset(),
                             state=state, stopping=threading.Event())

    assert result.complete
    assert [db.rows(f"SELECT * FROM {table}") for table in tables] == before
