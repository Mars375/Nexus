"""Application FastAPI de Nexus."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from functools import partial
from importlib.metadata import version
from secrets import token_hex  # not `nexus.secrets`

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from nexus import backup, live, migrate, nodes
from nexus import now as now_view
from nexus.approvals import api as approvals_api
from nexus.approvals.service import ApprovalNotFound
from nexus.auth import tokens
from nexus.auth.deps import Authenticated
from nexus.auth.tickets import TicketStore
from nexus.clock import now
from nexus.config import Settings
from nexus.db import make_engine
from nexus.events import api as events_api
from nexus.events.service import EventNotFound
from nexus.hosts import HostCheckMiddleware
from nexus.logs import AccessLogMiddleware
from nexus.permissions import Forbidden
from nexus.tasks import api as tasks_api
from nexus.tasks.rules import RuleViolation
from nexus.tasks.service import TaskNotFound
from nexus.validation import french_errors

log = logging.getLogger("nexus")

FIRST_NODES_READ_SECONDS = 1.0


def create_app(
    settings: Settings | None = None, nodes_runner: nodes.Runner | None = None
) -> FastAPI:
    """Return the Nexus API with route-template access logging and managed startup.

    Omitted settings are read from the environment; invalid values raise ValueError.
    The optional nodes_runner takes no arguments and returns Tailscale status JSON;
    by default, the configured Tailscale executable supplies it.

    The app's lifespan creates the data directory, migrates and backs up the database,
    and starts periodic backups and node refreshes. Startup filesystem, migration,
    and backup errors propagate; expected Tailscale failures yield unknown node states.
    Shutdown cancels the periodic tasks and disposes of the database engine.
    """
    settings = settings or Settings.from_env()
    nodes_runner = nodes_runner or partial(nodes.run_tailscale, settings.tailscale_bin)

    async def refresh_nodes(app: FastAPI) -> list[nodes.NodeState]:
        # Hors de la boucle événementielle : un Tailscale lent ne bloque pas l'API.
        app.state.nodes = await asyncio.to_thread(nodes.probe, nodes_runner)
        return app.state.nodes

    async def nodes_loop(app: FastAPI, first_read: asyncio.Task) -> None:
        # Une seule lecture à la fois : on attend la première avant de rafraîchir.
        try:
            await first_read
        except Exception:
            # La lecture attendue ne lève jamais (probe rend « unknown ») : ceci est un vrai bug.
            log.exception("première lecture de l'état des nœuds échouée")
        while True:
            await asyncio.sleep(settings.nodes_refresh_seconds)
            try:
                await refresh_nodes(app)
            except Exception:
                log.exception("lecture de l'état des nœuds échouée")

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
        # Elle tient lieu de sauvegarde de démarrage : une seconde copie ferait tourner la
        # rotation et pourrait effacer ce point de retour (ex. NEXUS_BACKUP_KEEP=1).
        before_migration = settings.db_path.is_file() and migrate.pending(settings.db_url)
        if before_migration:
            backup.backup(settings.db_path, settings.backup_dir, settings.backup_keep)
        migrate.upgrade(settings.db_url)
        # Random per process, derived from nothing: a cursor from another run (restart, restored
        # base) is never trusted by the live endpoint (#25).
        app.state.live_instance = token_hex(8)
        # Same lifetime as the instance: a ticket from a previous run is refused (#57).
        app.state.ws_tickets = TicketStore()
        app.state.engine = make_engine(settings.db_url)
        app.state.sessionmaker = sessionmaker(app.state.engine, expire_on_commit=False)
        # The diagnostic write (last_used_at) gets its own engine with a short busy timeout:
        # a locked database delays an authenticated request by a fraction of a second (#58).
        app.state.touch_engine = make_engine(settings.db_url, timeout=tokens.TOUCH_BUSY_TIMEOUT)
        app.state.touch_sessionmaker = sessionmaker(app.state.touch_engine, expire_on_commit=False)
        if not before_migration:
            backup.backup(settings.db_path, settings.backup_dir, settings.backup_keep)
        # Réponse immédiate (unknown) tant que la première lecture n'a pas abouti ; on lui
        # laisse une seconde pour que le cas normal serve d'emblée l'état réel.
        app.state.nodes = nodes.pending_snapshot()
        first_read = asyncio.create_task(refresh_nodes(app))
        await asyncio.wait({first_read}, timeout=FIRST_NODES_READ_SECONDS)
        tasks = [
            asyncio.create_task(backup_loop()),
            asyncio.create_task(nodes_loop(app, first_read)),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            app.state.engine.dispose()
            app.state.touch_engine.dispose()

    app = FastAPI(title="Nexus", version=version("nexus"), lifespan=lifespan)
    # Journal d'accès sans valeur reçue (ADR-006) : gabarit de route, jamais le chemin réel.
    app.add_middleware(AccessLogMiddleware)
    # CORS for the REST API (#47): the exact NEXUS_ALLOWED_ORIGINS list, never `*`;
    # no credentials (the token travels in Authorization). Added before the Host check
    # so that HostCheck stays outermost: a foreign Host is refused before a preflight
    # can be answered (ADR-020, D6).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=tuple(sorted(settings.allowed_origins)),
        allow_methods=("GET", "POST", "PATCH", "PUT", "DELETE"),
        allow_headers=("authorization", "content-type", "x-nexus-actor"),
        allow_credentials=False,
        allow_private_network=True,
        max_age=600,
    )
    # Added after the log so that it is outermost: a foreign Host (DNS rebinding) reaches nothing,
    # neither a route nor the database (ADR-020, D6). The log then does not see its refusals.
    # The IP addresses of NEXUS_HOST are admitted as `Host` without being declared twice
    # (ADR-021, D11); a MagicDNS name still has to be declared in NEXUS_ALLOWED_HOSTS.
    app.add_middleware(
        HostCheckMiddleware, allowed_hosts=settings.allowed_hosts | settings.host_literals
    )
    app.state.settings = settings
    app.include_router(tasks_api.router)
    app.include_router(events_api.router)
    app.include_router(approvals_api.router)
    app.include_router(now_view.router)
    # WebSocket: single-use ticket (#57); POST /api/ws-ticket itself requires a token.
    app.include_router(live.router)

    @app.exception_handler(RequestValidationError)
    def _invalid(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Jamais la valeur reçue dans la réponse : elle peut contenir un secret (ADR-006),
        # et la validation a lieu avant le masquage.
        return JSONResponse(status_code=422, content={"detail": french_errors(exc.errors())})

    @app.exception_handler(StaleDataError)
    def _stale(_request: Request, _exc: StaleDataError) -> JSONResponse:
        # Verrou optimiste : la tâche a changé depuis sa lecture (autre requête, agent…).
        return JSONResponse(status_code=409, content={"detail": {
            "code": "concurrent_update",
            "message": "la tâche vient d'être modifiée par ailleurs : recharge-la et réessaie",
        }})

    @app.exception_handler(RuleViolation)
    def _rule_violation(_request: Request, exc: RuleViolation) -> JSONResponse:
        return JSONResponse(
            status_code=409, content={"detail": {"code": exc.code, "message": exc.message}}
        )

    @app.exception_handler(Forbidden)
    def _forbidden(_request: Request, exc: Forbidden) -> JSONResponse:
        return JSONResponse(
            status_code=403, content={"detail": {"code": exc.code, "message": exc.message}}
        )

    @app.exception_handler(TaskNotFound)
    @app.exception_handler(EventNotFound)
    @app.exception_handler(ApprovalNotFound)
    def _not_found(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"detail": {"code": "not_found", "message": str(exc)}}
        )

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
        measured_at = now().isoformat()
        return {
            "version": app.version,
            "db": {"status": db_status, "source": "nexus.db", "measured_at": measured_at},
            "backup": {"last_at": last, "count": len(backups), "source": "nexus.db/backups",
                       "measured_at": measured_at},
        }

    @app.get("/api/nodes", dependencies=Authenticated)
    async def list_nodes() -> list[dict]:
        """État des nœuds (lecture seule), chacun avec sa source et sa fraîcheur."""
        return [s.to_dict() for s in app.state.nodes]

    return app
