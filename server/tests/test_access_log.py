"""Journal des requêtes (#25, ADR-006) : jamais une valeur reçue, seulement le gabarit de route."""

import asyncio
import copy
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from nexus import logs
from nexus.logs import (
    AccessLogMiddleware,
    WebSocketPathFilter,
    WebSocketSecretFilter,
    uvicorn_log_config,
)

SECRET = "ghp_" + "A" * 36  # fabriqué à l'exécution : jamais un vrai secret dans le dépôt


def access_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "nexus.access"]


def test_a_request_is_logged_with_its_route_template_not_its_values(client, caplog):
    caplog.set_level(logging.INFO, logger="nexus.access")
    client.get(f"/api/tasks/{SECRET}?q={SECRET}")
    lines = access_lines(caplog)
    assert lines, "chaque requête laisse une ligne"
    assert "GET /api/tasks/{task_ref} 404" in lines[-1]
    assert all(SECRET not in line for line in lines)


def test_an_unknown_route_is_logged_without_its_path(client, caplog):
    caplog.set_level(logging.INFO, logger="nexus.access")
    client.get(f"/api/{SECRET}")
    line = access_lines(caplog)[-1]
    assert "GET <route inconnue> 404" in line
    assert SECRET not in line


def test_the_line_gives_status_and_duration(client, caplog):
    caplog.set_level(logging.INFO, logger="nexus.access")
    client.get("/api/health")
    line = access_lines(caplog)[-1]
    assert line.startswith("GET /api/health 200 ")
    assert line.endswith(" ms")


def _ws_record(path: str, suffix: str = "[accepted]") -> logging.LogRecord:
    # Forme exacte des lignes WebSocket d'uvicorn (logger uvicorn.error).
    return logging.LogRecord("uvicorn.error", logging.INFO, __file__, 0,
                             '%s - "WebSocket %s" ' + suffix, ("127.0.0.1:5000", path), None)


def test_websocket_lines_lose_their_query_string():
    record = _ws_record(f"/api/ws?history_after={SECRET}&events_after=0")
    assert WebSocketPathFilter().filter(record) is True
    assert record.getMessage() == '127.0.0.1:5000 - "WebSocket /api/ws" [accepted]'


def test_the_websocket_instance_parameter_is_never_logged():
    instance = "ab" * 8  # built at runtime: the value must appear in no log record
    record = _ws_record(f"/api/ws?history_after=1&events_after=2&instance={instance}")
    assert WebSocketPathFilter().filter(record) is True
    assert instance not in record.getMessage()
    assert record.getMessage() == '127.0.0.1:5000 - "WebSocket /api/ws" [accepted]'


def test_an_unknown_websocket_path_is_masked():
    record = _ws_record(f"/api/{SECRET}", "403")
    WebSocketPathFilter().filter(record)
    assert SECRET not in record.getMessage()
    assert "<chemin masqué>" in record.getMessage()


def test_other_records_are_left_alone():
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 0,
                               "Application startup complete.", None, None)
    assert WebSocketPathFilter().filter(record) is True
    assert record.getMessage() == "Application startup complete."


def test_both_entry_points_turn_off_uvicorns_access_log(monkeypatch, tmp_path):
    import uvicorn

    import nexus
    from nexus import serving

    configs, calls = [], []

    async def fake_serve(config, settings):
        configs.append(config)
        return True

    monkeypatch.setattr(serving, "serve", fake_serve)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.append(kw))
    # The real `Config` would reconfigure the logging of the whole test session.
    monkeypatch.setattr(uvicorn.Config, "configure_logging", lambda self: None)
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    nexus.main()
    nexus.dev()
    assert len(configs) == 1 and len(calls) == 1
    assert configs[0].access_log is False
    assert "websocket_path" in configs[0].log_config["filters"]
    assert calls[0]["access_log"] is False
    assert "websocket_path" in calls[0]["log_config"]["filters"]


def test_uvicorn_runs_without_its_access_log_and_with_ours():
    config = uvicorn_log_config()
    assert config["loggers"]["nexus"]["level"] == "INFO"
    assert "nexus" in config["loggers"] and config["loggers"]["nexus"]["handlers"]
    assert any(
        f == "websocket_path" for f in config["handlers"]["default"].get("filters", [])
    )


@pytest.fixture
def http_scope():
    return {
        "type": "http", "method": "PATCH", "path": f"/api/tasks/{SECRET}",
        "query_string": f"q={SECRET}".encode(),
    }


