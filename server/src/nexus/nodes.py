"""Adaptateur `nodes` : état réel des nœuds, en lecture seule via Tailscale (INTEGRATIONS §10).

Aucune mutation, aucune connexion SSH : on lit `tailscale status --json` auprès du démon local.
Ce qui ne se vérifie pas reste `unknown` (ADR-005) ; Artémis éteint est `offline-by-design`,
jamais « en panne » (ADR-008).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime

from nexus.clock import TZ, now

log = logging.getLogger("nexus.nodes")

SOURCE = "tailscale"
TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class NodeSpec:
    id: str
    kind: str
    guardian_agent: str
    tailscale_host: str
    offline_by_design: bool = False


# DATA-MODEL §2.1. Helios is the local machine (Self in Tailscale).
# Order of importance: it fixes the floor of each node on the Now view (4 racks per floor).
NODES: tuple[NodeSpec, ...] = (
    NodeSpec("cortex", "homelab", "mnema", "cortex"),
    NodeSpec("synapse", "homelab", "aether", "synapse"),
    NodeSpec("artemis", "content-factory", "artemis", "artemis", offline_by_design=True),
    NodeSpec("helios", "workstation", "helios", "helios"),
)


@dataclass
class NodeState:
    id: str
    kind: str
    guardian_agent: str
    status: str  # online | offline | offline-by-design | unknown
    last_seen: str | None
    detail: str | None
    source: str
    measured_at: str

    def to_dict(self) -> dict:
        return asdict(self)


Runner = Callable[[], str]


def run_tailscale(binary: str = "tailscale") -> str:
    """`tailscale status --json`, sans ouvrir de fenêtre de console sous Windows."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run(
        [binary, "status", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        check=True,
        creationflags=flags,
    )
    return result.stdout


def probe(runner: Runner) -> list[NodeState]:
    measured_at = now().isoformat()
    try:
        status = json.loads(runner())
    except FileNotFoundError:
        return _all_unknown("Tailscale n'est pas installé sur ce poste", measured_at)
    except subprocess.TimeoutExpired:
        return _all_unknown("Tailscale ne répond pas", measured_at)
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        log.warning("lecture Tailscale impossible : %s", exc)
        return _all_unknown("lecture de Tailscale impossible", measured_at)

    try:
        return _read(status, measured_at)
    except (AttributeError, TypeError) as exc:  # JSON valide mais de forme inattendue
        log.warning("réponse Tailscale inattendue : %s", exc)
        return _all_unknown("réponse de Tailscale inattendue", measured_at)


def pending_snapshot() -> list[NodeState]:
    """État servi avant la première lecture : honnête et immédiat, jamais bloquant."""
    return _all_unknown("première lecture de Tailscale en cours", now().isoformat())


def _read(status: dict, measured_at: str) -> list[NodeState]:
    if status.get("BackendState") != "Running":
        return _all_unknown(
            f"Tailscale n'est pas connecté (état : {status.get('BackendState', 'inconnu')})",
            measured_at,
        )
    self_node = status.get("Self") or {}
    self_host = (self_node.get("HostName") or "").lower()
    peers = {
        (p.get("HostName") or "").lower(): p for p in (status.get("Peer") or {}).values()
    }
    states = []
    for spec in NODES:
        peer = self_node if spec.tailscale_host == self_host else peers.get(spec.tailscale_host)
        states.append(_state(spec, peer, measured_at))
    return states


def _state(spec: NodeSpec, peer: dict | None, measured_at: str) -> NodeState:
    base = {"id": spec.id, "kind": spec.kind, "guardian_agent": spec.guardian_agent,
            "source": SOURCE, "measured_at": measured_at}
    if peer is None:
        return NodeState(**base, status="unknown", last_seen=None,
                         detail="absent du réseau Tailscale")
    last_seen = _last_seen(peer.get("LastSeen"))
    online = peer.get("Online")
    if not isinstance(online, bool):  # absent ou illisible : rien ne se déduit (ADR-005)
        return NodeState(**base, status="unknown", last_seen=last_seen,
                         detail="état en ligne non fourni par Tailscale")
    if online:
        return NodeState(**base, status="online", last_seen=None, detail=None)
    if spec.offline_by_design:
        return NodeState(**base, status="offline-by-design", last_seen=last_seen,
                         detail="éteint volontairement")
    return NodeState(**base, status="offline", last_seen=last_seen, detail=None)


def _last_seen(value: str | None) -> str | None:
    """Tailscale met une date nulle (an 1) pour un pair en ligne : ce n'est pas une donnée."""
    if not value or value.startswith("0001-"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ).isoformat()
    except ValueError:
        return None


def _all_unknown(detail: str, measured_at: str) -> list[NodeState]:
    return [
        NodeState(id=s.id, kind=s.kind, guardian_agent=s.guardian_agent, status="unknown",
                  last_seen=None, detail=detail, source=SOURCE, measured_at=measured_at)
        for s in NODES
    ]
