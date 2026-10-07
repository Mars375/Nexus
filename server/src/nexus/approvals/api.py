"""API des approbations (#26) : lecture seule dans cette première étape.

Une approbation est l'état de décision d'une demande (`question` ou `needs_human`) adressée à
un humain. Ce qui est demandé est lu dans l'événement de demande ; le statut `expired` est
calculé à la lecture, jamais écrit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from nexus.approvals import service
from nexus.approvals.limits import LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX
from nexus.tasks.api import SessionDep

Status = Literal["pending", "approved", "rejected", "answered", "expired"]

router = APIRouter(prefix="/api/approvals", tags=["approbations"])


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
    response: dict[str, Any] | None  # {event, text, choice}; always null until answers exist
    source: str = "nexus.db"
    measured_at: datetime


def to_out(view: service.ApprovalView) -> ApprovalOut:
    approval, event = view.approval, view.event
    consequence = event.payload.get("consequence")
    return ApprovalOut(
        id=approval.ref, event=event.ref, ask_kind=approval.ask_kind, requested_by=event.actor,
        subject=event.subject, body=event.body, options=_options(event.payload),
        consequence=consequence.strip() or None if isinstance(consequence, str) else None,
        task=f"nx-task-{event.task_id}" if event.task_id else None, status=view.status,
        expires_at=approval.expires_at, decided_by=None, decided_at=None, response=None,
        measured_at=view.measured_at,
    )


def _options(payload: dict[str, Any]) -> list[str]:
    """Option texts at their original positions: `choice` is an index into `payload.options`.

    The list keeps the length and order of the payload; an element that is not text, or blank,
    becomes an empty string rather than shifting the following indices.
    """
    options = payload.get("options")
    if not isinstance(options, list):
        return []
    return [o.strip() if isinstance(o, str) else "" for o in options]


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
