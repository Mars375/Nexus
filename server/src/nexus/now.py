"""Vue Maintenant (#6) : un instantané de ce qui se passe, lu en une seule fois.

Tout vient de nexus.db, dans une seule session : les sections ne peuvent pas se contredire
parce qu'elles auraient été lues à des instants différents.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import get_args

from fastapi import APIRouter
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from nexus.actors import Agent
from nexus.approvals.service import consequence_of, effective_status, options_of
from nexus.auth.deps import Authenticated
from nexus.clock import now
from nexus.events.service import RUN_CLOSERS
from nexus.models import Approval, Event, Task, TaskHistory
from nexus.tasks.api import SessionDep

router = APIRouter(prefix="/api/now", tags=["maintenant"], dependencies=Authenticated)

AGENT_ORDER: tuple[str, ...] = get_args(Agent)
WINDOW = timedelta(days=7)
DONE_LIMIT = 5
ASK_KINDS = ("question", "needs_human")
HUMAN = "loic"


def _ref(task_id: int | None) -> str | None:
    return f"nx-task-{task_id}" if task_id is not None else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _since(row: TaskHistory | None) -> datetime | None:
    return row.at if row is not None else None


def _transitions(session: Session, tasks: list[Task], status: str) -> dict[int, TaskHistory]:
    """Par tâche, la ligne d'historique du dernier passage au statut donné : quand et par qui.

    Une seule requête pour toutes les tâches (aucune colonne ne garde cet instant).
    """
    found: dict[int, TaskHistory] = {}
    if not tasks:
        return found
    rows = session.scalars(
        select(TaskHistory).where(TaskHistory.task_id.in_([t.id for t in tasks]))
        .order_by(TaskHistory.id.desc())
    )
    for row in rows:
        if row.task_id in found:
            continue
        change = (row.changes or {}).get("status")
        if isinstance(change, list) and len(change) == 2 and change[1] == status:
            found[row.task_id] = row
    return found


def _open_runs(session: Session) -> dict[str, Event]:
    """Par agent, le `working` le plus récent dont le run n'est pas clos.

    Même règle que `events.service._runs` : une clôture ne ferme que le run qu'elle nomme,
    pour cet agent et cette tâche, et pour de bon (un `working` tardif ne le rouvre pas).
    Le filtre se fait en SQL : seuls les `working` encore ouverts sont lus, pas l'historique.
    """
    closer = aliased(Event)
    closed = (
        select(closer.id).where(
            closer.kind.in_(RUN_CLOSERS), closer.actor == Event.actor,
            closer.task_id.is_not_distinct_from(Event.task_id),
            closer.run_ref.is_not_distinct_from(Event.run_ref),
        ).exists()
    )
    latest = (
        select(func.max(Event.id)).where(Event.kind == "working", ~closed).group_by(Event.actor)
    )
    return {e.actor: e for e in session.scalars(select(Event).where(Event.id.in_(latest)))}


def _asks(session: Session, measured: datetime, cutoff: datetime) -> list[dict]:
    """Requests addressed to the human, with their approval (ADR-019, D6, D7).

    Listed: the pending ones, whatever their age, and the treated ones of the last 7 days: from
    their decision, or from their deadline when expired. A request from before migration 0004 has
    no approval (`approval` is null): it keeps the rule of #6, received within the last 7 days.
    One query, with the request, its approval and its response event.
    """
    response = aliased(Event)
    rows = session.execute(
        select(Event, Approval, response)
        .outerjoin(Approval, Approval.request_event_id == Event.id)
        .outerjoin(response, response.id == Approval.response_event_id)
        .where(Event.kind.in_(ASK_KINDS), or_(
            # Pending of any age; the expired ones (stored pending) only inside the window.
            and_(Approval.status == "pending",
                 or_(Approval.expires_at.is_(None), Approval.expires_at >= cutoff)),
            and_(Approval.id.is_(None), Event.received_at >= cutoff),
            response.received_at >= cutoff,
        ))
        # `received_at` (what Nexus received), not `at` (the declared time).
        .order_by(Event.received_at.desc(), Event.id.desc())
    )
    asks = []
    for e, approval, answer in rows:
        if HUMAN not in (e.needs or []):
            continue
        status = effective_status(approval, measured) if approval else None
        if status == "expired" and approval.expires_at.astimezone(UTC) < cutoff:
            continue  # expired more than 7 days ago
        asks.append({
            "event": e.ref, "agent": e.actor, "kind": e.kind, "subject": e.subject,
            "task": _ref(e.task_id), "at": _iso(e.at), "received_at": _iso(e.received_at),
            "body": e.body, "options": options_of(e.payload),
            "consequence": consequence_of(e.payload),
            "approval": None if approval is None else {
                "ref": approval.ref, "status": status, "expires_at": _iso(approval.expires_at),
                "decided_by": answer.actor if answer else None,
                "decided_at": _iso(answer.received_at) if answer else None,
            },
        })
    return asks


def snapshot(session: Session) -> dict:
    # pysqlite n'ouvre aucune transaction avant un SELECT : sans BEGIN explicite, chaque lecture
    # verrait son propre état de la base. Une seule transaction de lecture = un seul instant.
    session.connection().exec_driver_sql("BEGIN")
    measured = now()
    tasks = {t.id: t for t in session.scalars(select(Task))}

    main = next((t for t in tasks.values()
                 if t.status == "in_progress" and t.operation_role == "main"
                 and t.human_owner == HUMAN), None)
    operation = None if main is None else {
        "task": _ref(main.id), "title": main.title, "lead_agent": main.lead_agent,
        "since": _iso(_since(_transitions(session, [main], "in_progress").get(main.id))),
        "next_action": main.next_action, "due_at": _iso(main.due_at),
    }
    auxiliaries = [
        {"task": _ref(t.id), "title": t.title}
        for t in sorted(tasks.values(), key=lambda t: t.id)
        if t.operation_role == "auxiliary" and t.status == "in_progress"  # PRD §156 : en cours
    ]

    runs = _open_runs(session)
    agents = []
    for agent in AGENT_ORDER:
        run = runs.get(agent)
        task = tasks.get(run.task_id) if run is not None and run.task_id is not None else None
        agents.append({
            "agent": agent, "state": "run" if run is not None else "idle",
            "task": _ref(run.task_id) if run is not None else None,
            "title": task.title if task is not None else None,
            "run": run.run_ref if run is not None else None,
            "since": _iso(run.at) if run is not None else None,
        })

    # En UTC : une durée réelle, même autour d'un changement d'heure (checklist §7).
    cutoff = measured.astimezone(UTC) - WINDOW
    asks = _asks(session, measured, cutoff)

    blocked_tasks = [t for t in tasks.values() if t.status == "blocked"]
    entered_blocked = _transitions(session, blocked_tasks, "blocked")
    blocked = [(t, _since(entered_blocked.get(t.id))) for t in blocked_tasks]
    blocked.sort(key=lambda pair: (pair[1] is None, pair[1] or measured))
    blocks = [{
        "task": _ref(t.id), "title": t.title, "cause": t.block_cause, "since": _iso(since),
        "follow_up_at": _iso(t.follow_up_at), "lead_agent": t.lead_agent,
    } for t, since in blocked]

    # Un changement de statut touche `updated_at` : une tâche plus ancienne que la fenêtre n'a
    # pas pu passer à done dedans, inutile de relire son historique.
    done_tasks = [t for t in tasks.values() if t.status == "done" and t.updated_at >= cutoff]
    entered_done = _transitions(session, done_tasks, "done")
    finished = [(t, entered_done.get(t.id)) for t in done_tasks]
    recent = [(t, row) for t, row in finished if row is not None and row.at >= cutoff]
    recent.sort(key=lambda pair: (pair[1].at, pair[0].id), reverse=True)
    # `agent` : qui a clos la tâche (l'historique), pas son agent principal (ADR-005).
    done = [{
        "task": _ref(t.id), "title": t.title, "agent": row.actor,
        "evidence": list(t.evidence or []), "at": _iso(row.at),
    } for t, row in recent[:DONE_LIMIT]]

    return {
        "source": "nexus.db", "measured_at": _iso(measured),
        "operation": operation, "auxiliaries": auxiliaries, "agents": agents,
        "asks": asks, "blocks": blocks, "done": done,
    }


@router.get("")
def read_now(session: SessionDep) -> dict:
    """Ce qui se passe en ce moment : lu en une fois, avec sa provenance (ADR-005)."""
    return snapshot(session)