def test_streamed_response_is_forwarded_and_logged_once_after_completion(
    http_scope, caplog, monkeypatch,
):
    caplog.set_level(logging.INFO, logger="nexus.access")
    clock = Mock(side_effect=[100, 100.125])
    monkeypatch.setattr(logs, "time", SimpleNamespace(perf_counter=clock))
    request = {"type": "http.request", "body": b"payload", "more_body": False}
    receive = AsyncMock(return_value=request)
    send = AsyncMock()
    messages = [
        {"type": "http.response.start", "status": 202, "headers": [(b"x-test", b"value")]},
        {"type": "http.response.body", "body": b"first", "more_body": True},
        {"type": "http.response.body", "body": b"last", "more_body": False},
    ]

    async def app(scope, inner_receive, inner_send):
        assert scope is http_scope
        assert inner_receive is receive
        assert await inner_receive() is request
        # Le routeur renseigne le gabarit après l'entrée dans le middleware.
        scope["route"] = SimpleNamespace(path="/api/tasks/{task_ref}")
        for message in messages:
            await inner_send(message)
            assert access_lines(caplog) == []

    asyncio.run(AccessLogMiddleware(app)(http_scope, receive, send))

    receive.assert_awaited_once_with()
    assert [call.args[0] for call in send.await_args_list] == messages
    assert access_lines(caplog) == ["PATCH /api/tasks/{task_ref} 202 125 ms"]


@pytest.mark.parametrize("route", [None, SimpleNamespace(), SimpleNamespace(path="")])
def test_missing_route_templates_never_fall_back_to_the_received_path(
    route, http_scope, caplog,
):
    caplog.set_level(logging.INFO, logger="nexus.access")
    http_scope["route"] = route

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(AccessLogMiddleware(app)(http_scope, AsyncMock(), AsyncMock()))

    lines = access_lines(caplog)
    assert len(lines) == 1
    assert lines[0].startswith("PATCH <route inconnue> 404 ")
    assert SECRET not in lines[0]


@pytest.mark.parametrize("started_status", [None, 200])
def test_application_errors_are_reraised_and_logged_with_the_observed_status(
    started_status, http_scope, caplog,
):
    caplog.set_level(logging.INFO, logger="nexus.access")
    error = RuntimeError(SECRET)

    async def app(scope, receive, send):
        scope["route"] = SimpleNamespace(path="/api/tasks/{task_ref}")
        if started_status is not None:
            await send({"type": "http.response.start", "status": started_status, "headers": []})
        raise error

    with pytest.raises(RuntimeError) as raised:
        asyncio.run(AccessLogMiddleware(app)(http_scope, AsyncMock(), AsyncMock()))

    assert raised.value is error
    lines = access_lines(caplog)
    assert len(lines) == 1
    expected_status = 500 if started_status is None else started_status
    assert lines[0].startswith(f"PATCH /api/tasks/{{task_ref}} {expected_status} ")
    assert SECRET not in lines[0]


def test_send_errors_are_reraised_and_still_leave_an_access_line(http_scope, caplog):
    caplog.set_level(logging.INFO, logger="nexus.access")
    error = OSError(SECRET)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 503, "headers": []})

    with pytest.raises(OSError) as raised:
        asyncio.run(AccessLogMiddleware(app)(http_scope, AsyncMock(), AsyncMock(side_effect=error)))

    assert raised.value is error
    lines = access_lines(caplog)
    assert len(lines) == 1
    assert lines[0].startswith("PATCH <route inconnue> 503 ")
    assert SECRET not in lines[0]


@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
def test_non_http_scopes_pass_through_without_access_logging(scope_type, caplog):
    caplog.set_level(logging.INFO, logger="nexus.access")
    scope = {"type": scope_type}
    receive, send = AsyncMock(), AsyncMock()
    app = AsyncMock()

    asyncio.run(AccessLogMiddleware(app)(scope, receive, send))

    app.assert_awaited_once_with(scope, receive, send)
    assert access_lines(caplog) == []


@pytest.mark.parametrize("suffix", ["[accepted]", "403", "%d"])
@pytest.mark.parametrize("query", ["", "?", f"?token={SECRET}&next=/api/{SECRET}?again=yes"])
def test_known_websocket_paths_keep_status_and_client_but_drop_all_parameters(suffix, query):
    record = _ws_record("/api/ws" + query, suffix)
    if suffix == "%d":
        record.args += (403,)
    expected_suffix = "403" if suffix == "%d" else suffix
    path_filter = WebSocketPathFilter()

    # Le même LogRecord peut traverser plusieurs gestionnaires filtrés.
    for _ in range(2):
        assert path_filter.filter(record) is True
        assert record.getMessage() == f'127.0.0.1:5000 - "WebSocket /api/ws" {expected_suffix}'


