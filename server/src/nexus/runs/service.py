"""Run operations: create (idempotent by client key), cancel, read, update with a version lock."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus import permissions, secrets
from nexus.adapters.registry import AdapterRegistry
from nexus.clock import now
from nexus.models import Run, Task, TaskHistory
from nexus.runs import rules
from nexus.runs.states import CANCELLABLE, SETTLED
from nexus.tasks.rules import RuleViolation


class RunNotFound(Exception):
    def __init__(self, ref: str) -> None:
        # Never the received value: it could be a secret pasted by mistake.
        super().__init__(f"run introuvable : {ref}" if ref.startswith("nx-run-") else
                         "run introuvable : référence invalide")


@dataclass(frozen=True)
class NewRun:
    executor: str
    agent: str
    client_key: str
    brief: str
    workdir: str | None = None
    model: str | None = None


def _record(session: Session, run: Run, actor: str, action: str) -> None:
    """Trace a human act on a run in the task's history: it is also what tells the live feed
    (`run_changed`) that the runs of that task moved. No brief, no reference is copied."""
    session.add(TaskHistory(
        task_id=run.task_id, actor=actor, at=now(), action=action,
        changes={"run": run.ref, "executor": run.executor, "agent": run.agent},
    ))


def get_run(session: Session, ref: str) -> Run:
    raw = ref.removeprefix("nx-run-")
    if not re.fullmatch(r"[0-9]{1,12}", raw):
        raise RunNotFound("")
    run = session.get(Run, int(raw))
    if run is None:
        raise RunNotFound(f"nx-run-{int(raw)}")
    return run


def list_runs(session: Session, task: Task) -> list[Run]:
    return list(session.scalars(
        select(Run).where(Run.task_id == task.id).order_by(Run.id.desc())
    ))


def _same(run: Run, task_id: int, data: NewRun, brief: str, workdir: str | None) -> bool:
    return (run.task_id, run.executor, run.agent, run.brief, run.workdir, run.model) == (
        task_id, data.executor, data.agent, brief, workdir, data.model)


def create_run(
    session: Session, task: Task, actor: str, data: NewRun, registry: AdapterRegistry
) -> tuple[Run, bool]:
    """The run for this client key and whether it was just created; a resend is a read-back.

    The caller commits. A race is settled by the database: the unique key on the client key
    (the loser re-reads the winner) and the partial unique index on (task, agent) for live runs.
    """
    permissions.check_dispatch(actor)
    if secrets.redact(data.client_key)[1]:
        # Masked, two keys would compare equal: refused, never echoed (checklist §1).
        raise RuleViolation("secret_in_client_key", "client_key : ne doit contenir aucun secret")
    brief = secrets.redact(data.brief)[0]
    if secrets.is_blank(brief):
        raise RuleViolation("brief_required", "brief : un texte lisible est requis")
    if data.workdir and secrets.redact(data.workdir)[1]:
        # A path is compared and handed to the executor: masked, two paths would become equal.
        raise RuleViolation("secret_in_workdir", "workdir : ne doit contenir aucun secret")
    workdir = data.workdir or None
    task_id = task.id

    def known() -> tuple[Run, bool] | None:
        existing = session.scalar(
            select(Run).where(Run.dispatched_by == actor, Run.client_key == data.client_key)
        )
        if existing is None:
            return None
        if _same(existing, task_id, data, brief, workdir):
            return existing, False
        raise RuleViolation(
            "client_key_reused",
            "client_key : déjà utilisée pour un autre run ; une demande ne se réécrit pas",
        )

    if (replay := known()) is not None:
        return replay
    try:
        rules.check_dispatchable(
            session, task, executor=data.executor, agent=data.agent, registry=registry,
            model=data.model,
        )
    except RuleViolation:
        # The click that won the race may have committed since the first look: it is a resend.
        # Whatever rule it tripped, the winner's effects may be the cause: re-read the key first.
        if (replay := known()) is not None:
            return replay
        raise
    run = Run(
        task_id=task_id, executor=data.executor, agent=data.agent, dispatched_by=actor,
        client_key=data.client_key, brief=brief, workdir=workdir, model=data.model,
        status="dispatched",
        created_at=now(),
    )
    session.add(run)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        # Lost on the client key: re-read the winner. Lost on the live-run index: if the winner
        # carries our key it is the same click, else another run holds the agent.
        if (replay := known()) is not None:
            return replay
        # Lost on one of the live-run indexes: judge again on what the winner committed, so the
        # refusal names the right rule (same agent on the task, or executor already busy).
        rules.check_dispatchable(
            session, task, executor=data.executor, agent=data.agent, registry=registry,
            model=data.model,
        )
        raise rules.already_active("un autre run") from exc
    _record(session, run, actor, "run_created")
    return run, True


def request_cancel(session: Session, run: Run, actor: str) -> Run:
    """Record that a human wants the run stopped; the supervisor does the stopping.

    Idempotent. A run that already ended cannot be cancelled. The write goes through the version
    lock: a finish that landed first makes this a StaleDataError (409), never an overwrite.
    """
    permissions.check_dispatch(actor)
    if run.cancel_requested_at is not None:
        return run
    if run.status not in CANCELLABLE:
        raise RuleViolation(
            "run_not_cancellable", f"ce run est déjà {run.status} : il ne s'annule plus"
        )
    run.cancel_requested_at = now()
    session.flush()
    _record(session, run, actor, "run_cancel_requested")
    return run


def update_run(
    session: Session,
    run: Run,
    *,
    status: str | None = None,
    native_status: str | None = None,
    watch_cursor: str | None = None,
    external_ref: str | None = None,
) -> Run:
    """Write what the supervisor learned. Goes through the version lock, like a cancel."""
    if status is not None:
        if status != run.status:
            # Said after the commit by the live feed (`run_changed`): the run row itself has no
            # cursor, and an event may reach the interface before this write does.
            _record(session, run, run.executor, "run_status")
        run.status = status
        if status in SETTLED and run.ended_at is None:
            run.ended_at = now()
    if native_status is not None:
        run.native_status = secrets.redact(native_status)[0][:64]
    if watch_cursor is not None:
        run.watch_cursor = watch_cursor
    if external_ref is not None:
        run.external_ref = secrets.redact(external_ref)[0]
    session.flush()
    return run
