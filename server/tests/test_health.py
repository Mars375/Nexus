from datetime import datetime

import pytest
from sqlalchemy import inspect

from nexus.db import make_engine


def test_health_reports_db_ok_with_provenance(client):
    body = client.get("/api/health").json()

    assert body["db"]["status"] == "ok"
    assert body["db"]["source"] == "nexus.db"
    assert datetime.fromisoformat(body["db"]["measured_at"]).tzinfo is not None


def test_startup_creates_db_by_migration(client, settings):
    engine = make_engine(settings.db_url)
    tables = inspect(engine).get_table_names()
    engine.dispose()

    assert "app_meta" in tables
    assert "alembic_version" in tables


@pytest.mark.parametrize("keep", [1, 14])
def test_existing_database_is_backed_up_before_migrating(tmp_path, keep):
    import sqlite3

    from conftest import ActorClient

    from nexus import backup
    from nexus.app import create_app
    from nexus.config import Settings

    settings = Settings(data_dir=tmp_path / "data", backup_keep=keep)
    # Base existante, en retard sur les migrations (aucune n'a encore été appliquée).
    settings.data_dir.mkdir(parents=True)
    conn = sqlite3.connect(settings.db_path)
    conn.execute("CREATE TABLE notes (texte TEXT)")
    conn.execute("INSERT INTO notes VALUES ('à garder')")
    conn.commit()
    conn.close()

    with ActorClient(create_app(settings)):
        pass

    # Même avec KEEP=1, la seule copie restante est celle d'avant migration.
    backups = backup.list_backups(settings.backup_dir)
    assert len(backups) == 1
    first = sqlite3.connect(backups[0])
    tables = {r[0] for r in first.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert first.execute("SELECT texte FROM notes").fetchone() == ("à garder",)
    first.close()
    assert "alembic_version" not in tables  # copie prise avant la migration


def test_no_extra_backup_when_nothing_to_migrate(settings):
    from conftest import ActorClient

    from nexus import backup
    from nexus.app import create_app

    with ActorClient(create_app(settings)):
        pass
    with ActorClient(create_app(settings)):
        pass

    assert len(backup.list_backups(settings.backup_dir)) == 2  # une par démarrage


def test_startup_takes_a_backup(client):
    body = client.get("/api/health").json()

    assert body["backup"]["count"] == 1
    assert datetime.fromisoformat(body["backup"]["last_at"]).tzinfo is not None
