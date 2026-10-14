"""No ticket, cursor or frame reaches the DEBUG and TRACE logs of a real server (#57)."""

import io
import logging
import secrets as stdlib_secrets

import pytest
from conftest import (
    issue_ticket_http,
    issue_token,
    raw_handshake,
    serve_real,
    stop_real,
    tailscale_json,
)
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from nexus.app import create_app
from nexus.auth import tokens
from nexus.live import LIVE_PROTOCOL
from nexus.logs import uvicorn_log_config

LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi", "nexus",
           "nexus.access")


@pytest.fixture
def isolated_logging():
    """Restore every logger uvicorn's dictConfig touches (it sets `nexus.propagate = False`)."""
    saved = {}
    for name in LOGGERS:
        logger = logging.getLogger(name)
        saved[name] = (logger.level, list(logger.handlers), list(logger.filters),
                       logger.propagate, logger.disabled)
    try:
        yield
    finally:
        for name, (level, handlers, filters, propagate, disabled) in saved.items():
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.handlers[:] = handlers
            logger.filters[:] = filters
            logger.propagate = propagate
            logger.disabled = disabled


@pytest.mark.parametrize("level", ["debug", "trace"])
def test_no_ticket_or_cursor_reaches_debug_or_trace_logs(settings, isolated_logging, level):
    stream = io.StringIO()
    config = uvicorn_log_config()
    for handler in config["handlers"].values():
        handler["stream"] = stream
    app = create_app(settings, nodes_runner=tailscale_json)
    server, thread, port = serve_real(app, log_config=config, log_level=level)
    marker = "marqueur-" + stdlib_secrets.token_hex(8)
    history_cursor, events_cursor = "987654321098", "876543210987"
    issued: list[str] = []
    try:
        token = issue_token(app)
        instance = app.state.live_instance
        url = (f"ws://127.0.0.1:{port}/api/ws?history_after={history_cursor}"
               f"&events_after={events_cursor}&instance={instance}")

        # An accepted connection: hello received, a marker frame sent.
        ticket = issue_ticket_http(port, token)
        issued.append(ticket)
        with connect(url, subprotocols=[LIVE_PROTOCOL, ticket]) as ws:
            assert "hello" in ws.recv()
            ws.send(marker)

        # A refused connection (unknown ticket, built at runtime) and a replayed one.
        unknown = "nxw_" + stdlib_secrets.token_urlsafe(32)
        issued.append(unknown)
        for refused in (unknown, ticket):
            with pytest.raises(InvalidStatus) as closed:
                connect(url, subprotocols=[LIVE_PROTOCOL, refused]).close()
            assert closed.value.response.status_code == 403

        # A hand-written handshake that websockets itself rejects with a 400 (space, no comma).
        fresh = issue_ticket_http(port, token)
        issued.append(fresh)
        bad = raw_handshake(port, f"localhost:{port}", f"{LIVE_PROTOCOL} {fresh}")
        assert bad.startswith("HTTP/1.1 400"), bad.splitlines()[:1]
        # Documented exception to ADR-006 (spec 3.6): the 400 body echoes the header to its
        # sender. If websockets stops doing so, the note must be reviewed.
        assert fresh in bad, (
            "websockets no longer echoes the header in its 400 body: re-evaluate this expectation "
            "and update the ADR-006 exception note in DECISIONS.md"
        )
        # That refusal did not spend the ticket.
        good = raw_handshake(port, f"localhost:{port}", f"{LIVE_PROTOCOL}, {fresh}")
        assert good.startswith("HTTP/1.1 101"), good.splitlines()[:1]
    finally:
        stop_real(server, thread)
    output = stream.getvalue()
    assert output, "the server wrote nothing: the test would prove nothing"
    forbidden = [history_cursor, events_cursor, instance, marker]
    for value in issued:
        forbidden += [value, value[len("nxw_"):], tokens.digest(value)]
    for value in forbidden:
        assert value not in output, "a received value reached the logs"
    assert "! invalid handshake (détail masqué)" in output
    assert "Traceback" not in output
