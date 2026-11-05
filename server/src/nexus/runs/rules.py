"""Pre-conditions of handing a task to an agent (ADR-023): refuse now what `working` would refuse.

Pure rules over what the caller already read, like `tasks/rules.py`. A run that would start and
then see its first `working` event refused (task done, no next action, another main operation,
unresolved dependency) is a 409 at dispatch time, with the same codes as the task rules.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.adapters.registry import AdapterRegistry
from nexus.models import Run, Task
from nexus.runs.states import ACTIVE
from nexus.tasks import rules as task_rules
from nexus.tasks.queries import _other_main_in_progress, _pending_dependencies
from nexus.tasks.rules import RuleViolation


def already_active(run_ref: str) -> RuleViolation:
    return RuleViolation(
        "run_already_active",
        f"cet agent a déjà un run actif sur cette tâche ({run_ref}) : annule-le ou attends sa fin",
    )


def check_dispatchable(
    session: Session, task: Task, *, executor: str, agent: str, registry: AdapterRegistry
) -> None:
    if registry.get(executor) is None:
        raise RuleViolation(
            "executor_unavailable",
            "aucun adaptateur n'est configuré pour cet exécutant : rien n'est lancé",
        )
    task_rules.check_not_done(task.status)
    if task.status != "in_progress":
        task_rules.check_transition(task.status, "in_progress")
    task_rules.check_next_action("in_progress", task.next_action)
    task_rules.check_dependencies("in_progress", _pending_dependencies(session, task))
    if task.status != "in_progress":
        # The role the task would take when it starts (ADR-004): refused here if it cannot.
        task_rules.resolve_role(task.operation_role, _other_main_in_progress(session, task))
    active = session.scalar(
        select(Run).where(Run.task_id == task.id, Run.agent == agent, Run.status.in_(ACTIVE))
    )
    if active is not None:
        raise already_active(active.ref)
