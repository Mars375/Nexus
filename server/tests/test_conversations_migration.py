"""Migration 0010 (conversations, ADR-025): up from a populated 0009 database, the FTS5 index and
its triggers, the constraints the database holds itself, and down again."""

import sqlite3

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from migration_support import schema_diff
from sqlalchemy import event

from nexus import db as nexus_db
from nexus import migrate
from nexus.conversations import models

TS = "2026-11-11T09:00:00+00:00"
UUID = "0b6c7f1e-2a4d-4c3b-9e8f-1a2b3c4d5e6f"


def head(url: str) -> str:
    return ScriptDirectory.from_config(migrate.alembic_config(url)).get_current_head()


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def names(path, kind: str, pattern: str) -> set[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name LIKE ?", (kind, pattern)
        )
        return {name for (name,) in rows}


def counts(path) -> dict[str, int]:
    with sqlite3.connect(path) as conn:
        return {
            t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("tasks", "runs", "events")
        }


def version(path) -> str:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def add_conversation(conn, external_id="s1", source="claude-code") -> int:
    cur = conn.execute(
        "INSERT INTO conversations (source, external_id, message_count, measured_at) "
        "VALUES (?, ?, 0, ?)", (source, external_id, TS),
    )
    return cur.lastrowid


def add_message(conn, conversation_id, external_id="m1", body="bonjour", role="user") -> int:
    cur = conn.execute(
        "INSERT INTO conversation_messages (conversation_id, external_id, role, author, at, body, "
        "truncated, redacted) VALUES (?, ?, ?, 'loic', ?, ?, 0, 0)",
        (conversation_id, external_id, role, TS, body),
    )
    return cur.lastrowid


def add_cursor(conn, path_key="slug/a.jsonl", source="claude-code", state="ok", **extra):
    columns = {"source": source, "path_key": path_key, "state": state, "updated_at": TS} | extra
    conn.execute(
        f"INSERT INTO conversation_cursors ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})", tuple(columns.values()),
    )


def matches(conn, term: str) -> list[int]:
    rows = conn.execute("SELECT rowid FROM conversation_fts WHERE conversation_fts MATCH ?",
                        (term,))
    return [rowid for (rowid,) in rows]


def integrity(conn) -> None:
    conn.execute("INSERT INTO conversation_fts(conversation_fts) VALUES('integrity-check')")


@pytest.fixture
def at_0009(settings):
    settings.data_dir.mkdir(parents=True)
    command.upgrade(migrate.alembic_config(settings.db_url), "0009")
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO tasks (title, objective, status, human_owner, collaborators, evidence, "
        "priority, context, created_by, created_at, updated_at, version) VALUES "
        f"('Pont', 'Lire', 'todo', 'loic', '[]', '[]', 'normal', '[]', 'loic', '{TS}', '{TS}', 1)"
    )
    conn.execute(
        "INSERT INTO runs (task_id, executor, agent, dispatched_by, client_key, brief, status, "
        f"created_at, version) VALUES (1, 'codex', 'codex', 'loic', 'k', 'b', 'running', '{TS}', 1)"
    )
    conn.execute(
        "INSERT INTO events (actor, actor_event_id, at, received_at, task_id, kind, subject, "
        "payload, evidence, needs, redacted, origin, effects) VALUES "
        f"('codex', 'e1', '{TS}', '{TS}', 1, 'working', 'Lecture', '{{}}', '[]', '[]', '[]', "
        "'api', '[]')"
    )
    conn.commit()
    conn.close()
    return settings


@pytest.fixture
def at_head(at_0009):
    command.upgrade(migrate.alembic_config(at_0009.db_url), "head")
    return at_0009


