"""Server logs without received values (ADR-006, #25, #57).

uvicorn's access log copies the path and parameters as received: a secret slipped into a URL
would end up in clear in the logs. Nexus replaces it with its own line (method, route template,
status, duration) and strips the parameters from the WebSocket lines uvicorn writes on
`uvicorn.error`.

At DEBUG (request line, headers and frames of websockets) and TRACE (uvicorn's scope and ASGI
messages) the logs would copy the WebSocket ticket and the cursors of the URL (#57):
`WebSocketSecretFilter` masks them, from the message format and the argument position, never
from the shape of a value.
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
UNKNOWN_METHOD = "<méthode inconnue>"
# Méthodes HTTP standard (RFC 9110, plus PATCH) : toute autre valeur est un jeton reçu.
HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"}
)
MASKED = "<masqué>"
MASKED_SCOPE = "<scope masqué>"
MASKED_DETAIL = " (détail masqué)"
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
            method = scope.get("method")
            method = method if method in HTTP_METHODS else UNKNOWN_METHOD
            access_log.info("%s %s %d %.0f ms", method, template, status, elapsed)


class WebSocketPathFilter(logging.Filter):
    """Retire les paramètres (et masque un chemin inconnu) des lignes WebSocket d'uvicorn."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the path of uvicorn "WebSocket %s" records in place; always keep the record.

        The path argument is found by position, whatever its shape (an absolute-form target
        has no leading '/'). Its query string is dropped, and any path outside
        WEBSOCKET_PATHS becomes MASKED_PATH. Other records are left unchanged.
        """
        if isinstance(record.msg, str) and '"WebSocket %s"' in record.msg and record.args:
            args = list(record.args) if isinstance(record.args, tuple) else [record.args]
            # L'argument du `%s` de « WebSocket %s », quelle que soit sa forme : une cible en
            # forme absolue (`GET http://h/...`) donne un chemin qui ne commence pas par `/`.
            position = _conversions(record.msg[: record.msg.index('"WebSocket %s"')])
            if position < len(args):
                path = str(args[position]).split("?", 1)[0]
                args[position] = path if path in WEBSOCKET_PATHS else MASKED_PATH
            record.args = tuple(args)
        return True


# websockets (DEBUG): request line, headers and frames, all arguments are received values.
_ALL_ARGUMENTS_MASKED = frozenset({"< %s %s %s", "< %s: %s", "> %s: %s", "< %s", "> %s"})
# uvicorn's MessageLoggerMiddleware (TRACE), on the `uvicorn.asgi` logger only.
_SCOPE_FORMAT = "%s [%d] Started scope=%s"
_MESSAGE_FORMATS = frozenset({"%s [%d] Receive %s", "%s [%d] Send %s"})
ASGI_LOGGER = "uvicorn.asgi"


class WebSocketSecretFilter(logging.Filter):
    """Masks what websockets and uvicorn log at DEBUG and TRACE about a WebSocket handshake.

    Three families, recognised by the exact message format (or the "! " prefix) and by argument
    position, never by what a value looks like (SECURITY §1):
    1. request line, headers and frames of websockets: every argument becomes MASKED;
    2. websockets handshake refusals ("! …", "opening handshake failed"): the traceback, which
       repeats the received header, is dropped and the message says so;
    3. the scope and ASGI messages of uvicorn's TRACE logger: the scope is masked and each
       message is reduced to its `type`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the record in place; always keep it."""
        msg = record.msg
        if not isinstance(msg, str):
            return True
        if msg in _ALL_ARGUMENTS_MASKED:
            count = len(record.args) if isinstance(record.args, tuple) else 1
            record.args = (MASKED,) * count
        elif msg.startswith("! ") or msg == "opening handshake failed":
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
            if not msg.endswith(MASKED_DETAIL):
                record.msg = msg + MASKED_DETAIL
        elif record.name == ASGI_LOGGER and isinstance(record.args, tuple) and record.args:
            args = list(record.args)
            if msg == _SCOPE_FORMAT:
                args[-1] = MASKED_SCOPE
            elif msg in _MESSAGE_FORMATS:
                last = args[-1]
                args[-1] = {"type": last.get("type")} if isinstance(last, dict) else MASKED
            record.args = tuple(args)
        return True


def _conversions(fmt: str) -> int:
    """Nombre de conversions `%` dans un format, sans compter les `%%` littéraux."""
    return fmt.replace("%%", "").count("%")


def uvicorn_log_config() -> dict[str, Any]:
    """Configuration de journalisation d'uvicorn, plus le logger `nexus` et le filtre WebSocket.

    À utiliser avec `access_log=False` : la ligne d'accès vient d'`AccessLogMiddleware`.
    """
    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    filters = config.setdefault("filters", {})
    filters["websocket_path"] = {"()": WebSocketPathFilter}
    filters["websocket_secrets"] = {"()": WebSocketSecretFilter}
    for handler in config["handlers"].values():
        handler.setdefault("filters", []).extend(["websocket_path", "websocket_secrets"])
    config["loggers"]["nexus"] = {"handlers": ["default"], "level": "INFO", "propagate": False}
    # Défense en profondeur : même avec `access_log=True` par erreur, le journal d'accès
    # d'uvicorn (qui recopie l'URL reçue) n'a aucune sortie.
    config["loggers"]["uvicorn.access"] = {"handlers": [], "level": "INFO", "propagate": False}
    return config
