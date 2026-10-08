"""Contrôle de l'en-tête Host contre le DNS rebinding (#16, ADR-020, D6)."""

import pytest
from conftest import ActorClient, tailscale_json
from starlette.websockets import WebSocketDisconnect

from nexus.app import create_app
from nexus.config import Settings
from nexus.hosts import host_allowed

EVIL = "evil.example"


@pytest.mark.parametrize("host", [
    "localhost", "localhost:5173", "LOCALHOST:8765", "127.0.0.1", "127.0.0.1:8765",
    "[::1]", "[::1]:8765", "[::1]:5173",
])
def test_loopback_hosts_are_admitted_with_any_port(host):
    assert host_allowed(host, frozenset())


@pytest.mark.parametrize("host", [
    "", EVIL, f"{EVIL}:8765", "localhost.evil.example", "127.0.0.1.evil.example",
    "::1", "[::1", "[::1]x", "[::1]:", "[::1]:abc", "[::1]:99999999", "localhost:", "localhost:x",
    "localhost:1:2", "user@localhost", "localhost/path", "localhost evil", "127.0.0.2",
    "[::2]", "[::1]:8765:1", "localhost\n", "locаlhost", "a" * 10_000, "0.0.0.0", "[::ffff:7f00:1]",
])
def test_other_hosts_are_refused(host):
    assert not host_allowed(host, frozenset())


def test_configured_hosts_are_admitted(settings):
    extra = frozenset({"helios.tailnet.ts.net", "100.64.0.1"})
    assert host_allowed("helios.tailnet.ts.net:8765", extra)
    assert host_allowed("HELIOS.tailnet.ts.net", extra)
    assert host_allowed("100.64.0.1", extra)
    assert not host_allowed("other.tailnet.ts.net", extra)


def test_a_missing_host_is_refused():
    assert not host_allowed(None, frozenset())


def test_rest_refuses_a_foreign_host_without_echo(client):
    res = client.get("/api/health", headers={"Host": f"{EVIL}:8765"})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "invalid_host"
    assert EVIL not in res.text


def test_a_foreign_host_is_refused_before_authentication(anonymous):
    res = anonymous.get("/api/tasks", headers={"Host": EVIL})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "invalid_host"


@pytest.mark.parametrize("host", ["localhost:5173", "[::1]:8765", "127.0.0.1:8765"])
def test_rest_admits_loopback_hosts(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_the_default_test_host_is_loopback(client):
    assert client.base_url.host == "127.0.0.1"
    assert client.get("/api/health").status_code == 200


def test_testserver_is_refused(settings):
    with ActorClient(
        create_app(settings, nodes_runner=tailscale_json), base_url="http://testserver"
    ) as c:
        assert c.get("/api/health").status_code == 400


def test_websocket_refuses_a_foreign_host(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws", headers={"host": EVIL}):
            pass


def test_websocket_admits_loopback_hosts(client):
    with client.websocket_connect("/api/ws", headers={"host": "[::1]:8765"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_configured_host_is_admitted_end_to_end(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "d", allowed_hosts=frozenset({"helios.tailnet.ts.net"})
    )
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as c:
        ok = c.get("/api/health", headers={"Host": "helios.tailnet.ts.net:8765"})
        assert ok.status_code == 200
        assert c.get("/api/health", headers={"Host": EVIL}).status_code == 400


def test_a_configured_ipv6_host_is_matched_in_its_compressed_form(tmp_path):
    settings = Settings(data_dir=tmp_path / "d", allowed_hosts=frozenset({"fd7a:0:0::1"}))
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as c:
        ok = c.get("/api/health", headers={"Host": "[fd7a::1]:8765"})
        assert ok.status_code == 200


async def _drive(scope_type, headers):
    """Drives HostCheckMiddleware directly: the test client cannot send two Host headers."""
    from nexus.hosts import HostCheckMiddleware

    reached, sent = [], []

    async def app(scope, receive, send):
        reached.append(True)

    async def receive():
        return {"type": f"{scope_type}.connect" if scope_type == "websocket"
                else "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    scope = {"type": scope_type, "headers": headers, "path": "/api/health"}
    await HostCheckMiddleware(app)(scope, receive, send)
    return reached, sent


def _asgi(scope_type, headers):
    import asyncio

    return asyncio.run(_drive(scope_type, headers))


def test_two_host_headers_are_refused_over_http():
    reached, sent = _asgi("http", [(b"host", b"localhost"), (b"host", b"localhost")])
    assert not reached and sent[0]["status"] == 400
    assert b"invalid_host" in sent[1]["body"]


def test_two_host_headers_are_refused_over_websocket():
    reached, sent = _asgi("websocket", [(b"host", b"localhost"), (b"host", b"evil.example")])
    assert not reached and sent == [{"type": "websocket.close", "code": 1008}]


def test_a_single_host_header_still_passes():
    reached, _ = _asgi("http", [(b"host", b"localhost:5173")])
    assert reached