def test_upgrading_a_populated_0009_database_keeps_every_row(at_0009):
    before = counts(at_0009.db_path)

    command.upgrade(migrate.alembic_config(at_0009.db_url), "head")

    assert counts(at_0009.db_path) == before == {"tasks": 1, "runs": 1, "events": 1}
    with sqlite3.connect(at_0009.db_path) as conn:
        for table in ("conversations", "conversation_messages", "conversation_cursors"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    assert version(at_0009.db_path) == head(at_0009.db_url) == "0010"


def test_the_migrated_schema_matches_the_models_once_fts_is_filtered(at_head):
    assert schema_diff(at_head.db_url) == []

    unfiltered = schema_diff(at_head.db_url, filtered=False)
    assert {op for op, _table in unfiltered} == {"remove_table"}
    assert sorted(table.name for _op, table in unfiltered) == sorted(models.FTS_TABLES)


def test_the_fts_tables_are_exactly_the_filtered_names(at_head):
    assert names(at_head.db_path, "table", "conversation_fts%") == models.FTS_TABLES
    assert len(models.FTS_TABLES) == 5


def test_the_fts_is_external_content_with_the_unicode61_tokenizer(at_head):
    with connect(at_head.db_path) as conn:
        (sql,) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'conversation_fts'"
        ).fetchone()
        message = add_message(conn, add_conversation(conn), body="Échéance réunion")

        assert matches(conn, "echeance") == [message]
    for clause in ("content='conversation_messages'", "content_rowid='id'",
                   "tokenize='unicode61 remove_diacritics 2'"):
        assert clause in sql


def test_the_triggers_keep_the_index_in_step(at_head):
    conn = connect(at_head.db_path)
    try:
        conversation = add_conversation(conn)
        first = add_message(conn, conversation, "m1", "alpha")
        assert matches(conn, "alpha") == [first]
        integrity(conn)

        conn.execute("UPDATE conversation_messages SET body = 'beta' WHERE id = ?", (first,))
        assert matches(conn, "alpha") == [] and matches(conn, "beta") == [first]
        integrity(conn)

        conn.execute("DELETE FROM conversation_messages WHERE id = ?", (first,))
        assert matches(conn, "beta") == []
        integrity(conn)

        second = add_message(conn, conversation, "m2", "gamma")
        assert matches(conn, "gamma") == [second]
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation,))  # cascade
        assert matches(conn, "gamma") == []
        assert conn.execute("SELECT count(*) FROM conversation_messages").fetchone() == (0,)
        integrity(conn)
    finally:
        conn.close()


def test_ids_are_never_reused_after_a_purge(at_head):
    with sqlite3.connect(at_head.db_path) as conn:
        for table in ("conversations", "conversation_messages"):
            (sql,) = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
            ).fetchone()
            assert "AUTOINCREMENT" in sql
    conn = connect(at_head.db_path)
    try:
        add_conversation(conn, "a")
        top = add_conversation(conn, "b")
        conn.execute("DELETE FROM conversations WHERE id = ?", (top,))
        conversation = add_conversation(conn, "c")
        assert (top, conversation) == (2, 3)

        add_message(conn, conversation, "m1")
        top = add_message(conn, conversation, "m2")
        conn.execute("DELETE FROM conversation_messages WHERE id = ?", (top,))
        assert (top, add_message(conn, conversation, "m3")) == (2, 3)
    finally:
        conn.close()


