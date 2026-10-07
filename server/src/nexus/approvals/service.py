"""Approvals (#26): reading them (PR 1) and answering or deciding them (PR 2).

An approval is a light state row; what was asked (subject, body, requester, task, options,
consequence) is read from the immutable request event. The `expired` status is never stored:
it is computed here, at read time, with the server clock, on UTC instants (ADR-019).

A response is an immutable `answer` event (the journal) plus the update of the approval row (the
state), written in ONE transaction: `publish` inserts the event, `_close` updates the row under
its version lock. Both succeed or neither is stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from sqlalchemy.orm.exc import StaleDataError

from nexus import secrets
from nexus.actors import ACTORS, HUMANS
from nexus.approvals.limits import (
    ANSWER_ID_PREFIX,
    ANSWER_TEXT_MAX,
    LIST_LIMIT_DEFAULT,
    NOTE_MAX,
    REF_DIGITS_MAX,
    REF_PREFIX,
)
from nexus.clock import TZ, now
from nexus.events import service as events
from nexus.events.rules import Envelope
from nexus.events.service import parse_task_ref
from nexus.models import Approval, Event
from nexus.tasks.rules import RuleViolation
from nexus.validation import has_unencodable

STORED_STATUSES = ("pending", "approved", "rejected", "answered")
STATUSES = (*STORED_STATUSES, "expired")  # `expired` is computed, never stored

_REF = re.compile(re.escape(REF_PREFIX) + rf"[0-9]{{1,{REF_DIGITS_MAX}}}")


class ApprovalNotFound(Exception):
    def __init__(self, ref: str) -> None:
        # Never the received value: it could be a secret pasted by mistake.
        super().__init__(
            f"approbation introuvable : {ref}" if ref else
            "approbation introuvable : référence invalide"
        )


@dataclass(frozen=True)
class ApprovalView:
    approval: Approval
    event: Event  # the request
    status: str  # effective status
    measured_at: datetime
    response: Event | None = None  # the `answer` event, once somebody decided


def parse_ref(ref: object) -> int:
    """The approval number of `nx-appr-<n>`; anything else is a generic 404 (never echoed)."""
    # ASCII digits only, bounded: `²` or 5 000 digits are a 404, not a 500.
    if not isinstance(ref, str) or not _REF.fullmatch(ref):
        raise ApprovalNotFound("")
    return int(ref.removeprefix(REF_PREFIX))


def get_approval(session: Session, ref: str) -> ApprovalView:
    number = parse_ref(ref)
    row = session.execute(_with_event().where(Approval.id == number)).first()
    if row is None:
        raise ApprovalNotFound(f"{REF_PREFIX}{number}")
    return _view(row[0], row[1], row[2], now())


def _with_event():
    """Approvals with their request and response events in ONE query (no per-row lookup)."""
    response = aliased(Event)
    return (
        select(Approval, Event, response)
        .join(Event, Event.id == Approval.request_event_id)
        .outerjoin(response, response.id == Approval.response_event_id)
    )


def options_of(payload: dict[str, Any]) -> list[str]:
    """Option texts at their original positions: `choice` is an index into `payload.options`.

    The list keeps the length and order of the payload; an element that is not text, or blank,
    becomes an empty string rather than shifting the following indices.
    """
    options = payload.get("options")
    if not isinstance(options, list):
        return []
    return [o.strip() if isinstance(o, str) else "" for o in options]


def consequence_of(payload: dict[str, Any]) -> str | None:
    consequence = payload.get("consequence")
    return consequence.strip() or None if isinstance(consequence, str) else None


def list_approvals(
    session: Session,
    *,
    status: str | None = None,
    task: str | None = None,
    limit: int = LIST_LIMIT_DEFAULT,
) -> list[ApprovalView]:
    """Newest first. `status` filters on the effective status, `expired` included."""
    measured_at = now()
    query = _with_event().order_by(Approval.id.desc())
    if task:
        query = query.where(Event.task_id == parse_task_ref(task))
    computed = status in ("pending", "expired")
    if computed:
        # Both are stored as `pending`: the split is decided on the instant, in Python, so the
        # limit applies after it. Rows are streamed and reading stops at `limit` matches.
        query = query.where(Approval.status == "pending").execution_options(yield_per=100)
    else:
        if status:
            query = query.where(Approval.status == status)
        query = query.limit(limit)
    views: list[ApprovalView] = []
    result = session.execute(query)
    try:
        for approval, event, response in result:
            view = _view(approval, event, response, measured_at)
            if computed and view.status != status:
                continue
            views.append(view)
            if len(views) == limit:
                break
    finally:
        result.close()
    return views


def effective_status(approval: Approval, at: datetime) -> str:
    """A pending approval whose deadline has been reached is `expired` (deadline included)."""
    if (approval.status == "pending" and approval.expires_at is not None
            and approval.expires_at.astimezone(UTC) <= at.astimezone(UTC)):
        return "expired"
    return approval.status


def _view(
    approval: Approval, event: Event, response: Event | None, measured_at: datetime
) -> ApprovalView:
    return ApprovalView(
        approval, event, effective_status(approval, measured_at), measured_at, response
    )


# --- Answering and deciding (PR 2) ----------------------------------------------------------------

DECISIONS = ("approved", "rejected")
ATTEMPTS = 3  # a lost race is re-read and re-judged, a few times at most

# decision -> (subject prefix of the answer event, verb of the « already decided » refusal)
_WORDING = {
    "answered": ("réponse", "répondue"),
    "approved": ("validé", "validée"),
    "rejected": ("refusé", "refusée"),
}


class _Conflict(Exception):
    """Another writer got there first: roll back, re-read, judge again."""


def answer(session: Session, ref: str, actor: str, text: str) -> ApprovalView:
    """Answer a `question`. The caller commits; a refusal leaves nothing stored.

    Re-checks what the HTTP models guarantee (types, lengths, encodable text): an adapter calls
    this directly. Raises `RuleViolation` (a 409 over HTTP) and never echoes a received value.
    """
    _require_clean(session)
    _check_actor(actor)
    text = _clean_text(text, "text", ANSWER_TEXT_MAX, "invalid_text", "too_long_text")
    return _settle(session, ref, actor, "question", "answered", text, None)


def decide(
    session: Session,
    ref: str,
    actor: str,
    decision: str,
    choice: int | None = None,
    note: str | None = None,
) -> ApprovalView:
    """Approve or reject a `needs_human`; `choice` is the 0-based index into `payload.options`."""
    _require_clean(session)
    _check_actor(actor)
    if not isinstance(decision, str) or decision not in DECISIONS:
        raise RuleViolation("invalid_decision", "decision : approved ou rejected attendu")
    if choice is not None and (isinstance(choice, bool) or not isinstance(choice, int)):
        raise RuleViolation("invalid_choice", "choice doit être un entier (indice de l'option)")
    if note is not None:
        note = _clean_text(note, "note", NOTE_MAX, "invalid_note", "too_long_note") or None
    return _settle(session, ref, actor, "needs_human", decision, note, choice)


def _require_clean(session: Session) -> None:
    if session.new or session.dirty or session.deleted:
        # Same contract as `publish`: a race rolls back, which would drop the caller's writes.
        raise RuntimeError("une réponse demande une session dédiée, sans écriture en attente")


def _check_actor(actor: object) -> None:
    if not isinstance(actor, str):
        raise RuleViolation("invalid_actor", "actor doit être un texte")
    if actor not in ACTORS:
        raise RuleViolation("unknown_actor", "actor : acteur inconnu")


def _clean_text(value: object, name: str, limit: int, invalid: str, too_long: str) -> str:
    """Stripped as the API does (Pydantic), then measured; the value is never echoed."""
    if not isinstance(value, str):
        raise RuleViolation(invalid, f"{name} doit être un texte")
    if has_unencodable(value):
        raise RuleViolation(
            "invalid_value", "valeur non encodable : demi-paire UTF-16, NaN ou Infinity"
        )
    value = events.API_STRIP.validate_python(value)
    if len(value) > limit:
        raise RuleViolation(too_long, f"{name} : {limit} caractères au plus")
    return value


def _settle(
    session: Session, ref: str, actor: str, ask_kind: str, decision: str, text: str | None,
    choice: int | None,
) -> ApprovalView:
    number = parse_ref(ref)
    for _ in range(ATTEMPTS):
        try:
            return _attempt(session, number, actor, ask_kind, decision, text, choice)
        except _Conflict:
            session.rollback()  # nothing of the losing attempt stays
    raise RuleViolation(
        "approval_concurrent_update",
        "cette demande vient d'être modifiée par ailleurs : relis-la et réessaie",
    )


def _attempt(
    session: Session, number: int, actor: str, ask_kind: str, decision: str, text: str | None,
    choice: int | None,
) -> ApprovalView:
    approval = session.get(Approval, number)
    if approval is None:
        raise ApprovalNotFound(f"{REF_PREFIX}{number}")
    session.refresh(approval)  # judged on the current row, never on a copy loaded earlier
    request = session.get(Event, approval.request_event_id)
    if approval.ask_kind != ask_kind:
        raise RuleViolation("wrong_kind", (
            "une question se traite par une réponse, pas par une validation"
            if approval.ask_kind == "question" else
            "une demande de validation se traite par une décision, pas par une réponse"
        ))
    if request.actor == actor:
        raise RuleViolation("self_decision", "le demandeur ne tranche pas sa propre demande")
    if actor not in HUMANS or actor not in (request.needs or []):
        raise RuleViolation("not_addressee", "seul un destinataire humain de la demande la traite")
    # Masked as `publish` will store it: a resend is compared on what was stored.
    masked = secrets.redact(text)[0] if text else None
    if approval.status != "pending":
        response = (session.get(Event, approval.response_event_id)
                    if approval.response_event_id else None)
        return _replay(approval, request, response, actor, decision, choice, masked)
    if effective_status(approval, now()) == "expired":
        raise RuleViolation("approval_expired", "cette demande a expiré : l'agent ne l'attend plus")
    if ask_kind == "question":
        if secrets.is_blank(masked):  # empty, or nothing but masked secrets
            raise RuleViolation("answer_required", "la réponse est vide : écris-la")
    else:
        _check_choice(request, decision, choice)
    prefix = _WORDING[decision][0]
    envelope = Envelope(
        actor=actor, kind="answer", subject=f"{prefix} : {approval.ref}", body=text,
        task=f"nx-task-{request.task_id}" if request.task_id else None,
        payload={"approval": approval.ref, "in_reply_to": request.ref, "decision": decision,
                 "choice": choice},
        needs=[request.actor],
    )
    try:
        event, created = events.publish(
            session, envelope, f"{ANSWER_ID_PREFIX}{approval.ref}", now(), allow_reserved=True
        )
    except RuleViolation as exc:
        if exc.code == "event_id_reused":  # another decision took the event id first
            raise _Conflict from exc
        raise
    if not created:  # an identical event is already stored: somebody decided first
        raise _Conflict
    _close(session, approval, event, "answered" if ask_kind == "question" else decision)
    return ApprovalView(approval, request, approval.status, now(), event)


def _close(session: Session, approval: Approval, event: Event, status: str) -> None:
    """Link the answer event and move the approval out of `pending`, under the version lock."""
    approval.status = status
    approval.response_event_id = event.id
    try:
        session.flush()
    except (StaleDataError, IntegrityError) as exc:  # the row changed since it was read
        raise _Conflict from exc


def _check_choice(request: Event, decision: str, choice: int | None) -> None:
    options = options_of(request.payload)
    if choice is not None:
        if not 0 <= choice < len(options) or not options[choice]:
            raise RuleViolation("choice_unknown", "choice : cette option n'existe pas")
    elif decision == "approved" and sum(1 for o in options if o) >= 2:
        raise RuleViolation("choice_required", "choice : dis laquelle des options tu approuves")


def _replay(
    approval: Approval, request: Event, response: Event | None, actor: str, decision: str,
    choice: int | None, masked: str | None,
) -> ApprovalView:
    """Already decided: the same decider resending the same content gets the existing state."""
    if response is not None and (
        response.actor == actor and response.payload.get("decision") == decision
        and response.payload.get("choice") == choice and (response.body or None) == masked
    ):
        return ApprovalView(approval, request, approval.status, now(), response)
    verb = _WORDING["answered" if approval.status == "answered" else approval.status][1]
    if response is None:
        raise RuleViolation("approval_already_decided", f"déjà {verb}")
    when = response.received_at.astimezone(TZ).strftime("%d/%m/%Y à %H:%M")
    # The decider is an actor of the closed list: a known safe value, never received text.
    raise RuleViolation(
        "approval_already_decided", f"déjà {verb} par {response.actor} le {when}"
    )
