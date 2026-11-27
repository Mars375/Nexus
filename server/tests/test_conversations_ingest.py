"""A Claude Code pass on a real migrated database (spec §6.1, §6.4; plan PR 2 §5.6): budget,
batches, idempotence and crashes. The sessions are invented, under `tmp_path`."""

import sqlite3
import threading
from datetime import timedelta

import pytest
from claude_sessions_support import (
    NOW,
    assistant,
    conversation,
    migrated,
    new_id,
    text,
    title,
    user,
    write_session,
)
from conversations_support import recording, under

from nexus.conversations import ingest, jsonl_tail, store
from nexus.conversations.cursor_rules import Policy
from nexus.conversations.state import ProcessState

POLICY = Policy.at(NOW, since_days=31, retention_days=31)


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


def run(db, root, *, policy=POLICY, state=None, now=NOW, stopping=None, **budgets):
    return ingest.claude_pass(db.factory, root, policy, stopping=stopping or threading.Event(),
                              state=state or ProcessState(), now=now, **budgets)


def dump(db) -> list:
    tables = ("conversations", "conversation_messages", "conversation_cursors")
    return [db.rows(f"SELECT * FROM {t} ORDER BY 1, 2") for t in tables]


def cursor(db) -> dict:
    conn = db.raw()
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM conversation_cursors")]
    finally:
        conn.close()


def test_a_session_of_ten_messages(db, root):
    lines = conversation(10)
    lines[3]["timestamp"] = "2026-11-27T11:00:03.250000Z"
    write_session(root, lines)

    status = run(db, root)

    assert status.state == "ok" and status.messages_written == 10
    (count, started, last, measured), = db.rows(
        "SELECT message_count, started_at, last_message_at, measured_at FROM conversations")
    assert count == 10 == db.scalar("SELECT count(*) FROM conversation_messages")
    assert started == "2026-11-27T11:00:00+00:00" and last == "2026-11-27T11:00:09+00:00"
    assert measured == NOW.isoformat()
    (state,), = db.rows("SELECT state FROM conversation_cursors")
    assert state == "ok"


def test_a_second_pass_without_change_opens_nothing_and_writes_nothing(db, root):
    path = write_session(root, conversation(4))
    run(db, root)
    before = dump(db)

    with recording() as events:
        status = run(db, root, now=NOW + timedelta(minutes=1))

    assert not [e for e in under(events, path) if e[0] == "open"]
    assert dump(db) == before and status.files_read == 0


def test_a_cursor_reset_by_hand_reads_again_without_duplicates(db, root):
    write_session(root, conversation(6))
    run(db, root)
    before = dump(db)[:2]
    with db.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE conversation_cursors SET byte_offset = 0, state = 'partial'")

    run(db, root)

    assert dump(db)[:2] == before


