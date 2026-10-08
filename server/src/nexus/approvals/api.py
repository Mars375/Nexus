"""API des approbations (#26) : lecture, réponse à une question, décision sur une validation.

Une approbation est l'état de décision d'une demande (`question` ou `needs_human`) adressée à
un humain. Ce qui est demandé est lu dans l'événement de demande ; le statut `expired` est
calculé à la lecture, jamais écrit. Répondre ou décider écrit un événement `answer` et met à
jour l'approbation dans une seule transaction (voir `service`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, StrictInt, StringConstraints

from nexus.approvals import service
from nexus.approvals.limits import ANSWER_TEXT_MAX, LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX, NOTE_MAX
from nexus.auth.deps import Authenticated
from nexus.tasks.api import ActorDep, SessionDep, commit
from nexus.validation import InputModel

Status = Literal["pending", "approved", "rejected", "answered", "expired"]

router = APIRouter(
    prefix="/api/approvals", tags=["approbations"], dependencies=Authenticated
)


class ApprovalOut(BaseModel):
    id: str
    event: str  # the request event
    ask_kind: str
    requested_by: str
    subject: str
    body: str | None
    options: list[str]
    # Announced by the requester and not verified by Nexus (ADR-005): the UI says « annoncée par ».
    consequence: str | None
    task: str | None
    status: str  # effective: `expired` is computed at read time
    expires_at: datetime | None
    decided_by: str | None
    decided_at: datetime | None
    # {event, text, choice, redacted} once somebody answered or decided, else null. `text` is the
    # answer or the note, as stored (secrets masked); `redacted` lists the kinds of secret masked.
    response: dict[str, Any] | None
    source: str = "nexus.db"
    measured_at: datetime


def to_out(view: service.ApprovalView) -> ApprovalOut:
    approval, event, response = view.approval, view.event, view.response
    return ApprovalOut(
        id=approval.ref, event=event.ref, ask_kind=approval.ask_kind, requested_by=event.actor,
        subject=event.subject, body=event.body, options=service.options_of(event.payload),
        consequence=service.consequence_of(event.payload),
        task=f"nx-task-{event.task_id}" if event.task_id else None, status=view.status,
        expires_at=approval.expires_at,
        decided_by=response.actor if response else None,
        decided_at=response.received_at if response else None,
        response=None if response is None else {
            "event": response.ref, "text": response.body,
            "choice": response.payload.get("choice"), "redacted": response.redacted,
        },
        measured_at=view.measured_at,
    )


class AnswerIn(InputModel):
    """Empty text is accepted here and refused by the service (409 `answer_required`), like the
    text that is only masked secrets: one rule, one place."""

    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=ANSWER_TEXT_MAX)]


class DecisionIn(InputModel):
    decision: Literal["approved", "rejected"]
    # StrictInt: `true` is not an index (a bool is an int in Python); the service judges the range.
    choice: StrictInt | None = None
    note: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=NOTE_MAX)
    ] | None = None


@router.get("")
def list_(
    session: SessionDep,
    status: Status | None = None,
    task: str | None = None,
    limit: Annotated[int, Query(ge=1, le=LIST_LIMIT_MAX)] = LIST_LIMIT_DEFAULT,
) -> list[ApprovalOut]:
    views = service.list_approvals(session, status=status, task=task, limit=limit)
    return [to_out(v) for v in views]


@router.get("/{approval_ref}")
def read(approval_ref: str, session: SessionDep) -> ApprovalOut:
    return to_out(service.get_approval(session, approval_ref))


@router.post("/{approval_ref}/answer")
def answer(approval_ref: str, body: AnswerIn, session: SessionDep, actor: ActorDep) -> ApprovalOut:
    """Answer a `question` (pending -> answered). A resend of the same answer is a 200."""
    view = service.answer(session, approval_ref, actor, body.text)
    commit(session)
    return to_out(view)


@router.post("/{approval_ref}/decision")
def decide(
    approval_ref: str, body: DecisionIn, session: SessionDep, actor: ActorDep
) -> ApprovalOut:
    """Approve or reject a `needs_human` (pending -> approved | rejected)."""
    view = service.decide(
        session, approval_ref, actor, body.decision, choice=body.choice, note=body.note
    )
    commit(session)
    return to_out(view)
