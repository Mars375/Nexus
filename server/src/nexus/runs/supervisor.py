"""The run supervisor (ADR-023, D3): dispatch, watch, cancel, and lose track on restart.

It runs inside the server process (a task of the app's lifespan, like the node and backup loops).
Adapters block, so a tick runs in a worker thread. Every step is idempotent: a fact is published
under an id derived from the run and the fact (`nx-run-<n>-<seq>`) with the instant the executor
gave, so reading it again is a read-back, and a crash at any point replays safely. A transient
failure leaves the run as it was and is retried on the next tick.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from nexus import secrets
from nexus.adapters.base import Adapter, RunEvent, RunInfo
from nexus.adapters.registry import AdapterRegistry
from nexus.clock import now
from nexus.events import service as events
from nexus.events.rules import Envelope
from nexus.events.runs import RUN_CLOSERS
from nexus.models import Event, Run, Task
from nexus.runs import rules, service
from nexus.runs.states import CANCELLABLE, SETTLED, STATUS_OF_EVENT, WATCHED
from nexus.tasks.rules import RuleViolation

log = logging.getLogger("nexus.runs")

POLL_SECONDS = 2.0
CURSOR_MAX = 512
# `native_status` written before the executor is reached: a launch of unknown outcome.
DISPATCHING = "dispatching"


def _transient(exc: Exception) -> bool:
    """A version conflict or a busy/locked SQLite database: the run is left as it was and
    retried on the next tick. Any other database error is a real fault (also retried, but loud).
    """
    if isinstance(exc, StaleDataError):
        return True
    text = str(getattr(exc, "orig", exc)).lower()
    return isinstance(exc, OperationalError) and ("locked" in text or "busy" in text)


def info_of(run: Run) -> RunInfo:
    return RunInfo(
        run_id=run.id, ref=run.ref, task=f"nx-task-{run.task_id}", executor=run.executor,
        agent=run.agent, brief=run.brief, workdir=run.workdir, external_ref=run.external_ref,
        status=run.status, native_status=run.native_status, watch_cursor=run.watch_cursor,
        version=run.version,
    )


def _publish(
    factory: sessionmaker[Session],
    run: RunInfo,
    origin: str,
    event: RunEvent,
    event_id: str,
    refusals: list[str] | None = None,
) -> str | None:
    """Publish one fact of the run; the effective event kind, or None when it was not kept.

    A refusal of the protocol (anti-noise 409 included) never stops the supervisor: the fact is
    skipped and only its code is logged, never a message that could repeat a received value.
    A transient database failure propagates: the run is retried whole. The code of a refusal
    other than noise is appended to `refusals`, so a caller can avoid moving past a lost fact.
    """
    envelope = Envelope(
        actor=run.executor, kind=event.kind, subject=event.subject, task=run.task, run=run.ref,
        body=event.body, payload=dict(event.payload), evidence=list(event.evidence),
        needs=list(event.needs),
    )
    with factory() as session:
        try:
            stored, _ = events.publish(session, envelope, event_id, event.at, origin=origin)
            session.commit()
        except RuleViolation as exc:
            session.rollback()
            if exc.code != "noise":
                log.warning("événement de %s refusé (%s)", run.ref, exc.code)
                if refusals is not None:
                    refusals.append(exc.code)
            return None
        return stored.kind


def _finish(
    factory: sessionmaker[Session], run: RunInfo, *, strict: bool = False, **changes: str | None
) -> tuple[RunInfo, bool]:
    """Write what was learned about the run; returns its fresh snapshot and cancel flag.

    A status is written only from the state the supervisor started from: if a human changed the
    run since (a cancel), `StaleDataError` is raised and the run is read again on the next tick,
    where the cancel wins. Other facts (reference, cursor) are written whatever happened, unless
    `strict`: the launch marker must not slip in after a cancel, or the executor would be started.
    """
    with factory() as session:
        row = session.get(Run, run.run_id)
        if (changes.get("status") is not None or strict) and row.version != run.version:
            raise StaleDataError("run modifié depuis sa lecture")
        service.update_run(session, row, **changes)
        session.commit()
        return info_of(row), row.cancel_requested_at is not None


def _load(factory: sessionmaker[Session], run_id: int) -> tuple[RunInfo, bool]:
    with factory() as session:
        row = session.get(Run, run_id)
        return info_of(row), row.cancel_requested_at is not None


def _own_event(kind: str, subject: str, **payload: object) -> RunEvent:
    return RunEvent(seq=0, at=now(), kind=kind, subject=subject, payload=dict(payload))


def _journal_end(factory: sessionmaker[Session], run: RunInfo) -> str | None:
    """The status the journal already gives the run, from its latest closing event, else None.

    Covers an end published through the API by the executor itself, and one published by the
    supervisor just before a crash: the run follows the journal, it never contradicts it.
    """
    with factory() as session:
        last = session.execute(
            select(Event.kind, Event.actor_event_id)
            .where(Event.run_ref == run.ref, Event.actor == run.executor,
                   Event.task_id == int(run.task.removeprefix("nx-task-")),
                   Event.kind.in_(RUN_CLOSERS))
            .order_by(Event.id.desc()).limit(1)
        ).first()
    if last is None:
        return None
    # The closing `failed` of a cancel is the supervisor's own: the run is `cancelled`, not failed.
    return "cancelled" if last[1] == f"{run.ref}-cancelled" else STATUS_OF_EVENT.get(last[0])


def mark_lost(factory: sessionmaker[Session]) -> None:
    """At startup: every run that was being watched becomes `unknown`, with an event (ADR-005).

    A run whose end is already in the journal keeps that end. Nothing is relaunched or guessed:
    a human decides what to do with the others.
    """
    with factory() as session:
        ids = list(session.scalars(select(Run.id).where(Run.status.in_(WATCHED))))
    for run_id in ids:
        run, _ = _load(factory, run_id)
        ended = _journal_end(factory, run)
        if ended is not None:
            _finish(factory, run, status=ended)
            continue
        event = _own_event(
            "unknown", "suivi perdu au redémarrage de Nexus", last_check_at=now().isoformat()
        )
        # Event first, then status: a crash in between is replayed (the event id is fixed).
        _publish(factory, run, "nexus", event, f"{run.ref}-lost")
        _finish(factory, run, status="unknown")


def _safe_cursor(cursor: str | None) -> str | None:
    """An opaque position only: a cursor that looks like a secret or is huge is not stored."""
    if cursor is None or len(cursor) > CURSOR_MAX or secrets.redact(cursor)[1]:
        return None
    return cursor


def _fail(factory: sessionmaker[Session], adapter: Adapter, run: RunInfo, cause: str) -> None:
    event = _own_event("failed", cause, cause=cause)
    _publish(factory, run, adapter.name, event, f"{run.ref}-failed")
    _finish(factory, run, status="failed")


def _cancel(factory: sessionmaker[Session], adapter: Adapter | None, run: RunInfo) -> None:
    """Stop the executor, then close the run. No adapter: the run was never launched."""
    if adapter is not None:
        try:
            adapter.cancel(run)
        except Exception as exc:  # the message could carry a secret: type only
            # Still possibly running: the run stays open and the cancel is retried next tick.
            log.warning("annulation de %s : %s", run.ref, type(exc).__name__)
            return
    # `failed` closes the run in the event journal, so the executor may open another one.
    event = _own_event("failed", "run annulé", cause="annulé à la demande d'un humain")
    _publish(factory, run, adapter.name if adapter else "nexus", event, f"{run.ref}-cancelled")
    _finish(factory, run, status="cancelled")


def _launched(run: RunInfo) -> bool:
    """The executor may have been reached: a reference, or the marker written before the call."""
    return run.external_ref is not None or run.native_status == DISPATCHING


def _ready_code(factory: sessionmaker[Session], run: RunInfo) -> str | None:
    """Why the task could no longer start (a human finished it since), or None if it can."""
    with factory() as session:
        task = session.get(Task, int(run.task.removeprefix("nx-task-")))
        try:
            rules.check_task_ready(session, task)
        except RuleViolation as exc:
            return exc.code
    return None


def _dispatch(
    factory: sessionmaker[Session], adapter: Adapter, run: RunInfo
) -> tuple[RunInfo, bool] | None:
    """Hand the work over once; the fresh snapshot and cancel flag, or None when it failed.

    The marker is written BEFORE the call: if the process dies or the write after it fails, the
    outcome is uncertain and the launch is never repeated (see `_step`).
    """
    run, _ = _finish(factory, run, strict=True, native_status=DISPATCHING)
    try:
        sent = adapter.dispatch(run)
    except Exception as exc:
        log.warning("lancement de %s : %s", run.ref, type(exc).__name__)
        _fail(factory, adapter, run, "lancement impossible")
        return None
    if not isinstance(sent.external_ref, str) or secrets.redact(sent.external_ref)[1]:
        # A reference the scanner would mask cannot be stored usable: stop the executor with the
        # real one, which only lives in memory, and fail the run.
        try:
            adapter.cancel(replace(run, external_ref=sent.external_ref))
        except Exception as exc:
            log.warning("annulation de %s : %s", run.ref, type(exc).__name__)
        _fail(factory, adapter, run, "référence de l'exécutant inutilisable")
        return None
    try:
        return _finish(
            factory, run, external_ref=sent.external_ref,
            native_status=sent.native_status or "started",
        )
    except Exception as exc:
        # The work started but its reference could not be written (#168). The reference only
        # lives here: stop the work with it now rather than lose the means to stop it later.
        log.warning("référence de %s non enregistrée : %s", run.ref, type(exc).__name__)
        try:
            adapter.cancel(replace(run, external_ref=sent.external_ref))
        except Exception as cancel_exc:
            log.warning("annulation de %s : %s", run.ref, type(cancel_exc).__name__)
        _fail(factory, adapter, run, "référence de l'exécutant non enregistrée")
        return None


def _watch(factory: sessionmaker[Session], adapter: Adapter, run: RunInfo) -> None:
    result = adapter.watch(run)
    status = None
    refusals: list[str] = []
    for event in sorted(result.events, key=lambda e: e.seq):
        kept = _publish(
            factory, run, adapter.name, event, f"{run.ref}-{event.seq}", refusals=refusals
        )
        step = STATUS_OF_EVENT.get(kept or "")
        if step is not None and status not in SETTLED:
            status = step  # the journal closes a run for good: a late `working` reopens nothing
    ended = _journal_end(factory, run)
    if ended is not None:
        status = ended  # a close published meanwhile (API, earlier tick) wins over what we saw
    _finish(
        factory, run, status=status, native_status=result.native_status,
        # A refused fact (an id already taken, say) is not moved past: the adapter is read again
        # from the same place on the next tick, and the cause is in the log.
        watch_cursor=None if refusals else _safe_cursor(result.cursor),
    )


def _step(factory: sessionmaker[Session], registry: AdapterRegistry, run_id: int) -> None:
    run, cancel_requested = _load(factory, run_id)
    adapter = registry.get(run.executor)
    if cancel_requested and run.status in CANCELLABLE:
        if not _launched(run):
            _cancel(factory, None, run)  # nothing to stop: no call to the executor, whoever it is
        elif adapter is not None:
            _cancel(factory, adapter, run)
        return
    if adapter is None:
        return  # no adapter in this process: the run is left alone, not guessed at
    if run.status not in WATCHED:
        return
    ended = _journal_end(factory, run)
    if ended is not None:
        _finish(factory, run, status=ended)
        return
    if run.status == "dispatched" and run.external_ref is None:
        if run.native_status == DISPATCHING:
            # A previous launch may have started the work and lost its trace: never repeat it.
            event = _own_event("unknown", "lancement incertain", last_check_at=now().isoformat())
            _publish(factory, run, adapter.name, event, f"{run.ref}-uncertain")
            _finish(factory, run, status="unknown")
            return
        code = _ready_code(factory, run)
        if code is not None:
            _fail(factory, adapter, run, f"la tâche ne peut plus démarrer ({code})")
            return
        dispatched = _dispatch(factory, adapter, run)
        if dispatched is None:
            return
        run, cancel_requested = dispatched
        if cancel_requested:  # clicked while the executor was being reached: stop it, no watch
            _cancel(factory, adapter, run)
            return
    _watch(factory, adapter, run)


def tick(factory: sessionmaker[Session], registry: AdapterRegistry) -> None:
    """One pass over the runs that need attention. Never raises: it is a loop body."""
    with factory() as session:
        ids = list(session.scalars(
            select(Run.id).where(or_(
                Run.status.in_(WATCHED),
                (Run.status == "unknown") & Run.cancel_requested_at.is_not(None),
            )).order_by(Run.id)
        ))
    for run_id in ids:
        try:
            _step(factory, registry, run_id)
        except Exception as exc:
            if _transient(exc):
                log.info("run %s : conflit d'écriture, nouvelle tentative au prochain tour", run_id)
                continue
            # Anything else (an adapter, a database fault): logged by type only, never the
            # statement, its parameters or the message; the run is retried next time.
            log.warning("suivi du run %s : %s", run_id, type(exc).__name__)


async def loop(factory: sessionmaker[Session], registry: AdapterRegistry) -> None:
    """The lifespan task: sleep first, like the backup loop, then one tick in a worker thread."""
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            await asyncio.to_thread(tick, factory, registry)
        except Exception:
            log.exception("tour du superviseur de runs échoué")
