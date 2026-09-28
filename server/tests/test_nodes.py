import json
import subprocess
from datetime import datetime

import pytest
from conftest import tailscale_json
from fastapi.testclient import TestClient

from nexus import nodes
from nexus.app import create_app


def by_id(states):
    return {s.id: s for s in states}


def test_reads_the_four_nodes_with_provenance():
    states = nodes.probe(tailscale_json)

    assert [s.id for s in states] == ["helios", "cortex", "synapse", "artemis"]
    for s in states:
        assert s.source == "tailscale"
        assert datetime.fromisoformat(s.measured_at).tzinfo is not None


def test_online_nodes_and_self():
    states = by_id(nodes.probe(tailscale_json))

    assert states["helios"].status == "online"
    assert states["cortex"].status == "online"
    assert states["synapse"].status == "online"
    assert states["cortex"].last_seen is None  # date « an 1 » de Tailscale : pas une donnée


def test_artemis_off_is_offline_by_design_never_down():
    artemis = by_id(nodes.probe(tailscale_json))["artemis"]

    assert artemis.status == "offline-by-design"
    assert artemis.detail == "éteint volontairement"
    assert artemis.last_seen == "2026-09-25T22:58:37.100000+02:00"


def test_artemis_on_is_online():
    status = json.loads(tailscale_json())
    status["Peer"]["k3"]["Online"] = True
    artemis = by_id(nodes.probe(lambda: json.dumps(status)))["artemis"]

    assert artemis.status == "online"


def test_other_node_off_is_offline():
    status = json.loads(tailscale_json())
    status["Peer"]["k2"]["Online"] = False
    status["Peer"]["k2"]["LastSeen"] = "2026-09-28T08:00:00Z"
    cortex = by_id(nodes.probe(lambda: json.dumps(status)))["cortex"]

    assert cortex.status == "offline"
    assert cortex.last_seen == "2026-09-28T10:00:00+02:00"


def test_missing_peer_is_unknown():
    status = json.loads(tailscale_json())
    del status["Peer"]["k1"]
    synapse = by_id(nodes.probe(lambda: json.dumps(status)))["synapse"]

    assert synapse.status == "unknown"
    assert synapse.detail == "absent du réseau Tailscale"


def _raise(exc):
    def runner():
        raise exc

    return runner


@pytest.mark.parametrize(
    ("runner", "detail"),
    [
        (_raise(FileNotFoundError()), "Tailscale n'est pas installé sur ce poste"),
        (_raise(subprocess.TimeoutExpired("tailscale", 5)), "Tailscale ne répond pas"),
        (_raise(subprocess.CalledProcessError(1, "tailscale")), "lecture de Tailscale impossible"),
        (lambda: "pas du json", "lecture de Tailscale impossible"),
        (lambda: tailscale_json(BackendState="Stopped"), "Tailscale n'est pas connecté"),
    ],
)
def test_tailscale_unavailable_makes_every_node_unknown(runner, detail):
    states = nodes.probe(runner)

    assert {s.status for s in states} == {"unknown"}
    assert all(s.detail.startswith(detail) for s in states)


@pytest.mark.parametrize("payload", ["null", "[]", '"texte"', '{"BackendState": "Running", '
                                     '"Peer": [1]}', '{"BackendState": "Running", "Self": 3}'])
def test_unexpected_json_shape_makes_every_node_unknown(payload):
    states = nodes.probe(lambda: payload)

    assert {s.status for s in states} == {"unknown"}
    assert {s.detail for s in states} == {"réponse de Tailscale inattendue"}


def test_hanging_tailscale_does_not_block_the_api(settings):
    import threading
    import time

    release = threading.Event()

    def hanging():
        release.wait(10)
        return tailscale_json()

    with TestClient(create_app(settings, nodes_runner=hanging)) as client:
        try:
            started = time.monotonic()
            body = client.get("/api/nodes").json()
            elapsed = time.monotonic() - started
        finally:
            release.set()  # avant l'arrêt de l'app, qui attend la lecture en cours

    assert elapsed < 0.5
    assert {n["status"] for n in body} == {"unknown"}
    assert {n["detail"] for n in body} == {"première lecture de Tailscale en cours"}


def test_api_returns_the_four_nodes(client):
    body = client.get("/api/nodes").json()

    assert [n["id"] for n in body] == ["helios", "cortex", "synapse", "artemis"]
    assert body[3]["status"] == "offline-by-design"
    assert all(n["source"] == "tailscale" and n["measured_at"] for n in body)


def test_api_survives_tailscale_being_absent(settings):
    app = create_app(settings, nodes_runner=_raise(FileNotFoundError()))
    with TestClient(app) as client:
        res = client.get("/api/nodes")

    assert res.status_code == 200
    assert {n["status"] for n in res.json()} == {"unknown"}
