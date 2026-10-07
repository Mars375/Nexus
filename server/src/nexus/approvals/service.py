"""Read side of approvals (#26, PR 1).

An approval is a light state row; what was asked (subject, body, requester, task, options,
consequence) is read from the immutable request event. The `expired` status is never stored:
it is computed here, at read time, with the server clock, on UTC instants (ADR-019).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.approvals.limits import LIST_LIMIT_DEFAULT, REF_DIGITS_MAX, REF_PREFIX
from nexus.clock import now
from nexus.events.service import parse_task_ref
from nexus.models import Approval, Event

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
    event: Event
    status: str  # effective status
    measured_at: datetime


def get_approval(session: Session, ref: str) -> ApprovalView:
    if not _REF.fullmatch(ref):  # ASCII digits only, bounded: `²` or 5 000 digits are a 404
        raise ApprovalNotFound("")
    number = int(ref.removeprefix(REF_PREFIX))
    approval = session.get(Approval, number)
    if approval is None:
        raise ApprovalNotFound(f"{REF_PREFIX}{number}")
    measured_at = now()
    return _view(session, approval, measured_at)


def list_approvals(
    session: Session,
    *,
    status: str | None = None,
    task: str | None = None,
    limit: int = LIST_LIMIT_DEFAULT,
) -> list[ApprovalView]:
    """Newest first. `status` filters on the effective status, `expired` included."""
    measured_at = now()
    query = select(Approval).order_by(Approval.id.desc())
    if task:
        query = query.join(Event, Event.id == Approval.request_event_id).where(
            Event.task_id == parse_task_ref(task)
        )
    if status in ("approved", "rejected", "answered"):
        query = query.where(Approval.status == status).limit(limit)
    elif status in ("pending", "expired"):
        # Both are stored as `pending`: the split is decided on the instant, in Python.
        query = query.where(Approval.status == "pending")
    else:
        query = query.limit(limit)
    views: list[ApprovalView] = []
    for approval in session.scalars(query):
        effective = effective_status(approval, measured_at)
        if status in ("pending", "expired") and effective != status:
            continue
        views.append(_view(session, approval, measured_at))
        if len(views) == limit:
            break
    return views


def effective_status(approval: Approval, at: datetime) -> str:
    """A pending approval whose deadline has been reached is `expired` (deadline included)."""
    if (approval.status == "pending" and approval.expires_at is not None
            and approval.expires_at.astimezone(UTC) <= at.astimezone(UTC)):
        return "expired"
    return approval.status


def _view(session: Session, approval: Approval, measured_at: datetime) -> ApprovalView:
    event = session.get(Event, approval.request_event_id)
    assert event is not None  # the foreign key guarantees it
    return ApprovalView(approval, event, effective_status(approval, measured_at), measured_at)
