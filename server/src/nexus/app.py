"""Application FastAPI de Nexus."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from importlib.metadata import version

from fastapi import FastAPI
from sqlalchemy import text

from nexus import backup, migrate
from nexus.clock import now
from nexus.config import Settings
from nexus.db import make_engine

log = logging.getLogger("nexus")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    async def backup_loop() -> None:
        while True:
            await asyncio.sleep(settings.backup_interval_hours * 3600)
            try:
                # Hors de la boucle événementielle : une copie lente ne bloque pas l'API.
                await asyncio.to_thread(
                    backup.backup, settings.db_path, settings.backup_dir, settings.backup_keep
                )
            except Exception:
                log.exception("sauvegarde de nexus.db échouée")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        # Réversibilité (ROADMAP, règle 5) : copie de la base existante avant toute migration.
        if settings.db_path.is_file() and migrate.pending(settings.db_url):
            backup.backup(settings.db_path, settings.backup_dir, settings.backup_keep)
        migrate.upgrade(settings.db_url)
        app.state.engine = make_engine(settings.db_url)
        backup.backup(settings.db_path, settings.backup_dir, settings.backup_keep)
        task = asyncio.create_task(backup_loop())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            app.state.engine.dispose()

    app = FastAPI(title="Nexus", version=version("nexus"), lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict:
        try:
            with app.state.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_status = "ok"
        except Exception:
            log.exception("nexus.db injoignable")
            db_status = "unknown"
        backups = backup.list_backups(settings.backup_dir)
        last = backup.backup_time(backups[-1]).isoformat() if backups else None
        return {
            "version": app.version,
            "db": {"status": db_status, "source": "nexus.db", "measured_at": now().isoformat()},
            "backup": {"last_at": last, "count": len(backups), "source": "nexus.db/backups"},
        }

    return app
