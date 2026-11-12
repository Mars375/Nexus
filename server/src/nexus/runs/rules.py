"""Pre-conditions of handing a task to an agent (ADR-023): refuse now what `working` would refuse.

Pure rules over what the caller already read, like `tasks/rules.py`. A run that would start and
then see its first `working` event refused (task done, no next action, another main operation,
unresolved dependency) is a 409 at dispatch time, with the same codes as the task rules.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.adapters.registry import AdapterRegistry
from nexus.events.runs import _runs
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


def check_task_ready(session: Session, task: Task) -> None:
    """The task could start now: what the first `working` event would be judged on."""
    task_rules.check_not_done(task.status)
    if task.status != "in_progress":
        task_rules.check_transition(task.status, "in_progress")
    task_rules.check_next_action("in_progress", task.next_action)
    task_rules.check_dependencies("in_progress", _pending_dependencies(session, task))
    if task.status != "in_progress":
        # The role the task would take when it starts (ADR-004): refused here if it cannot.
        task_rules.resolve_role(task.operation_role, _other_main_in_progress(session, task))


# Which agents an executor works for (ADR-023 D5, D8; INTEGRATIONS §A): Hermes serves the node
# agents it hosts, the others serve only themselves.
AGENTS_OF = {
    "hermes": frozenset({"helios", "mnema", "aether"}),
    "codex": frozenset({"codex"}),
    "claude": frozenset({"claude"}),
    "orca": frozenset({"orca"}),
}


# The models a run can ask for, cheapest first (ADR-023 addendum of 2026-11-11), and the
# executors that serve them. An adapter may narrow the list with an optional `models` attribute,
# like `agents`.
RUN_MODELS = ("haiku", "sonnet", "opus")
MODELS_OF = {"claude": RUN_MODELS}


def check_model(executor: str, model: str | None) -> None:
    """Required when the executor serves models, refused otherwise: never ignored in silence."""
    if executor in MODELS_OF:
        if model is None:
            raise RuleViolation("model_required", "choisis un modèle pour ce run")
    elif model is not None:
        raise RuleViolation(
            "model_not_for_executor", "cet exécutant ne propose pas de choix de modèle"
        )


def check_dispatchable(
    session: Session,
    task: Task,
    *,
    executor: str,
    agent: str,
    registry: AdapterRegistry,
    model: str | None = None,
) -> None:
    if agent not in AGENTS_OF.get(executor, frozenset()):
        raise RuleViolation(
            "agent_not_for_executor", "cet exécutant ne travaille pas pour cet agent"
        )
    adapter = registry.get(executor)
    if adapter is None:
        raise RuleViolation(
            "executor_unavailable",
            "aucun adaptateur n'est configuré pour cet exécutant : rien n'est lancé",
        )
    served = getattr(adapter, "agents", None)
    if served is not None and agent not in served:
        raise RuleViolation(
            "executor_unavailable",
            "aucun adaptateur n'est configuré pour cet agent : rien n'est lancé",
        )
    check_model(executor, model)
    check_task_ready(session, task)
    active = session.scalar(
        select(Run).where(Run.task_id == task.id, Run.agent == agent, Run.status.in_(ACTIVE))
    )
    if active is not None:
        raise already_active(active.ref)
    # The journal agrees: a run the executor opened itself and never closed would refuse the
    # `working` of this one, after the work was handed over.
    open_run, _ = _runs(session, executor, task)
    if open_run is not None:
        raise RuleViolation(
            "run_already_active",
            f"{executor} a déjà un run ouvert sur cette tâche dans le journal : il doit "
            "d'abord le clore (done, review, failed, handoff ou blocked)",
        )
    busy = session.scalar(
        select(Run).where(Run.executor == executor, Run.status.in_(ACTIVE))
    )
    if busy is not None:
        # ADR-023 D7: one live run per executor, all tasks together.
        raise RuleViolation(
            "executor_busy",
            f"cet exécutant a déjà un run actif ({busy.ref}) : annule-le ou attends sa fin",
        )
