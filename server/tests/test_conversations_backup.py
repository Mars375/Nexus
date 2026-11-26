"""Backups carry no conversation index (spec §7.3, ADR-025 D10): each copy is emptied of it before
it is published, a failure publishes nothing, and partial copies left by a crash are removed at
startup, before the first backup."""

import pathlib
import shutil
import sqlite3
import uuid

import pytest
from alembic import command
from conftest import ActorClient, tailscale_json

from nexus import backup, migrate
from nexus.app import create_app
from nexus.config import Settings

TS = "2026-11-11T09:00:00+00:00"
SIDECARS = ("-wal", "-shm", "-journal")
CONVERSATION_TABLES = ("conversations", "conversation_messages", "conversation_cursors")


def secret() -> str:
    return "ghp_" + "A" * 36


def fill(path) -> list[str]:
    """Two conversations, three messages and two cursors; returns the unique markers."""
    markers = ["zq" + uuid.uuid4().hex for _ in range(3)]
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    for n, source in enumerate(("claude-code", "codex"), start=1):
        conn.execute(
            "INSERT INTO conversations (source, external_id, title, message_count, measured_at) "
            "VALUES (?, ?, ?, 0, ?)", (source, f"s{n}", markers[0], TS),
        )
        conn.execute(
            "INSERT INTO conversation_cursors (source, path_key, state, updated_at) "
            "VALUES (?, ?, 'ok', ?)", (source, f"k/{markers[n]}.jsonl", TS),
        )
    for n, marker in enumerate(markers):
        conn.execute(
            "INSERT INTO conversation_messages (conversation_id, external_id, role, author, at, "
            "body, truncated, redacted) VALUES (?, ?, 'user', 'loic', ?, ?, 0, 0)",
            (1 + n % 2, f"m{n}", TS, f"{marker} réunion {secret()}"),
        )
    conn.commit()
    conn.close()
    return markers


@pytest.fixture
def at_head(settings):
    settings.data_dir.mkdir(parents=True)
    migrate.upgrade(settings.db_url)
    return settings, fill(settings.db_path)


def rows(path, table) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def leftovers(folder) -> list[str]:
    return sorted(p.name for p in folder.iterdir()
                  if p.name.endswith(SIDECARS) or backup.PARTIAL in p.name)


def test_a_backup_holds_no_conversation_index(at_head):
    settings, markers = at_head

    target = backup.backup(settings.db_path, settings.backup_dir, keep=3)

    for table in CONVERSATION_TABLES:
        assert rows(target, table) == 0
    with sqlite3.connect(target) as conn:
        found = conn.execute(
            "SELECT rowid FROM conversation_fts WHERE conversation_fts MATCH ?", (markers[0],)
        ).fetchall()
        conn.execute("INSERT INTO conversation_fts(conversation_fts) VALUES('integrity-check')")
    assert found == []
    raw = target.read_bytes()
    assert not [m for m in (*markers, secret()) if m.encode() in raw]
    assert rows(settings.db_path, "conversation_messages") == 3  # the source keeps its rows


def test_no_sidecar_file_is_left_next_to_a_backup(at_head):
    settings, _markers = at_head

    target = backup.backup(settings.db_path, settings.backup_dir, keep=3)

    assert leftovers(settings.backup_dir) == []
    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone() == ("delete",)


