"""Opérations sur les tâches : applique les règles et journalise chaque mutation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.clock import now
from nexus.models import Task, TaskComment, TaskDependency, TaskHistory
from nexus.tasks import rules
from nexus.tasks.rules import RuleViolation


class TaskNotFound(Exception):
    def __init__(self, ref: str) -> None:
        super().__init__(f"tâche introuvable : {ref}")
        self.ref = ref


UPDATABLE = frozenset({
    "title", "objective", "human_owner", "lead_agent", "collaborators", "next_action",
    "due_at", "follow_up_at", "expected_evidence", "priority", "operation_role", "origin",
    "context",
})


def get_task(session: Session, task_id: int) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise TaskNotFound(f"nx-task-{task_id}")
    return task


def list_tasks(
    session: Session,
    *,
    statuses: list[str] | None = None,
    agent: str | None = None,
    owner: str | None = None,
    priority: str | None = None,
    role: str | None = None,
    due_before: datetime | None = None,
) -> list[Task]:
    query = select(Task).order_by(Task.updated_at.desc(), Task.id.desc())
    if statuses:
        query = query.where(Task.status.in_(statuses))
    if owner:
        query = query.where(Task.human_owner == owner)
    if priority:
        query = query.where(Task.priority == priority)
    if role:
        query = query.where(Task.operation_role == role)
    tasks = list(session.scalars(query))
    if agent:
        tasks = [t for t in tasks if t.lead_agent == agent or agent in t.collaborators]
    if due_before:
        tasks = [t for t in tasks if t.due_at is not None and t.due_at < due_before]
    return tasks


def create_task(session: Session, data: dict[str, Any], actor: str) -> Task:
    status = data.pop("status", "backlog")
    if status not in rules.INITIAL_STATUSES:
        raise RuleViolation(
            "initial_status", "une tâche se crée en backlog ou en todo, puis avance"
        )
    rules.check_next_action(status, data.get("next_action"))
    ts = now()
    task = Task(
        **data,
        status=status,
        evidence=[],
        created_by=actor,
        created_at=ts,
        updated_at=ts,
    )
    session.add(task)
    session.flush()
    _record(session, task, actor, "created", {
        k: [None, v] for k, v in data.items() if v not in (None, [], "")
    } | {"status": [None, status]})
    return task


def update_task(session: Session, task: Task, changes: dict[str, Any], actor: str) -> Task:
    unknown = set(changes) - UPDATABLE
    if unknown:
        raise RuleViolation("not_updatable", f"champs non modifiables ici : {sorted(unknown)}")
    diff = {}
    for field, value in changes.items():
        old = getattr(task, field)
        if old != value:
            diff[field] = [old, value]
            setattr(task, field, value)
    if not diff:
        return task
    rules.check_next_action(task.status, task.next_action)
    if task.status == "in_progress" and ({"operation_role", "human_owner"} & diff.keys()):
        task.operation_role = rules.resolve_role(
            task.operation_role, _other_main_in_progress(session, task)
        )
    task.updated_at = now()
    _record(session, task, actor, "updated", diff)
    return task


def change_status(
    session: Session,
    task: Task,
    target: str,
    actor: str,
    *,
    reason: str | None = None,
    block_cause: str | None = None,
    block_plan: str | None = None,
    follow_up_at: datetime | None = None,
    evidence: list[str] | None = None,
    next_action: str | None = None,
    role: str | None = None,
) -> Task:
    current = task.status
    rules.check_transition(current, target)
    watched = (
        "next_action", "block_cause", "block_plan", "follow_up_at", "drop_reason",
        "evidence", "operation_role",
    )
    before = {f: getattr(task, f) for f in watched}

    if next_action is not None:
        task.next_action = next_action

    if target == "blocked":
        follow_up = follow_up_at or task.follow_up_at
        rules.check_block(block_cause, block_plan, follow_up)
        task.block_cause, task.block_plan, task.follow_up_at = block_cause, block_plan, follow_up
    elif current == "blocked":
        task.block_cause = task.block_plan = None

    if target == "dropped":
        rules.check_drop(reason)
        task.drop_reason = reason
    elif current == "dropped":
        task.drop_reason = None

    final = target
    if target == "done":
        if evidence:
            task.evidence = list(dict.fromkeys([*task.evidence, *evidence]))
        final = rules.resolve_done(task.expected_evidence, task.evidence)
        if final == current:  # déjà en review, toujours sans preuve
            raise RuleViolation(
                "evidence_required", "cette tâche attend une preuve : fournis-la pour la clore"
            )

    if final == "in_progress":
        task.operation_role = rules.resolve_role(role, _other_main_in_progress(session, task))

    rules.check_next_action(final, task.next_action)
    task.status = final
    task.updated_at = now()

    changes: dict[str, Any] = {"status": [current, final]}
    changes |= {f: [before[f], getattr(task, f)] for f in watched if before[f] != getattr(task, f)}
    if final != target:
        changes["note"] = "preuve attendue manquante : clôture passée en review"
    if reason and target != "dropped":
        changes["reason"] = reason
    _record(session, task, actor, "status", changes)
    return task


def add_comment(session: Session, task: Task, actor: str, body: str) -> TaskComment:
    if not body.strip():
        raise RuleViolation("empty_comment", "un commentaire ne peut pas être vide")
    comment = TaskComment(task_id=task.id, author=actor, body=body, at=now())
    session.add(comment)
    session.flush()
    task.updated_at = comment.at
    _record(session, task, actor, "commented", {"comment_id": comment.id})
    return comment


def comments_of(session: Session, task: Task) -> list[TaskComment]:
    return list(session.scalars(
        select(TaskComment).where(TaskComment.task_id == task.id).order_by(TaskComment.id)
    ))


def history_of(session: Session, task: Task) -> list[TaskHistory]:
    return list(session.scalars(
        select(TaskHistory).where(TaskHistory.task_id == task.id).order_by(TaskHistory.id)
    ))


def dependencies_of(session: Session, task: Task) -> list[int]:
    return list(session.scalars(
        select(TaskDependency.depends_on_id)
        .where(TaskDependency.task_id == task.id)
        .order_by(TaskDependency.depends_on_id)
    ))


def add_dependency(session: Session, task: Task, other: Task, actor: str) -> None:
    if task.id == other.id:
        raise RuleViolation("self_dependency", "une tâche ne peut pas dépendre d'elle-même")
    if session.get(TaskDependency, (task.id, other.id)) is not None:
        return
    if _depends_on(session, other.id, task.id):
        raise RuleViolation(
            "dependency_cycle", f"{other.ref} dépend déjà de {task.ref} : cycle refusé"
        )
    session.add(TaskDependency(task_id=task.id, depends_on_id=other.id))
    task.updated_at = now()
    _record(session, task, actor, "linked", {"depends_on": [None, other.ref]})


def remove_dependency(session: Session, task: Task, other: Task, actor: str) -> None:
    link = session.get(TaskDependency, (task.id, other.id))
    if link is None:
        raise TaskNotFound(f"dépendance {task.ref} → {other.ref}")
    session.delete(link)
    task.updated_at = now()
    _record(session, task, actor, "unlinked", {"depends_on": [other.ref, None]})


def _depends_on(session: Session, start: int, target: int) -> bool:
    """`start` dépend-elle, directement ou non, de `target` ?"""
    seen, stack = set(), [start]
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(session.scalars(
            select(TaskDependency.depends_on_id).where(TaskDependency.task_id == current)
        ))
    return False


def _other_main_in_progress(session: Session, task: Task) -> bool:
    query = select(Task.id).where(
        Task.human_owner == task.human_owner,
        Task.status == "in_progress",
        Task.operation_role == "main",
        Task.id != task.id,
    )
    return session.scalar(query) is not None


def _record(session: Session, task: Task, actor: str, action: str, changes: dict) -> None:
    session.add(TaskHistory(
        task_id=task.id, actor=actor, at=now(), action=action, changes=_jsonable(changes)
    ))


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value
