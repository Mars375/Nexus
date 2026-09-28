"""Modèle de données Nexus (DATA-MODEL.md)."""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db import Base


class AppMeta(Base):
    """Métadonnées de l'instance (date de création, etc.)."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
