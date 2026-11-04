"""Read-only task queries: a task, the board, comments, history and the dependency graph."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.models import Task, TaskComment, TaskDependency, TaskHistory
from nexus.tasks import rules


class TaskNotFound(Exception):
    def __init__(self, ref: str) -> None:
        super().__init__(f"tâche introuvable : {ref}")
        self.ref = ref


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


def _advanced_dependents(session: Session, task: Task) -> list[str]:
    rows = session.execute(
        select(Task.id, Task.status)
        .join(TaskDependency, TaskDependency.task_id == Task.id)
        .where(TaskDependency.depends_on_id == task.id)
        .order_by(Task.id)
    )
    return [
        f"nx-task-{dep_id} ({status})"
        for dep_id, status in rows
        if status in rules.GATED_BY_DEPENDENCIES
    ]


def _pending_dependencies(session: Session, task: Task) -> list[str]:
    rows = session.execute(
        select(Task.id, Task.status)
        .join(TaskDependency, TaskDependency.depends_on_id == Task.id)
        .where(TaskDependency.task_id == task.id)
        .order_by(Task.id)
    )
    return [
        f"nx-task-{dep_id} ({status})"
        for dep_id, status in rows
        if status not in rules.DEPENDENCY_RESOLVED
    ]


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
    # Pas d'écriture anticipée des changements en cours : la règle doit répondre avant l'index.
    with session.no_autoflush:
        return session.scalar(query) is not None
