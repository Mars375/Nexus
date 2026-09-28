"""Configuration de Nexus, lue depuis l'environnement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Nexus"
    return Path.home() / ".nexus"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    backup_keep: int = 14
    backup_interval_hours: float = 24.0
    host: str = "127.0.0.1"
    port: int = 8765

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nexus.db"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(os.environ.get("NEXUS_DATA_DIR") or _default_data_dir()),
            backup_keep=int(os.environ.get("NEXUS_BACKUP_KEEP", "14")),
            backup_interval_hours=float(os.environ.get("NEXUS_BACKUP_INTERVAL_HOURS", "24")),
            host=os.environ.get("NEXUS_HOST", "127.0.0.1"),
            port=int(os.environ.get("NEXUS_PORT", "8765")),
        )
