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
from nexus.models import Run, Task
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
    return (run.task_id, run.executor, run.agent, run.brief, run.workdir) == (
        task_id, data.executor, data.agent, brief, workdir)


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
    workdir = secrets.redact(data.workdir)[0] if data.workdir else None
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
    rules.check_dispatchable(
        session, task, executor=data.executor, agent=data.agent, registry=registry
    )
    run = Run(
        task_id=task_id, executor=data.executor, agent=data.agent, dispatched_by=actor,
        client_key=data.client_key, brief=brief, workdir=workdir, status="dispatched",
        created_at=now(),
    )
    session.add(run)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if "client_key" in str(exc.orig):
            if (replay := known()) is not None:
                return replay
        raise rules.already_active("un autre run") from exc
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
