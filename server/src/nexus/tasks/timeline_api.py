"""`GET /api/tasks/{ref}/timeline`: the story of one card (ADR-023, lot E). Read-only.

Open to any authenticated actor, like the rest of the task reads. Nothing is formatted for the
screen here: the history keeps its `action` and `changes`, the events their kind, effects and
proofs (subject and body were masked before they were stored), the runs their milestones.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from nexus.auth.deps import Authenticated
from nexus.clock import now
from nexus.models import Event, TaskHistory
from nexus.tasks import service, timeline
from nexus.tasks.api import SessionDep, parse_ref

router = APIRouter(prefix="/api/tasks", tags=["tâches"], dependencies=Authenticated)


class EntryOut(BaseModel):
    id: str
    kind: str  # history | event | run_started | run_ended
    at: datetime
    actor: str | None = None
    # history
    action: str | None = None
    changes: dict[str, Any] | None = None
    # event
    event: str | None = None
    event_kind: str | None = None
    requested_kind: str | None = None
    subject: str | None = None
    body: str | None = None
    origin: str | None = None
    effects: list[dict[str, Any]] | None = None
    evidence: list[str] | None = None
    needs: list[str] | None = None
    # event and run milestones
    run: str | None = None
    # run milestones
    executor: str | None = None
    agent: str | None = None
    status: str | None = None
    source: str = "nexus.db"
    measured_at: datetime


class TimelineOut(BaseModel):
    entries: list[EntryOut]
    next_cursor: str | None
    source: str = "nexus.db"
    measured_at: datetime


def entry_out(entry: timeline.Entry, measured_at: datetime) -> EntryOut:
    base = {"id": entry.ref, "kind": entry.kind, "at": entry.at, "measured_at": measured_at}
    if entry.kind == "history":
        h: TaskHistory = entry.data["row"]
        return EntryOut(**base, actor=h.actor, action=h.action, changes=h.changes)
    if entry.kind == "event":
        e: Event = entry.data["row"]
        return EntryOut(
            **base, actor=e.actor, event=e.ref, event_kind=e.kind,
            requested_kind=e.requested_kind, subject=e.subject, body=e.body, origin=e.origin,
            effects=e.effects, evidence=e.evidence, needs=e.needs, run=e.run_ref,
        )
    return EntryOut(**base, **entry.data)


@router.get("/{task_ref}/timeline")
def read(
    task_ref: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=timeline.LIMIT_MAX)] = timeline.LIMIT_DEFAULT,
    before: Annotated[str | None, Query(max_length=80)] = None,
) -> TimelineOut:
    """Newest first. `before` is the `next_cursor` of the previous page, nothing else."""
    task = service.get_task(session, parse_ref(task_ref))
    try:
        position = timeline.Position.decode(before) if before is not None else None
    except timeline.InvalidCursor:
        raise HTTPException(422, {
            "code": "invalid_cursor", "message": "before : curseur invalide (jamais recopié)",
        }) from None
    entries, next_position = timeline.page(session, task, limit=limit, before=position)
    measured_at = now()
    return TimelineOut(
        entries=[entry_out(e, measured_at) for e in entries],
        next_cursor=next_position.encode() if next_position else None,
        measured_at=measured_at,
    )
