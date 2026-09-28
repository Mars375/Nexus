import sqlite3

import pytest

from nexus import backup


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()


def test_backup_is_a_readable_copy(tmp_path):
    db = tmp_path / "nexus.db"
    _make_db(db)

    target = backup.backup(db, tmp_path / "backups", keep=3)

    conn = sqlite3.connect(target)
    assert conn.execute("SELECT x FROM t").fetchone() == (42,)
    conn.close()


def test_backup_keeps_only_the_most_recent(tmp_path):
    db = tmp_path / "nexus.db"
    _make_db(db)
    backups_dir = tmp_path / "backups"

    made = [backup.backup(db, backups_dir, keep=3) for _ in range(5)]

    assert backup.list_backups(backups_dir) == made[-3:]


def test_missing_source_fails_without_creating_it_or_touching_backups(tmp_path):
    db = tmp_path / "nexus.db"
    _make_db(db)
    backups_dir = tmp_path / "backups"
    existing = [backup.backup(db, backups_dir, keep=2) for _ in range(2)]
    db.unlink()

    with pytest.raises(FileNotFoundError):
        backup.backup(db, backups_dir, keep=2)

    assert not db.exists()
    assert backup.list_backups(backups_dir) == existing


def test_failed_copy_is_not_published(tmp_path, monkeypatch):
    db = tmp_path / "nexus.db"
    _make_db(db)
    backups_dir = tmp_path / "backups"
    existing = backup.backup(db, backups_dir, keep=5)

    real_connect = sqlite3.connect

    class FailingSource:
        def __init__(self, conn):
            self._conn = conn

        def backup(self, _dest):
            raise sqlite3.OperationalError("disque plein")

        def close(self):
            self._conn.close()

    def connect(target, *args, **kwargs):
        conn = real_connect(target, *args, **kwargs)
        return FailingSource(conn) if kwargs.get("uri") else conn

    monkeypatch.setattr(backup.sqlite3, "connect", connect)

    with pytest.raises(sqlite3.OperationalError):
        backup.backup(db, backups_dir, keep=5)

    assert backup.list_backups(backups_dir) == [existing]
    assert not list(backups_dir.glob(f"*{backup.PARTIAL}"))