def test_a_backup_of_a_0009_database_needs_no_strip(settings):
    settings.data_dir.mkdir(parents=True)
    command.upgrade(migrate.alembic_config(settings.db_url), "0009")
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("CREATE TABLE notes (x TEXT)")
        conn.execute("INSERT INTO notes VALUES ('gardé')")
        tables = {n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    target = backup.backup(settings.db_path, settings.backup_dir, keep=3)

    with sqlite3.connect(target) as conn:
        copied = {n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert conn.execute("SELECT x FROM notes").fetchall() == [("gardé",)]
    assert copied == tables
    assert leftovers(settings.backup_dir) == []


def test_the_pre_migration_copy_of_a_0009_database_succeeds(settings):
    settings.data_dir.mkdir(parents=True)
    command.upgrade(migrate.alembic_config(settings.db_url), "0009")

    with ActorClient(create_app(settings, nodes_runner=tailscale_json)):
        pass

    (copy,) = backup.list_backups(settings.backup_dir)
    with sqlite3.connect(copy) as conn:
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name LIKE 'conversation%'"
        ).fetchone() == (0,)
    assert leftovers(settings.backup_dir) == []
    assert not migrate.pending(settings.db_url)


def test_a_failed_strip_publishes_nothing(at_head, monkeypatch):
    settings, _markers = at_head
    existing = backup.backup(settings.db_path, settings.backup_dir, keep=5)
    monkeypatch.setattr(backup, "_STRIP_STATEMENTS", (
        *backup._STRIP_STATEMENTS, ("conversations", "DELETE FROM nexus_absent_table"),
    ))

    with pytest.raises(sqlite3.OperationalError):
        backup.backup(settings.db_path, settings.backup_dir, keep=5)

    assert backup.list_backups(settings.backup_dir) == [existing]
    assert leftovers(settings.backup_dir) == []


def test_a_restored_backup_starts_with_an_empty_index(at_head, tmp_path):
    settings, _markers = at_head
    target = backup.backup(settings.db_path, settings.backup_dir, keep=3)
    restored = Settings(data_dir=tmp_path / "restauré")
    restored.data_dir.mkdir()
    shutil.copyfile(target, restored.db_path)
    assert not migrate.pending(restored.db_url)

    with ActorClient(create_app(restored, nodes_runner=tailscale_json)):
        pass

    for table in CONVERSATION_TABLES:
        assert rows(restored.db_path, table) == 0
    with sqlite3.connect(restored.db_path) as conn:
        conn.execute("INSERT INTO conversation_fts(conversation_fts) VALUES('integrity-check')")
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        others = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'conversation%' AND name NOT LIKE 'sqlite_%'")]
    assert "alembic_version" in others
    for table in others:  # the strip leaves every other table as it was
        assert rows(restored.db_path, table) == rows(settings.db_path, table), table


class Recording(sqlite3.Connection):
    log: list[str] = []

    def execute(self, sql, *args):
        Recording.log.append(sql)
        return super().execute(sql, *args)

    def commit(self):
        Recording.log.append("commit")
        super().commit()

    def close(self):
        Recording.log.append("close")
        super().close()


def test_the_strip_commits_before_vacuum_and_closes_before_unlink(at_head, monkeypatch):
    settings, _markers = at_head
    Recording.log = []
    monkeypatch.setattr(backup, "_open_copy", lambda p: sqlite3.connect(p, factory=Recording))

    backup.backup(settings.db_path, settings.backup_dir, keep=3)

    log = Recording.log
    first_delete = next(i for i, s in enumerate(log) if s.startswith("DELETE"))
    assert log.index("PRAGMA journal_mode=MEMORY") < first_delete
    assert log.index("commit") < log.index("VACUUM")
    assert log[-1] == "close"

    Recording.log = []
    unlinked = []
    real_unlink = pathlib.Path.unlink

    def spy(self, *args, **kwargs):
        if self.name.endswith(backup.PARTIAL):
            unlinked.append(len(Recording.log))
            Recording.log.append(f"unlink {self.suffix}")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", spy)
    monkeypatch.setattr(backup, "_STRIP_STATEMENTS", (
        *backup._STRIP_STATEMENTS, ("conversations", "DELETE FROM nexus_absent_table"),
    ))
    with pytest.raises(sqlite3.OperationalError):
        backup.backup(settings.db_path, settings.backup_dir, keep=3)

    assert unlinked and Recording.log.index("close") < unlinked[0]


STAMPED = "nexus-20261101T000000000000Z.db"


def test_startup_removes_leftover_partials(settings, monkeypatch):
    settings.backup_dir.mkdir(parents=True)
    marker = "zq" + uuid.uuid4().hex
    partial = settings.backup_dir / f"{STAMPED}{backup.PARTIAL}"
    seeded = [partial, *(partial.with_name(partial.name + s) for s in SIDECARS)]
    for path in seeded:
        path.write_text(marker, encoding="utf-8")
    real_backup = settings.backup_dir / "nexus-20261031T000000000000Z.db"
    real_backup.write_bytes(b"")
    kept = [settings.backup_dir / "notes.partial", settings.backup_dir / "nexus-x.db.partial"]
    for path in kept:
        path.write_text(marker, encoding="utf-8")
    seen_at_first_backup = []
    original = backup.backup

    def checked(*args, **kwargs):
        if not seen_at_first_backup:
            seen_at_first_backup.append([p for p in seeded if p.exists()])
        return original(*args, **kwargs)

    monkeypatch.setattr(backup, "backup", checked)

    with ActorClient(create_app(settings, nodes_runner=tailscale_json)):
        pass

    assert seen_at_first_backup == [[]]
    assert not [p for p in seeded if p.exists()]
    assert real_backup.exists() and all(p.exists() for p in kept)


def test_remove_partials_is_a_no_op_without_a_backup_dir(tmp_path):
    absent = tmp_path / "absent"

    backup.remove_partials(absent)

    assert not absent.exists()
