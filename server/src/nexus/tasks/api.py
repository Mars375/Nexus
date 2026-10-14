"""API des tâches (PRD FR-1, FR-2, FR-6). Aucune route ne déclenche d'agent (ADR-012)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus.actors import Actor, Human
from nexus.auth.deps import Authenticated, authenticated_actor, get_session
from nexus.clock import now
from nexus.events.limits import EVIDENCE_REF_MAX
from nexus.models import Task, TaskComment, TaskHistory
from nexus.tasks import service
from nexus.tasks.rules import RuleViolation
from nexus.validation import InputModel

Status =Literal["backlog", "todo", "in_progress", "blocked", "review", "done", "dropped"]
Priority = Literal["low", "normal", "high", "critical"]
Role = Literal["main", "auxiliary"]

SOURCE = "nexus.db"

router = APIRouter(prefix="/api/tasks", tags=["tâches"], dependencies=Authenticated)


# --- Dépendances --------------------------------------------------------------------------


def parse_ref(task_ref: str) -> int:
    raw = task_ref.removeprefix("nx-task-")
    # Chiffres ASCII seulement, longueur raisonnable ; la valeur reçue n'est jamais recopiée
    # dans l'erreur (elle pourrait être un secret collé par erreur).
    if not re.fullmatch(r"[0-9]{1,12}", raw):
        raise service.TaskNotFound("référence invalide")
    return int(raw)


SessionDep = Annotated[Session, Depends(get_session)]
ActorDep = Annotated[str, Depends(authenticated_actor)]
EvidenceRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# Same constraint as an event's evidence (events.api.Ref): stripped, non-empty, bounded.
BoundedEvidenceRef = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=EVIDENCE_REF_MAX)
]
# « Suite de » reference: ASCII digits only, bounded. Leading zeros are accepted and read as a
# number by the service (`nx-task-0007` is `nx-task-7`).
FollowsRef = Annotated[str, StringConstraints(pattern=r"^nx-task-[0-9]{1,12}$")]
# Un titre ou un objectif fait seulement d'espaces est vide.
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def commit(session: Session) -> None:
    """Valide ; une opération principale concurrente (index unique) devient un refus métier."""
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if "uq_tasks_one_main_in_progress" in str(exc.orig) or "tasks.human_owner" in str(
            exc.orig
        ):
            raise RuleViolation(
                "main_operation_taken",
                "une autre opération principale vient d'être démarrée pour cet humain",
            ) from exc
        raise


# --- Schémas ------------------------------------------------------------------------------


class TaskCreate(InputModel):

    title: Title
    objective: Text
    status: Literal["backlog", "todo"] = "backlog"
    human_owner: Human = "loic"
    lead_agent: Actor | None = None
    collaborators: list[Actor] = []
    next_action: str | None = None
    due_at: AwareDatetime | None = None
    follow_up_at: AwareDatetime | None = None
    expected_evidence: str | None = None
    priority: Priority = "normal"
    operation_role: Role | None = None
    origin: str | None = None
    context: list[str] = []
    follows: FollowsRef | None = None


NOT_NULLABLE = frozenset(
    {"title", "objective", "human_owner", "collaborators", "priority", "context"}
)


class TaskUpdate(InputModel):

    title: Title | None = None
    objective: Text | None = None
    human_owner: Human | None = None
    lead_agent: Actor | None = None
    collaborators: list[Actor] | None = None
    next_action: str | None = None
    due_at: AwareDatetime | None = None
    follow_up_at: AwareDatetime | None = None
    expected_evidence: str | None = None
    priority: Priority | None = None
    operation_role: Role | None = None
    origin: str | None = None
    context: list[str] | None = None
    follows: FollowsRef | None = None

    @model_validator(mode="after")
    def _no_null_on_required(self) -> Self:
        nulled = sorted(f for f in self.model_fields_set & NOT_NULLABLE if getattr(self, f) is None)
        if nulled:
            raise ValueError(f"ces champs ne peuvent pas être vidés : {nulled}")
        return self


class StatusChange(InputModel):

    status: Status
    reason: str | None = None
    block_cause: str | None = None
    block_plan: str | None = None
    follow_up_at: AwareDatetime | None = None
    evidence: list[EvidenceRef] | None = None
    next_action: str | None = None
    role: Role | None = None


class EvidenceIn(InputModel):
    """Evidence to append to a task of any status (ADR-022)."""

    evidence: list[BoundedEvidenceRef] = Field(min_length=1)


class CommentIn(InputModel):

    body: str = Field(min_length=1)


class TaskOut(BaseModel):
    id: str
    title: str
    objective: str
    status: Status
    human_owner: str
    lead_agent: str | None
    collaborators: list[str]
    next_action: str | None
    due_at: datetime | None
    follow_up_at: datetime | None
    block_cause: str | None
    block_plan: str | None
    drop_reason: str | None
    expected_evidence: str | None
    evidence: list[str]
    priority: Priority
    operation_role: Role | None
    origin: str | None
    context: list[str]
    depends_on: list[str]
    follows: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    source: str = SOURCE
    measured_at: datetime


class CommentOut(BaseModel):
    id: int
    task: str
    author: str
    body: str
    at: datetime
    source: str = SOURCE
    measured_at: datetime


class HistoryOut(BaseModel):
    id: int
    task: str
    actor: str
    at: datetime
    action: str
    changes: dict
    source: str = SOURCE
    measured_at: datetime


def to_out(session: Session, task: Task) -> TaskOut:
    return TaskOut(
        id=task.ref,
        **{f: getattr(task, f) for f in TaskOut.model_fields if hasattr(Task, f) and f != "id"},
        depends_on=[f"nx-task-{i}" for i in service.dependencies_of(session, task)],
        follows=None if task.follows_id is None else f"nx-task-{task.follows_id}",
        measured_at=now(),
    )


def comment_out(c: TaskComment) -> CommentOut:
    return CommentOut(
        id=c.id, task=f"nx-task-{c.task_id}", author=c.author, body=c.body, at=c.at,
        measured_at=now(),
    )


def history_out(h: TaskHistory) -> HistoryOut:
    return HistoryOut(
        id=h.id, task=f"nx-task-{h.task_id}", actor=h.actor, at=h.at, action=h.action,
        changes=h.changes, measured_at=now(),
    )


# --- Routes -------------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: TaskCreate, session: SessionDep, actor: ActorDep) -> TaskOut:
    task = service.create_task(session, body.model_dump(), actor)
    commit(session)
    return to_out(session, task)


@router.get("")
def list_(
    session: SessionDep,
    status_: Annotated[list[Status] | None, Query(alias="status")] = None,
    agent: Actor | None = None,
    owner: Human | None = None,
    priority: Priority | None = None,
    role: Role | None = None,
    due_before: AwareDatetime | None = None,
) -> list[TaskOut]:
    tasks = service.list_tasks(
        session, statuses=status_, agent=agent, owner=owner, priority=priority, role=role,
        due_before=due_before,
    )
    return [to_out(session, t) for t in tasks]


@router.get("/{task_ref}")
def read(task_ref: str, session: SessionDep) -> TaskOut:
    return to_out(session, service.get_task(session, parse_ref(task_ref)))


@router.patch("/{task_ref}")
def update(task_ref: str, body: TaskUpdate, session: SessionDep, actor: ActorDep) -> TaskOut:
    task = service.get_task(session, parse_ref(task_ref))
    service.update_task(session, task, body.model_dump(exclude_unset=True), actor)
    commit(session)
    return to_out(session, task)


@router.post("/{task_ref}/status")
def change_status(
    task_ref: str, body: StatusChange, session: SessionDep, actor: ActorDep
) -> TaskOut:
    task = service.get_task(session, parse_ref(task_ref))
    service.change_status(
        session, task, body.status, actor,
        **body.model_dump(exclude={"status"}),
    )
    commit(session)
    return to_out(session, task)


@router.post("/{task_ref}/evidence")
def attach_evidence(
    task_ref: str, body: EvidenceIn, session: SessionDep, actor: ActorDep
) -> TaskOut:
    task = service.get_task(session, parse_ref(task_ref))
    service.attach_evidence(session, task, body.evidence, actor)
    commit(session)
    return to_out(session, task)


@router.post("/{task_ref}/comments", status_code=status.HTTP_201_CREATED)
def comment(task_ref: str, body: CommentIn, session: SessionDep, actor: ActorDep) -> CommentOut:
    task = service.get_task(session, parse_ref(task_ref))
    created = service.add_comment(session, task, actor, body.body)
    commit(session)
    return comment_out(created)


@router.get("/{task_ref}/comments")
def comments(task_ref: str, session: SessionDep) -> list[CommentOut]:
    task = service.get_task(session, parse_ref(task_ref))
    return [comment_out(c) for c in service.comments_of(session, task)]


@router.get("/{task_ref}/history")
def history(task_ref: str, session: SessionDep) -> list[HistoryOut]:
    task = service.get_task(session, parse_ref(task_ref))
    return [history_out(h) for h in service.history_of(session, task)]


@router.put("/{task_ref}/dependencies/{other_ref}", status_code=status.HTTP_204_NO_CONTENT)
def link(task_ref: str, other_ref: str, session: SessionDep, actor: ActorDep) -> None:
    task = service.get_task(session, parse_ref(task_ref))
    other = service.get_task(session, parse_ref(other_ref))
    service.add_dependency(session, task, other, actor)
    commit(session)


@router.delete("/{task_ref}/dependencies/{other_ref}", status_code=status.HTTP_204_NO_CONTENT)
def unlink(task_ref: str, other_ref: str, session: SessionDep, actor: ActorDep) -> None:
    task = service.get_task(session, parse_ref(task_ref))
    other = service.get_task(session, parse_ref(other_ref))
    service.remove_dependency(session, task, other, actor)
    commit(session)
