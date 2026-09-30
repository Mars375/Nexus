"""Configuration de Nexus, lue depuis l'environnement."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Nexus"
    return Path.home() / ".nexus"


_ORIGIN = re.compile(r"[a-z][a-z0-9+.-]*://(\[[0-9a-f:.]+\]|[a-z0-9._-]+)(:[0-9]{1,5})?")


def _is_plain_origin(origin: str) -> bool:
    """Une origine sûre : schéma://hôte[:port] exactement (jamais `null`, chemin, identifiants)."""
    return _ORIGIN.fullmatch(origin) is not None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    backup_keep: int = 14
    backup_interval_hours: float = 24.0
    host: str = "127.0.0.1"
    port: int = 8765
    tailscale_bin: str = "tailscale"
    nodes_refresh_seconds: float = 60.0
    # Origines admises en plus de la boucle locale pour le WebSocket (ex. Tauri plus tard).
    allowed_origins: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.backup_keep < 1:
            raise ValueError(f"NEXUS_BACKUP_KEEP doit être ≥ 1 (reçu : {self.backup_keep})")
        if not (math.isfinite(self.backup_interval_hours) and self.backup_interval_hours > 0):
            raise ValueError(
                "NEXUS_BACKUP_INTERVAL_HOURS doit être un nombre fini > 0 "
                f"(reçu : {self.backup_interval_hours})"
            )
        if not 1 <= self.port <= 65535:
            raise ValueError(f"NEXUS_PORT doit être entre 1 et 65535 (reçu : {self.port})")
        if not (math.isfinite(self.nodes_refresh_seconds) and self.nodes_refresh_seconds > 0):
            raise ValueError(
                "NEXUS_NODES_REFRESH_SECONDS doit être un nombre fini > 0 "
                f"(reçu : {self.nodes_refresh_seconds})"
            )

        for origin in self.allowed_origins:
            if not _is_plain_origin(origin):
                # Jamais la valeur reçue dans le message (ADR-006).
                raise ValueError(
                    "NEXUS_ALLOWED_ORIGINS : chaque origine doit avoir la forme "
                    "schéma://hôte[:port], sans chemin, sans identifiants et sans requête"
                )

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
            tailscale_bin=os.environ.get("NEXUS_TAILSCALE_BIN", "tailscale"),
            nodes_refresh_seconds=float(os.environ.get("NEXUS_NODES_REFRESH_SECONDS", "60")),
            allowed_origins=frozenset(
                item.strip()
                for item in os.environ.get("NEXUS_ALLOWED_ORIGINS", "").split(",")
                if item.strip()
            ),
        )
