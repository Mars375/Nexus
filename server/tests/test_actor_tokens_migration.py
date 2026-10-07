"""Migration 0005 (actor_tokens) : montée, schéma conforme aux modèles, descente."""

import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from nexus import migrate
from nexus.actors import ACTORS
from nexus.app import create_app
from nexus.db import Base

HASH = "a" * 64


def tables(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def at_0004(settings):
    settings.data_dir.mkdir(parents=True)
    command.upgrade(migrate.alembic_config(settings.db_url), "0004")
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO tasks (title, objective, status, human_owner, collaborators, evidence, "
        "priority, context, created_by, created_at, updated_at, version) VALUES "
        "('Pont', 'Lire', 'todo', 'loic', '[]', '[]', 'normal', '[]', 'loic', "
        "'2026-09-28T07:00:00+00:00', '2026-09-28T07:00:00+00:00', 1)"
    )
    conn.commit()
    conn.close()


def test_upgrading_a_0004_database_keeps_its_data_and_adds_no_token(settings):
    at_0004(settings)
    assert "actor_tokens" not in tables(settings.db_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/tasks/nx-task-1").status_code == 200
    conn = sqlite3.connect(settings.db_path)
    head = ScriptDirectory.from_config(migrate.alembic_config(settings.db_url)).get_current_head()
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (head,)
    assert conn.execute("SELECT count(*) FROM actor_tokens").fetchone() == (0,)
    conn.close()


def test_the_migrated_schema_matches_the_models(settings):
    at_0004(settings)
    migrate.upgrade(settings.db_url)
    engine = create_engine(settings.db_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_the_constraints_hold_in_the_database(settings):
    at_0004(settings)
    migrate.upgrade(settings.db_url)
    conn = sqlite3.connect(settings.db_path)
    insert = (
        "INSERT INTO actor_tokens (actor, label, token_hash, created_at) "
        "VALUES (?, ?, ?, '2026-10-07T07:00:00+00:00')"
    )
    conn.execute(insert, ("loic", "navigateur", HASH))
    for args in [
        ("loic", "autre", HASH),  # empreinte unique
        ("mallory", "x", "b" * 64),  # acteur inconnu
        ("loic", "", "c" * 64),  # label vide
        ("loic", "x" * 65, "d" * 64),  # label trop long
        ("loic", "x", "e" * 63),  # empreinte de mauvaise longueur
    ]:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, args)
    conn.close()


def test_downgrade_round_trip_keeps_the_other_tables(settings):
    at_0004(settings)
    migrate.upgrade(settings.db_url)
    config = migrate.alembic_config(settings.db_url)
    command.downgrade(config, "0004")
    assert "actor_tokens" not in tables(settings.db_path)
    conn = sqlite3.connect(settings.db_path)
    assert conn.execute("SELECT title FROM tasks").fetchone() == ("Pont",)
    conn.close()
    command.upgrade(config, "head")
    assert "actor_tokens" in tables(settings.db_path)


def test_every_known_actor_can_hold_a_token(settings):
    """Adding an actor to ACTORS needs a migration (ADR-020): this fails until it exists."""
    at_0004(settings)
    migrate.upgrade(settings.db_url)
    conn = sqlite3.connect(settings.db_path)
    for index, actor in enumerate(sorted(ACTORS)):
        conn.execute(
            "INSERT INTO actor_tokens (actor, label, token_hash, created_at) "
            "VALUES (?, 'x', ?, '2026-10-07T07:00:00+00:00')",
            (actor, f"{index:064x}"),
        )
    conn.close()
