"""Sauvegarde de nexus.db — seule donnée non reconstructible (ARCHITECTURE §3.3).

L'index des conversations, lui, se reconstruit depuis les sources : chaque copie en est vidée
avant sa publication (ADR-025, D10), pour qu'aucune sauvegarde ne garde une conversation au-delà
de sa purge.
"""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path

from nexus.adapters.run_commit_scan import is_link
from nexus.clock import TZ

PREFIX = "nexus-"
SUFFIX = ".db"
PARTIAL = ".partial"
SIDECARS = ("-wal", "-shm", "-journal")
# Noms en UTC : ordre lexical = ordre chronologique, même au changement d'heure.
STAMP = "%Y%m%dT%H%M%S%fZ"
# A partial copy of `backup()` (and its journal files), by its whole name: nothing else is removed.
_PARTIAL_NAME = re.compile(
    re.escape(PREFIX) + r"[0-9]{8}T[0-9]{12}Z" + re.escape(SUFFIX + PARTIAL)
    + r"(-wal|-shm|-journal)?"
)

# Messages first: their delete trigger keeps the FTS in step. A table absent from an older copy
# (the lifespan backs up before migrating) is skipped. Never `delete-all` before the DELETE: the
# trigger would then send deletes for rows the index no longer has.
_STRIP_STATEMENTS = (
    ("conversation_messages", "DELETE FROM conversation_messages"),
    ("conversations", "DELETE FROM conversations"),
    ("conversation_cursors", "DELETE FROM conversation_cursors"),
    ("conversation_fts", "INSERT INTO conversation_fts(conversation_fts) VALUES('rebuild')"),
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def backup(db_path: Path, backup_dir: Path, keep: int) -> Path:
    """Copie cohérente (API de sauvegarde SQLite), vidée de l'index des conversations, publiée
    seulement si complète, puis rotation.

    La source est ouverte en lecture seule : une base absente fait échouer la sauvegarde
    au lieu d'en créer une vide. Un échec efface la copie partielle et ses fichiers voisins.
    """
    if not db_path.is_file():
        raise FileNotFoundError(f"base introuvable : {db_path}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{PREFIX}{_utcnow().strftime(STAMP)}{SUFFIX}"
    partial = target.with_name(target.name + PARTIAL)
    try:
        source = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            dest = sqlite3.connect(partial)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
        _strip_conversations(partial)
        os.replace(partial, target)
    except BaseException:
        _discard(partial)
        raise
    _prune(backup_dir, keep)
    return target


def _open_copy(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)  # no uri=True: a plain local file


def _strip_conversations(path: Path) -> None:
    """Empty the conversation index of the copy at `path` (spec §7.3); tolerate an older schema."""
    conn = _open_copy(path)
    try:
        # The copy inherits WAL from the source header; MEMORY leaves no -wal/-shm beside it.
        (mode,) = conn.execute("PRAGMA journal_mode=MEMORY").fetchone()
        if mode != "memory":
            raise RuntimeError("copie de sauvegarde : journal non basculé en mémoire")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA secure_delete=ON")
        present = {
            name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        statements = [(table, sql) for table, sql in _STRIP_STATEMENTS if table in present]
        if not statements:
            return  # older than 0010: nothing to strip
        for _table, sql in statements:
            conn.execute(sql)
        conn.commit()  # VACUUM refuses an open transaction
        conn.execute("VACUUM")
    finally:
        conn.close()  # before any unlink: Windows will not delete an open file


def _discard(partial: Path) -> None:
    for path in (partial, *(partial.with_name(partial.name + s) for s in SIDECARS)):
        path.unlink(missing_ok=True)


def remove_partials(backup_dir: Path) -> None:
    """Remove the partial copies a crash left in `backup_dir` (they may hold the index).

    Called at startup, before the first backup. Only regular files whose whole name is a partial
    copy's are removed; no subfolder is entered. A failure propagates: startup fails rather than
    leave a copy that keeps the index.
    """
    try:
        entries = os.scandir(backup_dir)
    except FileNotFoundError:
        return
    with entries:
        names = [entry.name for entry in entries]
    for name in names:
        if not _PARTIAL_NAME.fullmatch(name):
            continue
        path = backup_dir / name
        info = os.lstat(path)
        if stat.S_ISREG(info.st_mode) and not is_link(info):
            path.unlink()


def list_backups(backup_dir: Path) -> list[Path]:
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob(f"{PREFIX}*{SUFFIX}"))


def backup_time(path: Path) -> datetime:
    """Instant de la sauvegarde, exprimé en Europe/Paris pour l'affichage."""
    stamp = path.name.removeprefix(PREFIX).removesuffix(SUFFIX)
    return datetime.strptime(stamp, STAMP).replace(tzinfo=UTC).astimezone(TZ)


def _prune(backup_dir: Path, keep: int) -> None:
    for old in list_backups(backup_dir)[:-keep]:
        old.unlink()
