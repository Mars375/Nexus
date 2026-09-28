from datetime import datetime

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


def test_startup_takes_a_backup(client):
    body = client.get("/api/health").json()

    assert body["backup"]["count"] == 1
    assert datetime.fromisoformat(body["backup"]["last_at"]).tzinfo is not None
