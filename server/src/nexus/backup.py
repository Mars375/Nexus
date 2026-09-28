"""Sauvegarde de nexus.db — seule donnée non reconstructible (ARCHITECTURE §3.3)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from nexus.clock import TZ, now

PREFIX = "nexus-"
SUFFIX = ".db"
STAMP = "%Y%m%d-%H%M%S-%f"


def backup(db_path: Path, backup_dir: Path, keep: int) -> Path:
    """Copie cohérente (API de sauvegarde SQLite) puis rotation des plus anciennes."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{PREFIX}{now().strftime(STAMP)}{SUFFIX}"
    source = sqlite3.connect(db_path)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    _prune(backup_dir, keep)
    return target


def list_backups(backup_dir: Path) -> list[Path]:
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob(f"{PREFIX}*{SUFFIX}"))


def backup_time(path: Path) -> datetime:
    stamp = path.name.removeprefix(PREFIX).removesuffix(SUFFIX)
    return datetime.strptime(stamp, STAMP).replace(tzinfo=TZ)


def _prune(backup_dir: Path, keep: int) -> None:
    for old in list_backups(backup_dir)[:-keep]:
        old.unlink()
