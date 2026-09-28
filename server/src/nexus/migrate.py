"""Migrations Alembic appliquées au démarrage."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(db_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def pending(db_url: str) -> bool:
    """La base est-elle en retard sur la dernière migration ?"""
    heads = set(ScriptDirectory.from_config(alembic_config(db_url)).get_heads())
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            current = set(MigrationContext.configure(conn).get_current_heads())
    finally:
        engine.dispose()
    return current != heads


def upgrade(db_url: str) -> None:
    command.upgrade(alembic_config(db_url), "head")
