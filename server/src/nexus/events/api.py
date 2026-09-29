"""API d'événements (FR-4) : un agent lancé ailleurs déclare ce qu'il fait (ADR-015 b)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
)

from nexus.actors import Actor
from nexus.clock import now
from nexus.events import service
from nexus.events.rules import Envelope
from nexus.models import Event
from nexus.tasks.api import SessionDep, commit
from nexus.validation import InputModel

Kind = Literal[
    "claimed", "working", "progress", "question", "blocked", "needs_human", "handoff",
    "review", "done", "failed", "unknown",
]
Ref = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]

router = APIRouter(prefix="/api/events", tags=["événements"])


class EventIn(InputModel):
    """Enveloppe EVENT-PROTOCOL §2."""


    v: Literal[1] = 1
    id: str = Field(min_length=1, max_length=128, description="identifiant unique chez l'acteur")
    at: AwareDatetime
    task: str | None = None
    run: str | None = Field(default=None, max_length=128)
    actor: Actor
    kind: Kind
    subject: str = Field(min_length=1, max_length=500)
    body: str | None = None
    payload: dict[str, Any] = {}

    @field_validator("payload")
    @classmethod
    def _finite_numbers_only(cls, payload: dict[str, Any]) -> dict[str, Any]:
        # NaN et Infinity passent le décodage mais cassent la sérialisation des réponses.
        def check(value: Any) -> None:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("le payload ne peut pas contenir NaN ni Infinity")
            if isinstance(value, dict):
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)

        check(payload)
        return payload
    evidence: list[Ref] = []
    needs: list[Actor] = []


class EventOut(BaseModel):
    v: Literal[1] = 1
    id: str
    actor_event_id: str
    at: datetime
    received_at: datetime
    task: str | None
    run: str | None
    actor: str
    kind: str
    requested_kind: str | None
    subject: str
    body: str | None
    payload: dict[str, Any]
    evidence: list[str]
    needs: list[str]
    redacted: list[str]
    origin: str  # « api » ou nom de l'adaptateur qui a traduit l'événement
    effects: list[dict[str, Any]]
    source: str = "nexus.db"
    measured_at: datetime


def to_out(e: Event) -> EventOut:
    return EventOut(
        id=e.ref, actor_event_id=e.actor_event_id, at=e.at, received_at=e.received_at,
        task=f"nx-task-{e.task_id}" if e.task_id else None, run=e.run_ref, actor=e.actor,
        kind=e.kind, requested_kind=e.requested_kind, subject=e.subject, body=e.body,
        payload=e.payload, evidence=e.evidence, needs=e.needs, redacted=e.redacted, origin=e.origin,
        effects=e.effects, measured_at=now(),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def publish(
    body: EventIn,
    session: SessionDep,
    response: Response,
    x_nexus_actor: Annotated[str | None, Header()] = None,
) -> EventOut:
    if x_nexus_actor and x_nexus_actor != body.actor:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "l'acteur de l'en-tête et celui de l'événement diffèrent",
        )
    envelope = Envelope(
        actor=body.actor, kind=body.kind, subject=body.subject, task=body.task, run=body.run,
        body=body.body, payload=body.payload, evidence=body.evidence, needs=body.needs,
    )
    event, created = service.publish(session, envelope, body.id, body.at)
    commit(session)
    if not created:
        response.status_code = status.HTTP_200_OK  # renvoi identique : relecture
    return to_out(event)


@router.get("/{event_ref}")
def read(event_ref: str, session: SessionDep) -> EventOut:
    return to_out(service.get_event(session, event_ref))


@router.get("")
def list_(
    session: SessionDep,
    task: str | None = None,
    actor: Actor | None = None,
    kind: Kind | None = None,
    since: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[EventOut]:
    events = service.list_events(
        session, task=task, actor=actor, kind=kind, since=since, limit=limit
    )
    return [to_out(e) for e in events]