def test_the_database_enforces_the_closed_lists_and_keys(at_head):
    conn = connect(at_head.db_path)
    try:
        conversation = add_conversation(conn, "s1")
        add_message(conn, conversation, "m1")
        add_cursor(conn, "slug/a.jsonl")

        with pytest.raises(sqlite3.IntegrityError):
            add_conversation(conn, "s9", source="telegram")
        with pytest.raises(sqlite3.IntegrityError):
            add_message(conn, conversation, "m9", role="tool")
        with pytest.raises(sqlite3.IntegrityError):
            add_cursor(conn, "slug/b.jsonl", state="reading")
        with pytest.raises(sqlite3.IntegrityError):
            add_cursor(conn, "slug/c.jsonl", byte_offset=None)
        for body in ("", "a" * 16001, "a\x00" + "b" * 20000):
            with pytest.raises(sqlite3.IntegrityError):
                add_message(conn, conversation, "m-bad", body=body)
        with pytest.raises(sqlite3.IntegrityError):
            add_conversation(conn, "s1")
        with pytest.raises(sqlite3.IntegrityError):
            add_message(conn, conversation, "m1")
        with pytest.raises(sqlite3.IntegrityError):
            add_cursor(conn, "slug/a.jsonl")
        with pytest.raises(sqlite3.IntegrityError):
            add_message(conn, 999, "m-orphan")
        with pytest.raises(sqlite3.IntegrityError):
            add_conversation(conn, "")

        for n, body in enumerate(("a", "a" * 16000, "é" * 16000)):
            add_message(conn, conversation, f"ok{n}", body=body)
        add_conversation(conn, "s1", source="codex")
        for state in models.CURSOR_STATES:
            add_cursor(conn, f"slug/{state}.jsonl", state=state)
        add_cursor(conn, "slug/w.jsonl", window_from_id=4, session_external_id=None,
                   covered_since=TS)
        add_cursor(conn, "2026/11/03/r.jsonl.zst", source="codex", session_external_id=UUID)
        add_cursor(conn, "state.db", source="hermes", window_from_id=1, last_row_id=9,
                   covered_since=None)
        file_id = f"{2**63}:{2**64 - 1}"
        add_cursor(conn, "slug/id.jsonl", file_id=file_id)
        assert conn.execute(
            "SELECT file_id FROM conversation_cursors WHERE path_key = 'slug/id.jsonl'"
        ).fetchone() == (file_id,)
        assert set(models.CURSOR_STATES) >= {"skipping"} and len(models.CURSOR_STATES) == 6
        conn.commit()
    finally:
        conn.close()


def test_the_cursor_columns_have_the_spec_names(at_head):
    with sqlite3.connect(at_head.db_path) as conn:
        info = conn.execute("PRAGMA table_info(conversation_cursors)").fetchall()
    columns = [row[1] for row in info]
    by_name = {row[1]: row for row in info}

    assert columns == [
        "source", "path_key", "file_id", "size", "mtime_ns", "byte_offset", "head_sha256",
        "last_row_id", "window_from_id", "covered_since", "session_external_id", "state",
        "updated_at",
    ]
    assert "offset" not in columns
    assert by_name["file_id"][2].upper().startswith("VARCHAR")
    assert by_name["byte_offset"][3] == 1 and by_name["byte_offset"][4] == "'0'"
    assert by_name["covered_since"][3] == 0 and by_name["session_external_id"][3] == 0


def test_downgrade_removes_tables_fts_and_triggers_and_keeps_the_rest(at_head):
    before = counts(at_head.db_path)
    cfg = migrate.alembic_config(at_head.db_url)

    command.downgrade(cfg, "0009")

    assert names(at_head.db_path, "table", "conversation%") == set()
    assert names(at_head.db_path, "trigger", "conversation_messages_%") == set()
    assert names(at_head.db_path, "index", "ix_conversation%") == set()
    assert counts(at_head.db_path) == before
    assert version(at_head.db_path) == "0009"
    command.upgrade(cfg, "head")
    assert names(at_head.db_path, "table", "conversations") == {"conversations"}


def test_the_migration_fails_closed_without_fts5(at_0009, monkeypatch):
    real = nexus_db.make_engine

    def without_fts5(url, **kwargs):
        engine = real(url, **kwargs)

        @event.listens_for(engine, "before_cursor_execute", retval=True)
        def _rewrite(_conn, _cursor, statement, parameters, _context, _many):
            return statement.replace("USING fts5(", "USING nexus_absent_module("), parameters

        return engine

    monkeypatch.setattr(nexus_db, "make_engine", without_fts5)

    with pytest.raises(RuntimeError) as exc:
        command.upgrade(migrate.alembic_config(at_0009.db_url), "head")

    assert str(exc.value) == "SQLite sans FTS5"
    assert version(at_0009.db_path) == "0009"
    assert names(at_0009.db_path, "table", "conversation%") == set()


def test_an_empty_database_migrates_to_head(settings):
    settings.data_dir.mkdir(parents=True)

    migrate.upgrade(settings.db_url)

    assert names(settings.db_path, "table", "conversation%") == {
        "conversations", "conversation_messages", "conversation_cursors", *models.FTS_TABLES,
    }


def test_alembic_check_sees_no_drift_at_head(settings):
    settings.data_dir.mkdir(parents=True)
    migrate.upgrade(settings.db_url)

    command.check(migrate.alembic_config(settings.db_url))  # raises on any drift
