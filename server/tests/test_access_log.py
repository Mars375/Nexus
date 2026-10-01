"""Journal des requêtes (#25, ADR-006) : jamais une valeur reçue, seulement le gabarit de route."""

import logging

from nexus.logs import WebSocketPathFilter, uvicorn_log_config

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

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.append(kw))
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    nexus.main()
    nexus.dev()
    assert len(calls) == 2
    for kw in calls:
        assert kw["access_log"] is False
        assert "websocket_path" in kw["log_config"]["filters"]


def test_uvicorn_runs_without_its_access_log_and_with_ours():
    config = uvicorn_log_config()
    assert config["loggers"]["nexus"]["level"] == "INFO"
    assert "nexus" in config["loggers"] and config["loggers"]["nexus"]["handlers"]
    assert any(
        f == "websocket_path" for f in config["handlers"]["default"].get("filters", [])
    )
