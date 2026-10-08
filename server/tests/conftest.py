import json

import pytest
from fastapi.testclient import TestClient

from nexus.actors import ACTORS
from nexus.app import create_app
from nexus.auth import tokens
from nexus.config import Settings

LOCAL_URL = "http://127.0.0.1"  # TestClient sends Host `testserver` by default: refused (D6)


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
                _, self._issued[actor] = tokens.issue(session, actor, "test")
                session.commit()
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
