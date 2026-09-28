"""Sauvegarde de nexus.db — seule donnée non reconstructible (ARCHITECTURE §3.3)."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from nexus.clock import TZ

PREFIX = "nexus-"
SUFFIX = ".db"
PARTIAL = ".partial"
# Noms en UTC : ordre lexical = ordre chronologique, même au changement d'heure.
STAMP = "%Y%m%dT%H%M%S%fZ"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def backup(db_path: Path, backup_dir: Path, keep: int) -> Path:
    """Copie cohérente (API de sauvegarde SQLite), publiée seulement si complète, puis rotation.

    La source est ouverte en lecture seule : une base absente fait échouer la sauvegarde
    au lieu d'en créer une vide.
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
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    _prune(backup_dir, keep)
    return target


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