@pytest.mark.parametrize("path", [
    f"/api/ws/{SECRET}", f"/api/ws{SECRET}", "/api/ws/", "/api/WS", "/api/%77s", "//api/ws",
    # Cible en forme absolue (`GET http://h/... HTTP/1.1`) : uvicorn écrit un chemin sans `/`.
    f"http%3A//h/api/{SECRET}", "http%3A//h/api/ws", "http://h/api/ws", "api/ws", "",
])
def test_websocket_allowlist_requires_an_exact_path(path):
    record = _ws_record(f"{path}?token={SECRET}", "403")
    assert WebSocketPathFilter().filter(record) is True
    assert record.getMessage() == '127.0.0.1:5000 - "WebSocket <chemin masqué>" 403'


@pytest.mark.parametrize(("message", "args"), [
    ("Serving directory %s", ("/srv/nexus",)),
    ('"WebSocket %s"', ()),
    (object(), ()),
])
def test_unrelated_and_unformatted_log_records_are_not_rewritten(message, args):
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 0, message, args, None)
    original_message = record.getMessage()

    assert WebSocketPathFilter().filter(record) is True

    assert record.msg is message
    assert record.args is args
    assert record.getMessage() == original_message


def test_log_config_protects_every_handler_and_preserves_existing_filters(monkeypatch):
    from uvicorn.config import LOGGING_CONFIG

    handler = copy.deepcopy(LOGGING_CONFIG["handlers"]["default"])
    handler["filters"] = ["existing"]
    monkeypatch.setitem(LOGGING_CONFIG["handlers"], "extra", handler)
    monkeypatch.setitem(LOGGING_CONFIG, "filters", {"existing": {"()": logging.Filter}})

    config = uvicorn_log_config()

    assert config["filters"]["websocket_path"]["()"] is WebSocketPathFilter
    assert config["filters"]["existing"] == {"()": logging.Filter}
    for configured_handler in config["handlers"].values():
        assert configured_handler["filters"].count("websocket_path") == 1
    assert config["filters"]["websocket_secrets"]["()"] is WebSocketSecretFilter
    for configured_handler in config["handlers"].values():
        assert configured_handler["filters"].count("websocket_secrets") == 1
    assert config["handlers"]["extra"]["filters"] == [
        "existing", "websocket_path", "websocket_secrets",
    ]
    assert config["loggers"]["nexus"] == {
        "handlers": ["default"], "level": "INFO", "propagate": False,
    }


def test_log_configs_are_independent_of_uvicorn_defaults_and_each_other():
    from uvicorn.config import LOGGING_CONFIG

    original = copy.deepcopy(LOGGING_CONFIG)
    first = uvicorn_log_config()
    second = uvicorn_log_config()
    assert first == second
    assert LOGGING_CONFIG == original

    first["handlers"]["default"]["filters"].append("extra")
    first["formatters"]["default"]["fmt"] = "changed"
    first["loggers"]["uvicorn"]["handlers"].append("extra")
    first["filters"]["websocket_path"]["()"] = logging.Filter

    assert second == uvicorn_log_config()
    assert LOGGING_CONFIG == original


def test_the_uvicorn_access_logger_has_no_output_even_if_access_log_is_left_on():
    # Défense en profondeur : avec `access_log=True` par erreur, uvicorn.access recopierait
    # l'URL reçue. Sans gestionnaire ni propagation, ses lignes INFO ne sortent nulle part.
    access = uvicorn_log_config()["loggers"]["uvicorn.access"]
    assert access["handlers"] == []
    assert access["propagate"] is False


@pytest.mark.parametrize("method", [SECRET, "get", "PROPFIND", ""])
def test_an_unknown_http_method_is_never_copied_into_the_log(method, http_scope, caplog):
    # Avec le parseur h11, n'importe quel jeton devient `scope["method"]` : un secret aussi.
    caplog.set_level(logging.INFO, logger="nexus.access")
    http_scope["method"] = method

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 405, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(AccessLogMiddleware(app)(http_scope, AsyncMock(), AsyncMock()))

    (line,) = access_lines(caplog)
    assert line.startswith(f"{logs.UNKNOWN_METHOD} ")
    assert SECRET not in line


