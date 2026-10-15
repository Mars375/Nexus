import ipaddress
import json
import subprocess
from datetime import datetime

import pytest
from conftest import ActorClient, tailscale_json

from nexus import nodes
from nexus.app import create_app


def by_id(states):
    return {s.id: s for s in states}


def test_reads_the_four_nodes_with_provenance():
    states = nodes.probe(tailscale_json)

    assert [s.id for s in states] == ["cortex", "synapse", "artemis", "helios"]
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


@pytest.mark.parametrize("value", ["missing", "false", 1, None])
def test_unreadable_online_field_is_unknown(value):
    status = json.loads(tailscale_json())
    if value == "missing":
        del status["Peer"]["k3"]["Online"]
    else:
        status["Peer"]["k3"]["Online"] = value
    artemis = by_id(nodes.probe(lambda: json.dumps(status)))["artemis"]

    assert artemis.status == "unknown"
    assert artemis.detail == "état en ligne non fourni par Tailscale"


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
    import gc
    import threading
    import time

    release = threading.Event()

    def hanging():
        release.wait(10)
        return tailscale_json()

    with ActorClient(create_app(settings, nodes_runner=hanging)) as client:
        # Late in the full suite the heap is large: a generation-2 collection takes about 0.5 s
        # and, when it lands inside the timed request, fails the test without the API being slow.
        gc.collect()
        gc.disable()
        try:
            started = time.monotonic()
            body = client.get("/api/nodes").json()
            elapsed = time.monotonic() - started
        finally:
            gc.enable()
            release.set()  # avant l'arrêt de l'app, qui attend la lecture en cours

    assert elapsed < 0.5
    assert {n["status"] for n in body} == {"unknown"}
    assert {n["detail"] for n in body} == {"première lecture de Tailscale en cours"}


def test_api_returns_the_four_nodes(client):
    body = client.get("/api/nodes").json()

    assert [n["id"] for n in body] == ["cortex", "synapse", "artemis", "helios"]
    assert body[2]["status"] == "offline-by-design"
    assert all(n["source"] == "tailscale" and n["measured_at"] for n in body)


def test_nodes_order_is_importance_order():
    # The UI keeps the received order: it fixes the floor of each node (#36).
    assert [spec.id for spec in nodes.NODES] == ["cortex", "synapse", "artemis", "helios"]
    assert [s.id for s in nodes.pending_snapshot()] == [spec.id for spec in nodes.NODES]


def test_api_survives_tailscale_being_absent(settings):
    app = create_app(settings, nodes_runner=_raise(FileNotFoundError()))
    with ActorClient(app) as client:
        res = client.get("/api/nodes")

    assert res.status_code == 200
    assert {n["status"] for n in res.json()} == {"unknown"}


def test_unexpected_exception_in_first_read_is_logged(settings, caplog):
    """Une exception inattendue lors de la première lecture doit être loguée."""
    def boom():
        raise RuntimeError("boom")

    with ActorClient(create_app(settings, nodes_runner=boom)) as client:
        res = client.get("/api/nodes")

    # L'API répond 200 même si la première lecture a échoué
    assert res.status_code == 200
    assert {n["status"] for n in res.json()} == {"unknown"}
    # L'erreur est loguée
    assert any(
        "première lecture de l'état des nœuds échouée" in record.message
        and record.levelname == "ERROR"
        for record in caplog.records
    )


def test_run_tailscale_self_asks_for_this_node_only(monkeypatch):
    calls = []

    def fake(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake)
    assert nodes.run_tailscale_self("ts-bin") == "{}"
    nodes.run_tailscale("ts-bin")
    (argv, kwargs), (_, status_kwargs) = calls
    assert argv == ["ts-bin", "status", "--json", "--peers=false"]
    assert kwargs["timeout"] == nodes.TIMEOUT_SECONDS
    assert kwargs["check"] is True and kwargs["capture_output"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["creationflags"] == status_kwargs["creationflags"]


ADDRESS = ipaddress.ip_address("100.101.102.103")
ADDRESS6 = ipaddress.ip_address("fd7a:115c:a1e0::1")


def _status(state="Running", ips=("100.101.102.103", "fd7a:115c:a1e0::1")):
    return json.dumps({"BackendState": state, "TailscaleIPs": list(ips)})


@pytest.mark.parametrize("output,address,reason", [
    (_status(), ADDRESS, None),
    (_status(), ADDRESS6, None),
    (_status(ips=("fd7a:115c:a1e0:0:0:0:0:1",)), ADDRESS6, None),
    (_status("Stopped"), ADDRESS, nodes.NOT_CONNECTED),
    (_status("NeedsLogin"), ADDRESS, nodes.NOT_CONNECTED),
    (_status("Starting"), ADDRESS, nodes.NOT_CONNECTED),
    (_status("NoState"), ADDRESS, nodes.NOT_CONNECTED),
    (json.dumps({"TailscaleIPs": ["100.101.102.103"]}), ADDRESS, nodes.NOT_CONNECTED),
    (_status(ips=("100.101.102.104",)), ADDRESS, nodes.ABSENT),
    (_status(ips=()), ADDRESS, nodes.ABSENT),
    (json.dumps({"BackendState": "Running", "TailscaleIPs": None}), ADDRESS, nodes.ABSENT),
    (json.dumps({"BackendState": "Running"}), ADDRESS, nodes.ABSENT),
    (json.dumps({"BackendState": "Running", "Self": {"TailscaleIPs": ["100.101.102.103"]}}),
     ADDRESS, nodes.ABSENT),
    (_status(ips=("x",)), ADDRESS, nodes.UNEXPECTED),
    (_status(ips=(42,)), ADDRESS, nodes.UNEXPECTED),
    (json.dumps({"BackendState": "Running", "TailscaleIPs": "100.101.102.103"}),
     ADDRESS, nodes.UNEXPECTED),
    (json.dumps([]), ADDRESS, nodes.UNEXPECTED),
    (json.dumps("s"), ADDRESS, nodes.UNEXPECTED),
    ("not json 100.101.102.103", ADDRESS, nodes.UNEXPECTED),
])
def test_tailnet_address_reason(output, address, reason):
    assert nodes.tailnet_address_reason(output, address) == reason
