"""Règles du protocole d'événements (EVENT-PROTOCOL §3, §4, §7) — logique pure.

Un événement valide est un fait actionnable : il nomme son destinataire quand il demande
quelque chose, dit sa cause quand il bloque ou échoue, et prouve ce qu'il déclare terminé.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from nexus.actors import ACTORS, HUMANS
from nexus.events.limits import CONSEQUENCE_MAX, EXPIRY_MAX, EXPIRY_MIN, RUN_MAX
from nexus.secrets import is_blank, is_blank_reference
from nexus.tasks.rules import RuleViolation

KINDS = (
    "claimed", "working", "progress", "question", "blocked", "needs_human", "handoff",
    "review", "done", "failed", "unknown",
)

# Ces événements parlent d'une tâche précise.
TASK_REQUIRED = frozenset(
    {"claimed", "working", "progress", "blocked", "handoff", "review", "done", "failed"}
)


# Asks open an approval when they are addressed to a human (ADR-019).
ASK_KINDS = ("question", "needs_human")


# Champs du payload recopiés dans la tâche (cause, plan de déblocage, prochaine action) :
# ils doivent être du texte, sinon l'écriture en base échouerait.
TEXT_PAYLOAD_FIELDS = ("cause", "plan", "next_action")


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


def expiry_of(payload: dict[str, Any]) -> datetime | None:
    """`payload.expires_at` as a UTC instant, or None when absent (never echoes the value).

    A string with a timezone only: a naive date has no instant, a number is not a date. Every
    comparison is then made between UTC instants (PEP 495 `fold`, microseconds far in the future).
    """
    value = payload.get("expires_at")
    if value is None:
        return None
    message = "payload.expires_at doit être un instant ISO-8601 avec fuseau (texte)"
    if not isinstance(value, str):
        raise RuleViolation("invalid_expires_at", message)
    try:
        instant = datetime.fromisoformat(value)
        if instant.utcoffset() is None:
            raise ValueError
        return instant.astimezone(UTC)
    except (ValueError, OverflowError):  # OverflowError: year 9999 with a negative offset
        raise RuleViolation("invalid_expires_at", message) from None


def check_expiry_window(expires_at: datetime, received_at: datetime) -> None:
    """The deadline of a NEW ask: 1 minute to 30 days after its reception, as exact durations.

    Not applied to a resend of a known event: it is a read-back, even after its deadline.
    """
    received = received_at.astimezone(UTC)
    if expires_at < received + EXPIRY_MIN:
        raise RuleViolation(
            "expires_at_too_soon",
            "payload.expires_at doit tomber au moins 1 minute après la réception",
        )
    if expires_at > received + EXPIRY_MAX:
        raise RuleViolation(
            "expires_at_too_far",
            "payload.expires_at doit tomber au plus 30 jours après la réception",
        )


def require_consequence(e: Envelope) -> None:
    """A NEW `needs_human` states what happens if Loïc approves (ADR-019, D3). See check_new_ask."""
    if e.kind == "needs_human" and not _text(e.payload.get("consequence")):
        raise RuleViolation(
            "consequence_required",
            "needs_human doit dire ce qui se passera si Loïc approuve (payload.consequence)",
        )


def check_new_ask(e: Envelope, raw_consequence: Any, received_at: datetime) -> datetime | None:
    """What only a NEW ask must satisfy; returns its deadline (UTC) or None.

    Not part of `validate`, which runs before the read-back of an identical resend: an event
    published before these rules existed (a malformed `expires_at`, a consequence of any type or
    length, no consequence) must still be replayed, not refused. Direct service calls go through
    here too, since `publish` runs it for every new event.

    `raw_consequence` is the value as received, measured before masking and stripping, as the
    HTTP layer would measure it.
    """
    if e.kind not in ASK_KINDS:
        return None
    if e.payload.get("consequence") is not None and not isinstance(
        e.payload.get("consequence"), str
    ):
        raise RuleViolation("invalid_consequence", "payload.consequence doit être un texte")
    if isinstance(raw_consequence, str) and len(raw_consequence) > CONSEQUENCE_MAX:
        raise RuleViolation(
            "too_long_consequence", f"payload.consequence : {CONSEQUENCE_MAX} caractères au plus"
        )
    require_consequence(e)
    expires_at = expiry_of(e.payload)
    if expires_at is not None:
        check_expiry_window(expires_at, received_at)
    return expires_at


def proofs(e: Envelope) -> list[str]:
    """Preuves utilisables : une preuve vide ou masquée (secret collé) ne prouve rien."""
    return [ref for ref in e.evidence if not is_blank_reference(ref)]


def cause_of(e: Envelope) -> str | None:
    return _text(e.payload.get("cause")) or _text(e.body)


def validate(e: Envelope) -> str:
    """Vérifie l'événement et renvoie son type effectif (un `done` sans preuve devient `review`)."""
    if e.actor not in ACTORS:
        # L'API le garantit déjà ; un adaptateur qui appelle publish() directement, non.
        raise RuleViolation("unknown_actor", "actor : acteur inconnu")
    if e.kind not in KINDS:
        # La valeur reçue n'est jamais recopiée (elle pourrait être un secret) : on nomme le champ.
        raise RuleViolation("unknown_kind", "kind : type d'événement inconnu")
    if is_blank(e.subject):
        raise RuleViolation("subject_required", "l'événement doit avoir un sujet lisible")
    if e.kind in TASK_REQUIRED and not e.task:
        raise RuleViolation("task_required", f"un événement {e.kind} doit viser une tâche")
    run_ref = e.payload.get("run_ref")
    if run_ref is not None and not (
        isinstance(run_ref, str) and 0 < len(run_ref.strip()) <= RUN_MAX
    ):
        raise RuleViolation(
            "invalid_run_ref",
            f"payload.run_ref doit être un texte de {RUN_MAX} caractères au plus",
        )
    if _text(run_ref) and _text(e.run) and _text(run_ref) != _text(e.run):
        raise RuleViolation(
            "run_ref_conflict", "run et payload.run_ref désignent des runs différents"
        )
    for name in TEXT_PAYLOAD_FIELDS:
        value = e.payload.get(name)
        if value is not None and not isinstance(value, str):
            raise RuleViolation(f"invalid_{name}", f"payload.{name} doit être un texte")
    unknown_needs = sorted(set(e.needs) - ACTORS)
    if unknown_needs:
        raise RuleViolation("unknown_recipient", "needs : destinataire inconnu")

    match e.kind:
        case "working":
            if not (_text(e.payload.get("run_ref")) or _text(e.run)):
                raise RuleViolation(
                    "run_ref_required", "working doit donner la référence du run (payload.run_ref)"
                )
        case "progress":
            percent = e.payload.get("percent")
            if percent is not None and not (
                isinstance(percent, int | float) and not isinstance(percent, bool)
                and 0 <= percent <= 100
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