def test_a_crash_between_two_batches_leaves_no_duplicate_and_no_gap(db, root, monkeypatch):
    write_session(root, conversation(1200))
    real, calls = store.write_batch, []

    def crashing(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("plantage simulé")
        return real(*args, **kwargs)

    monkeypatch.setattr(store, "write_batch", crashing)
    with pytest.raises(RuntimeError):
        run(db, root, message_budget=5000)
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 500

    monkeypatch.setattr(store, "write_batch", real)
    run(db, root, message_budget=5000)

    ids = [r[0] for r in db.rows("SELECT external_id FROM conversation_messages ORDER BY 1")]
    assert ids == [f"00000000-0000-4000-8000-{i:012d}" for i in range(1200)]
    assert db.scalar("SELECT message_count FROM conversations") == 1200
    assert db.scalar("SELECT state FROM conversation_cursors") == "ok"


def test_a_crash_inside_a_batch_rolls_the_batch_back(db, root, monkeypatch):
    write_session(root, conversation(8))
    real = store._upsert_cursor

    def failing(*args, **kwargs):
        raise RuntimeError("après les messages, avant le curseur")

    monkeypatch.setattr(store, "_upsert_cursor", failing)
    with pytest.raises(RuntimeError):
        run(db, root)
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 0
    assert db.scalar("SELECT count(*) FROM conversations") == 0

    monkeypatch.setattr(store, "_upsert_cursor", real)
    run(db, root)
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 8


def test_a_message_budget_resumes_at_the_right_line_and_keeps_the_identity(db, root):
    write_session(root, conversation(12))
    state = ProcessState()
    seen, from_zero = [], 0

    for _ in range(3):
        status = run(db, root, state=state, message_budget=5)
        from_zero += status.reads_from_zero
        seen.append(db.scalar("SELECT count(*) FROM conversation_messages"))
        row = cursor(db)[0]
        assert all(row[k] is not None for k in (
            "covered_since", "size", "mtime_ns", "file_id", "head_sha256"))

    assert seen == [5, 10, 12]
    assert row["state"] == "ok" and from_zero == 1


def test_a_read_budget_takes_the_most_recent_files_first(db, root, monkeypatch):
    monkeypatch.setattr(jsonl_tail, "LINE_MAX", 16 << 10)
    big = "x" * 2000
    for age in (3, 1, 2):
        write_session(root, conversation(40, body=big), session=f"0000000{age}-0000-4000-8000"
                      f"-000000000000", mtime=NOW - timedelta(hours=age))

    first = run(db, root, read_budget=128 << 10)

    states = dict(db.rows("SELECT substr(path_key, -42, 8), state FROM conversation_cursors"))
    # The newest is read whole, the next one with what is left; the oldest waits.
    assert states == {"00000001": "ok", "00000002": "partial"}
    assert first.state == "partial" and first.bytes_read <= 128 << 10
    assert (128 << 10) - first.bytes_read < 16 << 10
    for _ in range(6):
        run(db, root, read_budget=128 << 10)
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 120
    assert {r[0] for r in db.rows("SELECT state FROM conversation_cursors")} == {"ok"}


def test_a_2_mib_line_across_the_budget_never_blocks_the_session(db, root):
    lines = conversation(4)
    huge = user("y" * (2 << 20))
    write_session(root, lines[:2] + [huge] + lines[2:])

    first = run(db, root, read_budget=(3 << 20) // 2)
    run(db, root, read_budget=(3 << 20) // 2)

    assert first.codes["oversized"] == 1
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 4
    assert db.scalar("SELECT state FROM conversation_cursors") == "ok"


def test_a_message_older_than_the_retention_is_never_written(db, root):
    old = user("vieux", at=NOW - timedelta(days=40))
    write_session(root, [old, user("récent")])

    status = run(db, root)

    assert [r[0] for r in db.rows("SELECT body FROM conversation_messages")] == ["récent"]
    assert status.codes["old"] == 1


def test_a_file_outside_the_window_is_never_opened_until_the_window_widens(db, root):
    path = write_session(root, [user("ancien", at=NOW - timedelta(days=50))],
                         mtime=NOW - timedelta(days=40))

    with recording() as events:
        run(db, root)

    assert not [e for e in under(events, path) if e[0] == "open"]
    assert db.scalar("SELECT state FROM conversation_cursors") == "skipped_old"
    wider = Policy.at(NOW, since_days=60, retention_days=60)
    status = run(db, root, policy=wider)
    assert status.reads_from_zero == 1
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 1


def test_a_session_of_tools_and_thinking_only_creates_no_conversation(db, root):
    write_session(root, [user([{"type": "tool_result", "content": "sortie"}]),
                         assistant([{"type": "thinking", "thinking": "hmm"}])])

    run(db, root)

    assert db.scalar("SELECT count(*) FROM conversations") == 0
    assert db.scalar("SELECT state FROM conversation_cursors") == "ok"


def test_the_same_session_name_under_two_folders_is_one_conversation(db, root):
    session = new_id()
    write_session(root, conversation(3), slug="a", session=session)
    write_session(root, conversation(5), slug="b", session=session)

    run(db, root)

    assert db.scalar("SELECT count(*) FROM conversations") == 1
    assert db.scalar("SELECT count(*) FROM conversation_cursors") == 2
    assert db.scalar("SELECT message_count FROM conversations") == 5


def test_degraded_needs_twenty_judged_lines(db, root):
    bad = [b"{pas du json"] * 16
    write_session(root, [user("présent")])
    gone = write_session(root, [user("disparu")])
    state = ProcessState()
    run(db, root, state=state)
    gone.unlink()
    write_session(root, [user(f"ok {i}") for i in range(14)] + bad)

    status = run(db, root, state=state, now=NOW + timedelta(minutes=1))
    run(db, root, state=state, now=NOW + timedelta(minutes=2))

    assert status.state == "degraded"
    assert db.scalar("SELECT count(*) FROM conversations WHERE missing_since IS NOT NULL") == 0
    few = migrated(root.parent.parent / "other")
    try:
        write_session(root.parent.parent / "p2", [user(f"ok {i}") for i in range(4)] + bad[:6])
        assert run(few, root.parent.parent / "p2").state != "degraded"
    finally:
        few.engine.dispose()


def test_a_writer_holding_the_lock_stops_the_pass_with_db_busy(tmp_path, root, monkeypatch):
    db = migrated(tmp_path, timeout=0.2)
    write_session(root, conversation(1000))
    real, held, release = store.write_batch, threading.Event(), threading.Event()

    def holder():
        conn = sqlite3.connect(db.path, timeout=5, isolation_level=None)
        conn.execute("BEGIN IMMEDIATE")
        held.set()
        release.wait(10)
        conn.execute("ROLLBACK")
        conn.close()

    calls = []

    def second_blocked(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            threading.Thread(target=holder, daemon=True).start()
            held.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(store, "write_batch", second_blocked)
    try:
        status = run(db, root, message_budget=5000)
        assert (status.state, status.code) == ("interrupted", "db_busy")
        assert db.scalar("SELECT count(*) FROM conversation_messages") == 500
        assert db.scalar("SELECT state FROM conversation_cursors") == "partial"
        release.set()
        monkeypatch.setattr(store, "write_batch", real)
        assert run(db, root, message_budget=5000).state == "ok"
        assert db.scalar("SELECT count(DISTINCT external_id) FROM conversation_messages") == 1000
        assert db.scalar("SELECT message_count FROM conversations") == 1000
    finally:
        release.set()
        db.engine.dispose()


def test_text_blocks_and_titles_reach_the_conversation(db, root):
    write_session(root, [{"type": "ai-title", "aiTitle": "Titre IA", "sessionId": None},
                         user([text("un"), text("deux")]),
                         {"type": "custom-title", "customTitle": "Mon titre", "sessionId": None},
                         {"type": "ai-title", "aiTitle": "Autre IA", "sessionId": None}])

    run(db, root)

    assert db.rows("SELECT title, workspace, git_branch FROM conversations") == [
        ("Mon titre", "F:\\Projet\\Ex", "master")]


def test_a_busy_database_while_loading_the_cursors_interrupts_only_the_pass(db, root,
                                                                            monkeypatch):
    from sqlalchemy.exc import OperationalError
    write_session(root, conversation(10))

    def locked(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, sqlite3.OperationalError("database is locked"))

    monkeypatch.setattr(store, "load_cursors", locked)

    status = run(db, root)

    assert (status.state, status.code) == ("interrupted", "db_busy")
    assert db.scalar("SELECT count(*) FROM conversation_messages") == 0


def test_a_stop_seen_at_the_line_check_of_the_last_file_interrupts_the_pass(db, root,
                                                                            monkeypatch):
    write_session(root, conversation(2 * ingest.STOP_CHECK_LINES))
    stopping, real_parse, marked = threading.Event(), ingest.parse_line, []

    def parse_then_stop(*args, **kwargs):
        stopping.set()
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(ingest, "parse_line", parse_then_stop)
    monkeypatch.setattr(store, "mark_old", lambda *a, **k: marked.append(1))

    status = run(db, root, stopping=stopping)

    assert (status.state, status.code) == ("interrupted", "stopping")
    assert marked == []
    assert db.scalar("SELECT state FROM conversation_cursors") == "partial"


def test_a_title_seen_before_any_message_reaches_the_conversation(db, root):
    session = new_id()
    write_session(root, [title("Réunion budget")], session=session, mtime=NOW)
    assert run(db, root).state == "ok"
    assert db.scalar("SELECT count(*) FROM conversations") == 0

    write_session(root, [title("Réunion budget"), user("premier message")], session=session,
                  mtime=NOW + timedelta(seconds=5))
    run(db, root, now=NOW + timedelta(seconds=10))

    assert db.scalar("SELECT title FROM conversations") == "Réunion budget"
    assert db.scalar("SELECT message_count FROM conversations") == 1


def _busy_mark_old(*_args, **_kwargs):
    from sqlalchemy.exc import OperationalError
    raise OperationalError("UPDATE", {}, sqlite3.OperationalError("database is locked"))


def test_an_interrupted_pass_with_many_bad_lines_stays_interrupted(db, root, monkeypatch):
    write_session(root, [user(f"ok {i}") for i in range(14)] + [b"{pas du json"] * 16)
    monkeypatch.setattr(store, "mark_old", _busy_mark_old)

    status = run(db, root)

    assert (status.state, status.code) == ("interrupted", "db_busy")


def test_a_pass_that_does_not_finish_forgets_the_files_listed_before(db, root, monkeypatch):
    write_session(root, [user("premier")])
    state = ProcessState()
    run(db, root, state=state)
    assert ingest.SOURCE in state.listed
    write_session(root, [user("second")])
    monkeypatch.setattr(store, "mark_old", _busy_mark_old)

    assert run(db, root, state=state, now=NOW + timedelta(minutes=1)).state == "interrupted"

    assert ingest.SOURCE not in state.listed  # no purge may judge presence on the old listing
