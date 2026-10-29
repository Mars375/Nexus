import base64
import http.client
import json
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from nexus.actors import ACTORS
from nexus.app import create_app
from nexus.auth import tokens
from nexus.clock import now
from nexus.config import Settings
from nexus.live import LIVE_PROTOCOL

LOCAL_URL = "http://127.0.0.1"  # TestClient sends Host `testserver` by default: refused (D6)


def ago(seconds: float) -> datetime:
    """An instant `seconds` before now, computed on the UTC timeline.

    Wall-clock subtraction in Europe/Paris is not a real duration across a DST change: on the
    spring one it lands in an hour that does not exist (read back with `fold=0`, it can be in the
    future) and on the autumn one it re-reads the repeated hour an hour off. Tests that fix the
    clock freeze this module's `now`, not their own (#128, #132).
    """
    return now().astimezone(UTC) - timedelta(seconds=seconds)


def seconds_since(stamp: datetime) -> float:
    """The absolute distance in seconds between `stamp` and now, on the UTC timeline.

    `stamp - now()` on two values of the same zone compares by wall clock and ignores `fold`:
    across a DST change it is off by an hour (#132). Same `now` as `ago`.
    """
    return abs((stamp.astimezone(UTC) - now().astimezone(UTC)).total_seconds())


class ActorClient(TestClient):
    """TestClient on the loopback that signs each request with the token of its actor.

    The actor is read from the request itself (`Authorization` already set: untouched,
    `X-Nexus-Actor`, the `actor` of a JSON body, else `loic`), so existing scenarios keep
    their meaning. `authenticate=False` sends nothing: the anonymous caller.
    """

    def __init__(self, app, *, authenticate: bool = True, **kwargs):
        kwargs.setdefault("base_url", LOCAL_URL)
        super().__init__(app, **kwargs)
        self._authenticate = authenticate
        self._issued: dict[str, str] = {}

    def token_for(self, actor: str) -> str:
        if actor not in self._issued:
            with self.app.state.sessionmaker() as session:
                _, token = tokens.issue(session, actor, "test")
                session.commit()
            # Published only once committed (#138): another thread may already be using it, and
            # an uncommitted row is invisible to its connection, i.e. a 401 `invalid_token` for a
            # valid token before the request even reaches the test's race barrier.
            self._issued[actor] = token
        return self._issued[actor]

    def headers_for(self, actor: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token_for(actor)}"}

    def websocket_connect(self, url, *args, **kwargs):
        # Starlette joins a relative URL to `ws://testserver`: refused by the Host check (D6).
        if url.startswith("/"):
            url = "ws://127.0.0.1" + url
        return super().websocket_connect(url, *args, **kwargs)

    def request(self, method, url, **kwargs):
        if self._authenticate:
            headers = dict(kwargs.get("headers") or {})
            if not any(str(name).lower() == "authorization" for name in headers):
                body = kwargs.get("json")
                if body is None and kwargs.get("content"):
                    try:
                        body = json.loads(kwargs["content"])
                    except ValueError:
                        body = None
                candidates = (headers.get("X-Nexus-Actor"), body.get("actor") if isinstance(
                    body, dict) else None)
                # An unknown name is not an identity: sign as loic, so that the server's
                # `actor_mismatch` (or its 422 for a non-text actor) is what gets exercised.
                actor = next(
                    (c for c in candidates if isinstance(c, str) and c in ACTORS), "loic"
                )
                headers |= self.headers_for(actor)
                kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


def ws_connect(client, url="/api/ws", *, actor="loic", **kwargs):
    """Open the live WebSocket the way the UI does: a fresh ticket, offered as a subprotocol."""
    res = client.post("/api/ws-ticket", headers=client.headers_for(actor))
    assert res.status_code == 200, res.status_code
    ticket = res.json()["ticket"]
    return client.websocket_connect(url, subprotocols=[LIVE_PROTOCOL, ticket], **kwargs)


def serve_real(app, **config):
    """Run a real uvicorn server on a free loopback port; returns (server, thread, port).

    `log_config` defaults to None so the session's logging stays untouched; `log_level` and any
    other `uvicorn.Config` option can be passed.
    """
    import uvicorn

    options = {"host": "127.0.0.1", "port": 0, "log_config": None, "access_log": False}
    options.update(config)
    server = uvicorn.Server(uvicorn.Config(app, **options))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            stop_real(server, thread)
            raise AssertionError("uvicorn did not start")
        time.sleep(0.02)
    return server, thread, server.servers[0].sockets[0].getsockname()[1]


def stop_real(server, thread):
    server.should_exit = True
    thread.join(timeout=10)
    assert not thread.is_alive(), "uvicorn did not stop"


def raw_handshake(port, host, protocols=None, origin="http://localhost:5173", path="/api/ws"):
    """A hand-written WebSocket handshake; returns the whole first answer (headers and body).

    `protocols` is the raw `Sec-WebSocket-Protocol` value, sent as is.
    """
    key = base64.b64encode(os.urandom(16)).decode()  # a fresh nonce, as a real client sends
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
        f"Origin: {origin}",
    ]
    if protocols is not None:
        lines.append(f"Sec-WebSocket-Protocol: {protocols}")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        chunks = []
        try:
            while chunk := sock.recv(4096):
                chunks.append(chunk)
                if len(chunk) < 4096:
                    break
        except TimeoutError:
            pass
        return b"".join(chunks).decode("latin-1")


def issue_ticket_http(port, token):
    """Ask a real server for a ticket over HTTP, as the UI does."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", "/api/ws-ticket", headers={"Authorization": f"Bearer {token}"})
        res = conn.getresponse()
        assert res.status == 200, res.status
        return json.loads(res.read())["ticket"]
    finally:
        conn.close()


def issue_token(app, actor="loic"):
    """A fresh actor token in the app's database."""
    with app.state.sessionmaker() as session:
        _, token = tokens.issue(session, actor, "test")
        session.commit()
    return token


def tailscale_json(**overrides) -> str:
    """Sortie factice de `tailscale status --json`, calquée sur le vrai réseau (sans clés)."""
    status = {
        "BackendState": "Running",
        "Self": {"HostName": "Helios", "Online": True, "LastSeen": "0001-01-01T00:00:00Z"},
        "Peer": {
            "k1": {"HostName": "synapse", "Online": True, "LastSeen": "0001-01-01T00:00:00Z"},
            "k2": {"HostName": "cortex", "Online": True, "LastSeen": "0001-01-01T00:00:00Z"},
            "k3": {"HostName": "Artemis", "Online": False, "LastSeen": "2026-09-25T20:58:37.1Z"},
            "k4": {"HostName": "The Fairphone (Gen", "Online": True},
        },
    }
    status.update(overrides)
    return json.dumps(status)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings):
    # Jamais le vrai Tailscale dans les tests : sortie factice et déterministe.
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as client:
        yield client


@pytest.fixture
def anonymous(settings):
    """Un appelant sans jeton, sur la boucle locale."""
    with ActorClient(
        create_app(settings, nodes_runner=tailscale_json), authenticate=False
    ) as client:
        yield client
