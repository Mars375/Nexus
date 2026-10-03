"""Journaux du serveur sans valeur reçue (ADR-006, #25).

Le journal d'accès d'uvicorn recopie le chemin et les paramètres tels que reçus : un secret
glissé dans une URL finirait en clair dans les journaux. Nexus le remplace par sa propre ligne
(méthode, gabarit de route, statut, durée) et retire les paramètres des lignes WebSocket
qu'uvicorn écrit sur `uvicorn.error`.
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

access_log = logging.getLogger("nexus.access")

UNKNOWN_ROUTE = "<route inconnue>"
MASKED_PATH = "<chemin masqué>"
# Seules routes WebSocket : leur chemin sans paramètres ne porte aucune valeur reçue.
WEBSOCKET_PATHS = frozenset({"/api/ws"})


class AccessLogMiddleware:
    """Une ligne par requête HTTP : `GET /api/tasks/{task_ref} 404 3 ms`."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the ASGI app to record HTTP request summaries."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run the app, passing non-HTTP scopes through without an access entry.

        On HTTP completion or failure, record the method, route template (or
        UNKNOWN_ROUTE), response status, and elapsed time rounded to milliseconds.
        The received path and query string are omitted. If no response start was
        observed, the recorded status is 500. App and send errors propagate after
        the access entry is attempted.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500  # sans réponse émise (exception), c'est une erreur serveur

        async def send_wrapper(message: dict) -> None:
            """Capture the response status and forward the message, propagating send errors."""
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None) or UNKNOWN_ROUTE
            elapsed = (time.perf_counter() - started) * 1000
            access_log.info("%s %s %d %.0f ms", scope["method"], template, status, elapsed)


class WebSocketPathFilter(logging.Filter):
    """Retire les paramètres (et masque un chemin inconnu) des lignes WebSocket d'uvicorn."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize matching WebSocket records in place and always return True.

        For messages containing '"WebSocket %s"' with arguments, strip query strings
        from string arguments starting with '/'. Keep paths in WEBSOCKET_PATHS and
        replace other paths with MASKED_PATH. Other records are left unchanged.
        """
        if isinstance(record.msg, str) and '"WebSocket %s"' in record.msg and record.args:
            args = list(record.args) if isinstance(record.args, tuple) else [record.args]
            for i, value in enumerate(args):
                if isinstance(value, str) and value.startswith("/"):
                    path = value.split("?", 1)[0]
                    args[i] = path if path in WEBSOCKET_PATHS else MASKED_PATH
            record.args = tuple(args)
        return True


def uvicorn_log_config() -> dict[str, Any]:
    """Configuration de journalisation d'uvicorn, plus le logger `nexus` et le filtre WebSocket.

    À utiliser avec `access_log=False` : la ligne d'accès vient d'`AccessLogMiddleware`.
    """
    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["websocket_path"] = {"()": WebSocketPathFilter}
    for handler in config["handlers"].values():
        handler.setdefault("filters", []).append("websocket_path")
    config["loggers"]["nexus"] = {"handlers": ["default"], "level": "INFO", "propagate": False}
    return config
