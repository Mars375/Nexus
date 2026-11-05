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
from nexus.models import Run
from nexus.runs import service
from nexus.runs.states import ACTIVE, CANCELLABLE, STATUS_OF_EVENT
from nexus.tasks.rules import RuleViolation

log = logging.getLogger("nexus.runs")

POLL_SECONDS = 2.0
CURSOR_MAX = 512
# Transient: the run is left as it was and retried on the next tick.
TRANSIENT = (StaleDataError, OperationalError)


def info_of(run: Run) -> RunInfo:
    return RunInfo(
        run_id=run.id, ref=run.ref, task=f"nx-task-{run.task_id}", executor=run.executor,
        agent=run.agent, brief=run.brief, workdir=run.workdir, external_ref=run.external_ref,
        status=run.status, native_status=run.native_status, watch_cursor=run.watch_cursor,
    )


def _publish(
    factory: sessionmaker[Session], run: RunInfo, origin: str, event: RunEvent, event_id: str
) -> str | None:
    """Publish one fact of the run; the effective event kind, or None when it was not kept.

    A refusal of the protocol (anti-noise 409 included) never stops the supervisor: the fact is
    skipped and only its code is logged, never a message that could repeat a received value.
    A transient database failure propagates: the run is retried whole.
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
            return None
        return stored.kind


def _finish(factory: sessionmaker[Session], run_id: int, **changes: str | None) -> None:
    with factory() as session:
        service.update_run(session, session.get(Run, run_id), **changes)
        session.commit()


def _own_event(kind: str, subject: str, **payload: object) -> RunEvent:
    return RunEvent(seq=0, at=now(), kind=kind, subject=subject, payload=dict(payload))


def mark_lost(factory: sessionmaker[Session]) -> None:
    """At startup: every run that was being watched becomes `unknown`, with an event (ADR-005).

    Nothing is relaunched or guessed: a human decides what to do with it.
    """
    with factory() as session:
        lost = [info_of(r) for r in session.scalars(select(Run).where(Run.status.in_(ACTIVE)))]
    for run in lost:
        event = _own_event(
            "unknown", "suivi perdu au redémarrage de Nexus", last_check_at=now().isoformat()
        )
        # Event first, then status: a crash in between is replayed (the event id is fixed).
        _publish(factory, run, "nexus", event, f"{run.ref}-lost")
        _finish(factory, run.run_id, status="unknown")


def _safe_cursor(cursor: str | None) -> str | None:
    """An opaque position only: a cursor that looks like a secret or is huge is not stored."""
    if cursor is None or len(cursor) > CURSOR_MAX or secrets.redact(cursor)[1]:
        return None
    return cursor


def _cancel(factory: sessionmaker[Session], adapter: Adapter, run: RunInfo) -> None:
    try:
        adapter.cancel(run)
    except Exception as exc:  # the adapter's message could carry a secret: type only
        log.warning("annulation de %s : %s", run.ref, type(exc).__name__)
    # `failed` closes the run in the event journal, so the executor may open another one.
    event = _own_event("failed", "run annulé", cause="annulé à la demande d'un humain")
    _publish(factory, run, adapter.name, event, f"{run.ref}-cancelled")
    _finish(factory, run.run_id, status="cancelled")


def _dispatch(factory: sessionmaker[Session], adapter: Adapter, run: RunInfo) -> RunInfo | None:
    """Hand the work over once. None when it failed (the run is then `failed`)."""
    try:
        sent = adapter.dispatch(run)
    except Exception as exc:
        log.warning("lancement de %s : %s", run.ref, type(exc).__name__)
        event = _own_event("failed", "lancement impossible", cause="lancement impossible")
        _publish(factory, run, adapter.name, event, f"{run.ref}-failed")
        _finish(factory, run.run_id, status="failed")
        return None
    _finish(factory, run.run_id, external_ref=sent.external_ref, native_status=sent.native_status)
    with factory() as session:
        return info_of(session.get(Run, run.run_id))


def _watch(factory: sessionmaker[Session], adapter: Adapter, run: RunInfo) -> None:
    result = adapter.watch(run)
    status = None
    for event in sorted(result.events, key=lambda e: e.seq):
        kept = _publish(factory, run, adapter.name, event, f"{run.ref}-{event.seq}")
        status = STATUS_OF_EVENT.get(kept or "", status)
    _finish(
        factory, run.run_id, status=status, native_status=result.native_status,
        watch_cursor=_safe_cursor(result.cursor),
    )


def _step(factory: sessionmaker[Session], registry: AdapterRegistry, run_id: int) -> None:
    with factory() as session:
        row = session.get(Run, run_id)
        run, cancel_requested = info_of(row), row.cancel_requested_at is not None
    adapter = registry.get(run.executor)
    if adapter is None:
        return  # no adapter in this process: the run is left alone, not guessed at
    if cancel_requested and run.status in CANCELLABLE:
        _cancel(factory, adapter, run)
        return
    if run.status not in ACTIVE:
        return
    if run.status == "dispatched" and run.external_ref is None:
        dispatched = _dispatch(factory, adapter, run)
        if dispatched is None:
            return
        run = dispatched
    _watch(factory, adapter, run)


def tick(factory: sessionmaker[Session], registry: AdapterRegistry) -> None:
    """One pass over the runs that need attention. Never raises: it is a loop body."""
    with factory() as session:
        ids = list(session.scalars(
            select(Run.id).where(or_(
                Run.status.in_(ACTIVE),
                (Run.status == "unknown") & Run.cancel_requested_at.is_not(None),
            )).order_by(Run.id)
        ))
    for run_id in ids:
        try:
            _step(factory, registry, run_id)
        except TRANSIENT:
            log.info("run %s : conflit d'écriture, nouvelle tentative au prochain tour", run_id)
        except Exception as exc:
            # The adapter's own failure: logged by type, the run is retried next time.
            log.warning("suivi du run %s : %s", run_id, type(exc).__name__)


async def loop(factory: sessionmaker[Session], registry: AdapterRegistry) -> None:
    """The lifespan task: sleep first, like the backup loop, then one tick in a worker thread."""
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            await asyncio.to_thread(tick, factory, registry)
        except Exception:
            log.exception("tour du superviseur de runs échoué")
