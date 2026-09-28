import sqlite3

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
