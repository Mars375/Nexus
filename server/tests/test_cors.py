"""REST CORS for the Tauri WebView origin (#47)."""

import pytest
from conftest import ActorClient, tailscale_json, ws_connect
from starlette.websockets import WebSocketDisconnect

from nexus.app import create_app
from nexus.config import Settings

ORIGIN = "http://tauri.localhost"
EVIL = "https://evil.example"


def client_for(tmp_path, *, origins=frozenset({ORIGIN}), authenticate=True):
    settings = Settings(data_dir=tmp_path / "data", allowed_origins=frozenset(origins))
    return ActorClient(create_app(settings, nodes_runner=tailscale_json), authenticate=authenticate)


def preflight(
    client,
    *,
    origin=ORIGIN,
    method="POST",
    headers="authorization, content-type",
    **extra,
):
    request_headers = {
        "Origin": origin,
        "Access-Control-Request-Method": method,
    }
    if headers is not None:
        request_headers["Access-Control-Request-Headers"] = headers
    request_headers.update(extra)
    return client.options("/api/tasks", headers=request_headers)


def test_a_listed_origin_is_allowed_on_a_get(tmp_path):
    with client_for(tmp_path) as client:
        res = client.get("/api/health", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == ORIGIN
    assert res.headers.get("access-control-allow-origin") != "*"
    assert res.headers.get("access-control-allow-credentials") is None
    assert "origin" in res.headers.get("vary", "").lower()


def test_a_listed_origin_is_allowed_on_a_json_post(tmp_path):
    with client_for(tmp_path) as client:
        res = client.post(
            "/api/tasks",
            json={"title": "T", "objective": "O"},
            headers={"Origin": ORIGIN},
        )
    assert res.status_code == 201
    assert res.headers.get("access-control-allow-origin") == ORIGIN


def test_a_preflight_from_a_listed_origin_is_allowed(tmp_path):
    with client_for(tmp_path, authenticate=False) as client:
        res = preflight(client)
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == ORIGIN
    assert "POST" in res.headers["access-control-allow-methods"]
    allowed_headers = res.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers
    assert res.headers.get("access-control-max-age") == "600"
    assert res.headers.get("access-control-allow-credentials") is None


def test_a_private_network_preflight_is_allowed(tmp_path):
    with client_for(tmp_path, authenticate=False) as client:
        res = preflight(client, **{"Access-Control-Request-Private-Network": "true"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-private-network") == "true"


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "PUT", "DELETE"])
def test_every_method_the_ui_uses_passes_the_preflight(tmp_path, method):
    with client_for(tmp_path, authenticate=False) as client:
        res = preflight(client, method=method)
    assert res.status_code == 200
    assert method in res.headers["access-control-allow-methods"]


def test_a_preflight_for_an_unlisted_method_is_refused(tmp_path):
    with client_for(tmp_path, authenticate=False) as client:
        res = preflight(client, method="TRACE")
    assert res.status_code == 400
    assert "Disallowed CORS method" in res.text
    assert ORIGIN not in res.text


def test_a_preflight_for_an_unlisted_header_is_refused(tmp_path):
    with client_for(tmp_path, authenticate=False) as client:
        res = preflight(client, headers="x-evil")
    assert res.status_code == 400
    assert "Disallowed CORS headers" in res.text
    assert "x-evil" not in res.text.lower()


def test_an_unlisted_origin_is_not_readable_on_a_get(tmp_path):
    with client_for(tmp_path) as client:
        res = client.get("/api/health", headers={"Origin": EVIL})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") is None
    assert EVIL not in res.text


def test_a_preflight_from_an_unlisted_origin_is_refused_without_echo(tmp_path):
    with client_for(tmp_path, authenticate=False) as client:
        res = preflight(client, origin=EVIL)
    assert res.status_code == 400
    assert res.headers.get("access-control-allow-origin") is None
    assert EVIL not in res.text


def test_a_configured_origin_is_matched_exactly(tmp_path):
    with client_for(tmp_path, origins=frozenset({"tauri://localhost"})) as client:
        for origin in ("TAURI://localhost", "tauri://localhost.evil", "tauri://localhost/"):
            res = client.get("/api/health", headers={"Origin": origin})
            assert res.headers.get("access-control-allow-origin") is None
            assert origin not in res.text


def test_a_request_without_origin_is_untouched(tmp_path):
    with client_for(tmp_path) as client:
        res = client.get("/api/health")
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") is None


def test_the_host_check_runs_before_cors_on_a_preflight(tmp_path):
    with client_for(tmp_path, authenticate=False) as client:
        res = preflight(client, Host="evil.example")
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "invalid_host"
    assert res.headers.get("access-control-allow-origin") is None
    assert "evil.example" not in res.text


def test_rest_and_websocket_share_the_configured_list(tmp_path):
    with client_for(tmp_path, origins=frozenset({ORIGIN})) as client:
        res = client.get("/api/health", headers={"Origin": ORIGIN})
        assert res.headers.get("access-control-allow-origin") == ORIGIN
        with ws_connect(client, headers={"origin": ORIGIN}) as ws:
            assert ws.receive_json()["type"] == "hello"
        with pytest.raises(WebSocketDisconnect) as closed:
            with ws_connect(client, headers={"origin": EVIL}):
                pass
        assert closed.value.code == 1008


def test_an_allowed_origin_can_read_a_401(tmp_path):
    with client_for(tmp_path, authenticate=False) as client:
        res = client.post(
            "/api/tasks",
            json={"title": "T", "objective": "O"},
            headers={"Origin": ORIGIN},
        )
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") == ORIGIN


def test_a_disallowed_origin_is_not_an_http_403(tmp_path):
    """CORS is a browser read barrier, not access control: the token remains the boundary."""
    with client_for(tmp_path) as client:
        res = client.post(
            "/api/tasks",
            json={"title": "T", "objective": "O"},
            headers={"Origin": EVIL},
        )
    assert res.status_code == 201
    assert res.headers.get("access-control-allow-origin") is None
