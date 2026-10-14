"""Migration 0006 (tasks.follows_id): populated round trip, real foreign key, schema = models."""

import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from conftest import ActorClient
from sqlalchemy import create_engine

from nexus import migrate
from nexus.app import create_app
from nexus.db import Base

TS = "2026-10-13T07:00:00+00:00"
TABLES = ("tasks", "task_dependencies", "task_comments", "task_history", "events")


def counts(path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        conn.close()


def columns(path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
    finally:
        conn.close()


def indexes(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute("PRAGMA index_list(tasks)")}
    finally:
        conn.close()


@pytest.fixture
def at_0005(settings):
    """A 0005 database holding a done task with a dependency, a comment, history and an event."""
    settings.data_dir.mkdir(parents=True)
    command.upgrade(migrate.alembic_config(settings.db_url), "0005")
    conn = sqlite3.connect(settings.db_path)
    task = (
        "INSERT INTO tasks (title, objective, status, human_owner, collaborators, evidence, "
        "priority, context, created_by, created_at, updated_at, version) VALUES "
        f"(?, 'Lire', ?, 'loic', '[]', '[\"commit:abc\"]', 'normal', '[]', 'loic', '{TS}', "
        f"'{TS}', 1)"
    )
    conn.execute(task, ("Livrée", "done"))
    conn.execute(task, ("Avant", "done"))
    conn.execute("INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (1, 2)")
    conn.execute(f"INSERT INTO task_comments (task_id, author, body, at) "
                 f"VALUES (1, 'loic', 'ok', '{TS}')")
    conn.execute(f"INSERT INTO task_history (task_id, actor, at, action, changes) "
                 f"VALUES (1, 'loic', '{TS}', 'created', '{{}}')")
    conn.execute(
        "INSERT INTO events (actor, actor_event_id, at, received_at, task_id, kind, subject, "
        "payload, evidence, needs, redacted, origin, effects) VALUES "
        f"('helios', 'e1', '{TS}', '{TS}', 1, 'progress', 's', '{{}}', '[]', '[]', '[]', 'api', "
        "'[]')"
    )
    conn.commit()
    conn.close()
    return settings


def test_upgrade_keeps_every_row_and_leaves_the_link_empty(at_0005):
    before = counts(at_0005.db_path)
    assert "follows_id" not in columns(at_0005.db_path)
    migrate.upgrade(at_0005.db_url)
    assert counts(at_0005.db_path) == before == {
        "tasks": 2, "task_dependencies": 1, "task_comments": 1, "task_history": 1, "events": 1
    }
    conn = sqlite3.connect(at_0005.db_path)
    assert conn.execute("SELECT follows_id FROM tasks").fetchall() == [(None,), (None,)]
    conn.close()
    assert "ix_tasks_follows_id" in indexes(at_0005.db_path)


def test_a_migrated_done_task_is_read_only(at_0005):
    migrate.upgrade(at_0005.db_url)
    with ActorClient(create_app(at_0005), authenticate=True) as client:
        res = client.patch("/api/tasks/nx-task-1", json={"title": "Autre"})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "task_done"
        task = client.get("/api/tasks/nx-task-1").json()
        assert task["follows"] is None and task["depends_on"] == ["nx-task-2"]
        assert client.post("/api/tasks/nx-task-1/comments", json={"body": "ok"}).status_code == 201


def test_downgrade_then_upgrade_round_trip(at_0005):
    migrate.upgrade(at_0005.db_url)
    before = counts(at_0005.db_path)
    config = migrate.alembic_config(at_0005.db_url)
    command.downgrade(config, "0005")
    assert "follows_id" not in columns(at_0005.db_path)
    assert "ix_tasks_follows_id" not in indexes(at_0005.db_path)
    assert counts(at_0005.db_path) == before
    command.upgrade(config, "head")
    assert "follows_id" in columns(at_0005.db_path)
    assert counts(at_0005.db_path) == before


def test_the_foreign_key_is_real_and_sets_null_on_delete(at_0005):
    migrate.upgrade(at_0005.db_url)
    conn = sqlite3.connect(at_0005.db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    [fk] = [r for r in conn.execute("PRAGMA foreign_key_list(tasks)") if r[3] == "follows_id"]
    assert fk[2] == "tasks" and fk[6] == "SET NULL"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE tasks SET follows_id = 999 WHERE id = 1")
    conn.execute("UPDATE tasks SET follows_id = 2 WHERE id = 1")
    conn.execute("DELETE FROM task_dependencies")  # the link below is the only one left
    conn.execute("DELETE FROM tasks WHERE id = 2")
    assert conn.execute("SELECT follows_id FROM tasks WHERE id = 1").fetchone() == (None,)
    conn.close()


def test_the_migrated_schema_matches_the_models(at_0005):
    migrate.upgrade(at_0005.db_url)
    engine = create_engine(at_0005.db_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_an_empty_database_migrates_to_head(settings):
    settings.data_dir.mkdir(parents=True)
    migrate.upgrade(settings.db_url)
    assert "follows_id" in columns(settings.db_path)
