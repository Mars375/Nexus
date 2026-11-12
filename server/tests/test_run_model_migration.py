"""Migration 0009 (runs.model): populated 0008 database, matching the models, and down again."""

import sqlite3

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from nexus import migrate
from nexus.db import Base

TS = "2026-11-11T09:00:00+00:00"


def columns(path) -> dict[str, tuple]:
    with sqlite3.connect(path) as conn:
        return {r[1]: r for r in conn.execute("PRAGMA table_info(runs)")}


def test_0009_adds_a_nullable_model_and_drops_it_again(settings):
    settings.data_dir.mkdir(parents=True)
    cfg = migrate.alembic_config(settings.db_url)
    command.upgrade(cfg, "0008")
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO tasks (title, objective, status, human_owner, collaborators, evidence, "
        "priority, context, created_by, created_at, updated_at, version) VALUES "
        f"('Pont', 'Lire', 'todo', 'loic', '[]', '[]', 'normal', '[]', 'loic', '{TS}', '{TS}', 1)"
    )
    conn.execute(
        "INSERT INTO runs (task_id, executor, agent, dispatched_by, client_key, brief, status, "
        f"created_at, version) VALUES (1, 'codex', 'codex', 'loic', 'k', 'b', 'running', '{TS}', 1)"
    )
    conn.commit()
    conn.close()
    assert "model" not in columns(settings.db_path)

    command.upgrade(cfg, "0009")

    col = columns(settings.db_path)["model"]
    assert col[2].upper().startswith("VARCHAR") and col[3] == 0 and col[4] is None
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT status, model FROM runs").fetchall() == [("running", None)]
    engine = create_engine(settings.db_url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []

    command.downgrade(cfg, "0008")

    assert "model" not in columns(settings.db_path)
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT status FROM runs").fetchall() == [("running",)]
        indexes = {r[1] for r in conn.execute("PRAGMA index_list('runs')")}
    assert "uq_runs_one_active_per_executor" in indexes
