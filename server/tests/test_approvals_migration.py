"""Migration 0004 (approvals) on a populated 0003 database, with the backup taken before it."""

import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from nexus import backup, migrate
from nexus.app import create_app
from nexus.config import Settings
from nexus.db import Base


def populated_0003(settings: Settings) -> None:
    """A real database as 0.3 left it: migrated to 0003, with a task and an open ask."""
    settings.data_dir.mkdir(parents=True)
    command.upgrade(migrate.alembic_config(settings.db_url), "0003")
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO tasks (title, objective, status, human_owner, collaborators, evidence, "
        "priority, context, created_by, created_at, updated_at, version) VALUES "
        "('Pont', 'Lire', 'todo', 'loic', '[]', '[]', 'normal', '[]', 'loic', "
        "'2026-09-28T07:00:00+00:00', '2026-09-28T07:00:00+00:00', 1)"
    )
    conn.execute(
        "INSERT INTO events (actor, actor_event_id, at, received_at, task_id, kind, subject, "
        "payload, evidence, needs, redacted, origin, effects) VALUES "
        "('mnema', 'old', '2026-09-28T07:05:00+00:00', '2026-09-28T07:05:00+00:00', 1, "
        "'needs_human', 'Ancienne demande', '{\"options\": [\"a\", \"b\"]}', '[]', '[\"loic\"]', "
        "'[]', 'api', '[]')"
    )
    conn.commit()
    conn.close()


def tables(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_upgrading_a_populated_0003_database_keeps_its_data_and_opens_no_approval(settings):
    populated_0003(settings)
    assert "approvals" not in tables(settings.db_path)

    with TestClient(create_app(settings)) as client:
        events = client.get("/api/events").json()
        assert [e["subject"] for e in events] == ["Ancienne demande"]
        assert events[0]["effects"] == []
        assert client.get("/api/approvals").json() == []  # D6: no backfill
        assert client.get("/api/tasks/nx-task-1").status_code == 200

    conn = sqlite3.connect(settings.db_path)
    head = ScriptDirectory.from_config(migrate.alembic_config(settings.db_url)).get_current_head()
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (head,)
    conn.close()


def test_the_database_is_copied_before_migrating_to_0004(settings):
    populated_0003(settings)

    with TestClient(create_app(settings)):
        pass

    backups = backup.list_backups(settings.backup_dir)
    assert len(backups) == 1  # the pre-migration copy stands in for the startup backup
    assert "approvals" not in tables(backups[0])
    copy = sqlite3.connect(backups[0])
    assert copy.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)
    assert copy.execute("SELECT subject FROM events").fetchone() == ("Ancienne demande",)
    copy.close()


def test_a_new_ask_after_the_upgrade_gets_the_first_approval(settings):
    populated_0003(settings)

    with TestClient(create_app(settings)) as client:
        res = client.post("/api/events", json={
            "id": "new", "at": "2026-09-28T09:05:00+02:00", "actor": "helios",
            "kind": "question", "subject": "Nouvelle", "needs": ["loic"],
        })
        assert res.json()["effects"][0]["approval"] == "nx-appr-1"


def test_the_migrated_schema_matches_the_models(settings):
    populated_0003(settings)
    migrate.upgrade(settings.db_url)

    engine = create_engine(settings.db_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()

    assert diff == []


def test_the_constraints_hold_in_the_database(settings):
    populated_0003(settings)
    migrate.upgrade(settings.db_url)
    conn = sqlite3.connect(settings.db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    insert = (
        "INSERT INTO approvals (request_event_id, ask_kind, status, version) "
        "VALUES (?, 'needs_human', 'pending', 1)"
    )
    conn.execute(insert, (1,))
    with pytest.raises(sqlite3.IntegrityError):  # one approval per request event
        conn.execute(insert, (1,))
    with pytest.raises(sqlite3.IntegrityError):  # the request event must exist
        conn.execute(insert, (99,))
    indexes = {r[1] for r in conn.execute("PRAGMA index_list(approvals)")}
    assert "ix_approvals_status" in indexes
    conn.close()


def test_downgrade_round_trip_keeps_the_other_tables(settings):
    populated_0003(settings)
    migrate.upgrade(settings.db_url)
    config = migrate.alembic_config(settings.db_url)

    command.downgrade(config, "0003")
    assert "approvals" not in tables(settings.db_path)
    conn = sqlite3.connect(settings.db_path)
    assert conn.execute("SELECT subject FROM events").fetchone() == ("Ancienne demande",)
    conn.close()

    command.upgrade(config, "head")
    assert "approvals" in tables(settings.db_path)
