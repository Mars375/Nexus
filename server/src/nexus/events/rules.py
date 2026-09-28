"""Règles du protocole d'événements (EVENT-PROTOCOL §3, §4, §7) — logique pure.

Un événement valide est un fait actionnable : il nomme son destinataire quand il demande
quelque chose, dit sa cause quand il bloque ou échoue, et prouve ce qu'il déclare terminé.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from nexus.actors import ACTORS, HUMANS
from nexus.secrets import is_blank
from nexus.tasks.rules import RuleViolation

KINDS = (
    "claimed", "working", "progress", "question", "blocked", "needs_human", "handoff",
    "review", "done", "failed", "unknown",
)

# Ces événements parlent d'une tâche précise.
TASK_REQUIRED = frozenset(
    {"claimed", "working", "progress", "blocked", "handoff", "review", "done", "failed"}
)


@dataclass
class Envelope:
    actor: str
    kind: str
    subject: str
    task: str | None = None
    run: str | None = None
    body: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)


def _text(value: Any) -> str | None:
    """Texte utilisable, ou None (vide, ou réduit à des secrets masqués)."""
    return value.strip() if isinstance(value, str) and not is_blank(value) else None


def _instant(value: Any, name: str) -> datetime:
    try:
        instant = datetime.fromisoformat(str(value))
    except ValueError:
        instant = None
    if instant is None or instant.tzinfo is None:
        raise RuleViolation("invalid_instant", f"{name} doit être un instant ISO-8601 avec fuseau")
    return instant


def proofs(e: Envelope) -> list[str]:
    """Preuves utilisables : une preuve vide ou masquée (secret collé) ne prouve rien."""
    return [ref for ref in e.evidence if not is_blank(ref)]


def cause_of(e: Envelope) -> str | None:
    return _text(e.payload.get("cause")) or _text(e.body)


def validate(e: Envelope) -> str:
    """Vérifie l'événement et renvoie son type effectif (un `done` sans preuve devient `review`)."""
    if e.kind not in KINDS:
        raise RuleViolation("unknown_kind", f"type d'événement inconnu : {e.kind}")
    if e.kind in TASK_REQUIRED and not e.task:
        raise RuleViolation("task_required", f"un événement {e.kind} doit viser une tâche")
    run_ref = e.payload.get("run_ref")
    if run_ref is not None and not (isinstance(run_ref, str) and 0 < len(run_ref.strip()) <= 128):
        raise RuleViolation(
            "invalid_run_ref", "payload.run_ref doit être un texte de 128 caractères au plus"
        )
    unknown_needs = sorted(set(e.needs) - ACTORS)
    if unknown_needs:
        raise RuleViolation("unknown_recipient", f"destinataires inconnus : {unknown_needs}")

    match e.kind:
        case "working":
            if not (_text(e.payload.get("run_ref")) or _text(e.run)):
                raise RuleViolation(
                    "run_ref_required", "working doit donner la référence du run (payload.run_ref)"
                )
        case "progress":
            percent = e.payload.get("percent")
            if percent is not None and not (
                isinstance(percent, int | float) and 0 <= percent <= 100
            ):
                raise RuleViolation("invalid_percent", "payload.percent doit être entre 0 et 100")
            if percent is None and not _text(e.body):
                raise RuleViolation(
                    "progress_empty", "progress doit donner un pourcentage ou décrire l'avancée"
                )
        case "question" | "needs_human" | "handoff":
            if not e.needs:
                raise RuleViolation(
                    "recipient_required", f"{e.kind} doit nommer son destinataire (needs)"
                )
    match e.kind:
        case "needs_human":
            if not set(e.needs) & HUMANS:
                raise RuleViolation(
                    "human_required", "needs_human doit s'adresser à un humain (ex. loic)"
                )
            options = e.payload.get("options")
            if not (isinstance(options, list) and any(_text(o) for o in options)):
                raise RuleViolation(
                    "options_required", "needs_human doit proposer les options (payload.options)"
                )
        case "handoff":
            if len(set(e.needs)) != 1:
                raise RuleViolation(
                    "single_recipient_required",
                    "un handoff transmet la responsabilité à un seul acteur (needs)",
                )
            if e.actor in e.needs:
                raise RuleViolation("handoff_to_self", "un handoff se fait vers un autre acteur")
            if not _text(e.payload.get("next_action")):
                raise RuleViolation(
                    "next_action_required",
                    "handoff doit dire la prochaine action (payload.next_action)",
                )
        case "blocked":
            if not cause_of(e):
                raise RuleViolation("block_cause_required", "blocked doit donner sa cause")
            follow_up = e.payload.get("follow_up_at")
            if follow_up is not None:
                _instant(follow_up, "payload.follow_up_at")
            if follow_up is None and not _text(e.payload.get("plan")):
                raise RuleViolation(
                    "block_follow_up_required",
                    "blocked doit prévoir une relance (payload.follow_up_at) "
                    "ou dire ce qui débloquerait (payload.plan)",
                )
        case "review":
            if not proofs(e):
                raise RuleViolation("evidence_required", "review doit pointer la preuve à examiner")
        case "failed":
            if not cause_of(e):
                raise RuleViolation("failure_cause_required", "failed doit donner la cause")
        case "unknown":
            last = e.payload.get("last_check_at")
            if last is None:
                raise RuleViolation(
                    "last_check_required",
                    "unknown doit dire quand a eu lieu le dernier contrôle (payload.last_check_at)",
                )
            _instant(last, "payload.last_check_at")
        case "done":
            if not proofs(e):
                return "review"  # preuve ou review (EVENT-PROTOCOL §4)
    return e.kind