# --- WebSocket secrets in DEBUG and TRACE records (#57) ---


def _record(msg, *args, name="uvicorn.error", exc_info=None, level=logging.DEBUG):
    return logging.LogRecord(name, level, __file__, 0, msg, args or None, exc_info)


def _ticket():
    return "nxw_" + "A" * 43  # built at runtime


@pytest.mark.parametrize(("fmt", "args"), [
    ("< %s %s %s", ("GET", "/api/ws?history_after=987654321098", "HTTP/1.1")),
    ("< %s: %s", ("Sec-WebSocket-Protocol", "nexus.live.v1, TICKET")),
    ("> %s: %s", ("Sec-WebSocket-Protocol", "TICKET")),
    ("< %s", ("Frame(opcode=TEXT, data=TICKET)",)),
    ("> %s", ("Frame(opcode=TEXT, data=TICKET)",)),
])
def test_websocket_headers_request_line_and_frames_are_masked(fmt, args):
    ticket = _ticket()
    args = tuple(a.replace("TICKET", ticket) for a in args)
    record = _record(fmt, *args)
    assert WebSocketSecretFilter().filter(record) is True
    assert record.args == ("<masqué>",) * len(args)
    message = record.getMessage()
    assert ticket not in message and "987654321098" not in message


@pytest.mark.parametrize(("fmt", "args"), [
    ("> HTTP/1.1 %d %s", (403, "Forbidden")),
    ("> [body] (%d bytes)", (12,)),
])
def test_status_and_body_length_stay_readable(fmt, args):
    record = _record(fmt, *args)
    assert WebSocketSecretFilter().filter(record) is True
    assert record.args == args


@pytest.mark.parametrize("message", [
    "! invalid handshake", "! invalid origin", "! header fields too large",
    "! no valid HTTP request", "! request line too long", "opening handshake failed",
])
def test_handshake_refusals_lose_their_traceback(message):
    ticket = _ticket()
    try:
        raise ValueError(f"invalid Sec-WebSocket-Protocol: nexus.live.v1 {ticket}")
    except ValueError:
        import sys

        record = _record(message, exc_info=sys.exc_info())
    record.exc_text = f"Traceback ... {ticket}"
    record.stack_info = f"stack {ticket}"
    flt = WebSocketSecretFilter()
    assert flt.filter(record) is True
    assert flt.filter(record) is True  # idempotent
    assert record.exc_info is None and record.exc_text is None and record.stack_info is None
    assert record.getMessage() == message + " (détail masqué)"
    formatted = logging.Formatter("%(message)s").format(record)
    assert "Traceback" not in formatted and ticket not in formatted


def test_uvicorn_scope_and_asgi_messages_are_reduced():
    ticket = _ticket()
    scope = {"type": "websocket", "subprotocols": ["nexus.live.v1", ticket],
             "query_string": b"history_after=987654321098"}
    started = _record("%s [%d] Started scope=%s", "ws", 3, scope, name="uvicorn.asgi")
    WebSocketSecretFilter().filter(started)
    assert started.getMessage() == "ws [3] Started scope=<scope masqué>"
    for fmt in ("%s [%d] Receive %s", "%s [%d] Send %s"):
        message = {"type": "websocket.connect", "subprotocol": ticket, "text": "<9 chars>"}
        record = _record(fmt, "ws", 3, message, name="uvicorn.asgi")
        WebSocketSecretFilter().filter(record)
        assert record.args[2] == {"type": "websocket.connect"}
        assert ticket not in record.getMessage()


def test_the_asgi_family_is_only_recognised_on_the_asgi_logger():
    message = {"type": "x", "text": "keep"}
    record = _record("%s [%d] Receive %s", "ws", 3, message, name="uvicorn.error")
    WebSocketSecretFilter().filter(record)
    assert record.args == ("ws", 3, message)


@pytest.mark.parametrize(("fmt", "args"), [
    ("Serving directory %s", ("/srv/nexus",)),
    ("connection open", ()),
    ("= connection is %s", ("OPEN",)),
])
def test_unrelated_records_are_not_touched_by_the_secret_filter(fmt, args):
    record = _record(fmt, *args)
    msg, kept = record.msg, record.args
    assert WebSocketSecretFilter().filter(record) is True
    assert record.msg is msg and record.args == kept
