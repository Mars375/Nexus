"""Migration 0008 (runs): up on a populated 0007 database, matching the models, and down again."""

import sqlite3

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from nexus import migrate
from nexus.db import Base


def tables(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_0008_creates_runs_matching_the_models_and_drops_it_again(settings):
    settings.data_dir.mkdir(parents=True)
    cfg = migrate.alembic_config(settings.db_url)
    command.upgrade(cfg, "0007")
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO tasks (title, objective, status, human_owner, collaborators, evidence, "
        "priority, context, created_by, created_at, updated_at, version) VALUES "
        "('Pont', 'Lire', 'todo', 'loic', '[]', '[]', 'normal', '[]', 'loic', "
        "'2026-09-28T07:00:00+00:00', '2026-09-28T07:00:00+00:00', 1)"
    )
    conn.commit()
    conn.close()
    assert "runs" not in tables(settings.db_path)

    command.upgrade(cfg, "head")  # 0009 adds runs.model: the models describe the head schema

    assert "runs" in tables(settings.db_path)
    engine = create_engine(settings.db_url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []
    conn = sqlite3.connect(settings.db_path)
    indexes = {r[1] for r in conn.execute("PRAGMA index_list('runs')")}
    conn.close()
    assert {"uq_runs_one_active_per_agent_task", "uq_runs_one_active_per_executor",
            "ix_runs_task_id"} <= indexes

    command.downgrade(cfg, "0007")

    assert "runs" not in tables(settings.db_path)
    conn = sqlite3.connect(settings.db_path)
    assert conn.execute("SELECT count(*) FROM tasks").fetchone() == (1,)
    conn.close()


def test_the_database_itself_refuses_a_second_active_run_and_a_repeated_key(settings):
    settings.data_dir.mkdir(parents=True)
    command.upgrade(migrate.alembic_config(settings.db_url), "head")
    insert = (
        "INSERT INTO runs (task_id, executor, agent, dispatched_by, client_key, brief, status, "
        "created_at, version) VALUES (1, 'codex', 'codex', 'loic', ?, 'b', ?, "
        "'2026-11-05T09:00:00+00:00', 1)"
    )
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO tasks (title, objective, status, human_owner, collaborators, evidence, "
        "priority, context, created_by, created_at, updated_at, version) VALUES "
        "('Pont', 'Lire', 'todo', 'loic', '[]', '[]', 'normal', '[]', 'loic', "
        "'2026-09-28T07:00:00+00:00', '2026-09-28T07:00:00+00:00', 1)"
    )
    conn.execute(insert, ("a", "running"))
    for key, status in [("b", "dispatched"), ("a", "done")]:
        try:
            conn.execute(insert, (key, status))
        except sqlite3.IntegrityError:
            continue
        raise AssertionError(f"{key}/{status} accepted")
    conn.execute(insert, ("c", "done"))  # a finished run does not count
    conn.close()
