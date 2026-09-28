import json

import pytest
from fastapi.testclient import TestClient

from nexus.app import create_app
from nexus.config import Settings


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
    with TestClient(create_app(settings, nodes_runner=tailscale_json)) as client:
        yield client
