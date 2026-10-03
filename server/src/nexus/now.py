"""Vue Maintenant (#6) : un instantané de ce qui se passe, lu en une seule fois.

Tout vient de nexus.db, dans une seule session : les sections ne peuvent pas se contredire
parce qu'elles auraient été lues à des instants différents.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import get_args

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.actors import Agent
from nexus.clock import now
from nexus.events.service import RUN_CLOSERS
from nexus.models import Event, Task, TaskHistory
from nexus.tasks.api import SessionDep

router = APIRouter(prefix="/api/now", tags=["maintenant"])

AGENT_ORDER: tuple[str, ...] = get_args(Agent)
WINDOW = timedelta(days=7)
DONE_LIMIT = 5
ASK_KINDS = ("question", "needs_human")
HUMAN = "loic"


def _ref(task_id: int | None) -> str | None:
    return f"nx-task-{task_id}" if task_id is not None else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _transition(session: Session, task: Task, status: str) -> TaskHistory | None:
    """Ligne d'historique du dernier passage de la tâche au statut donné : quand et par qui."""
    rows = session.scalars(
        select(TaskHistory).where(TaskHistory.task_id == task.id).order_by(TaskHistory.id.desc())
    )
    for row in rows:
        change = (row.changes or {}).get("status")
        if isinstance(change, list) and len(change) == 2 and change[1] == status:
            return row
    return None


def _entered(session: Session, task: Task, status: str) -> datetime | None:
    """Instant du dernier passage de la tâche au statut donné (aucune colonne ne le garde)."""
    row = _transition(session, task, status)
    return row.at if row is not None else None


def _open_runs(session: Session) -> dict[str, Event]:
    """Par agent, le `working` le plus récent dont le run n'est pas clos.

    Même règle que `events.service._runs` : une clôture ne ferme que le run qu'elle nomme,
    pour cet agent et cette tâche.
    """
    events = list(session.scalars(
        select(Event).where(Event.kind.in_(("working", *RUN_CLOSERS))).order_by(Event.id.desc())
    ))
    # Les clôtures sur tout l'historique d'abord : un `working` tardif (id plus grand que sa
    # clôture) ne rouvre pas un run déjà clos.
    closed = {(e.actor, e.task_id, e.run_ref) for e in events if e.kind in RUN_CLOSERS}
    runs: dict[str, Event] = {}
    for event in events:
        key = (event.actor, event.task_id, event.run_ref)
        if event.kind == "working" and event.actor not in runs and key not in closed:
            runs[event.actor] = event
    return runs


def snapshot(session: Session) -> dict:
    # pysqlite n'ouvre aucune transaction avant un SELECT : sans BEGIN explicite, chaque lecture
    # verrait son propre état de la base. Une seule transaction de lecture = un seul instant.
    session.connection().exec_driver_sql("BEGIN")
    measured = now()
    tasks ={t.id: t for t in session.scalars(select(Task))}

    main = next((t for t in tasks.values()
                 if t.status == "in_progress" and t.operation_role == "main"
                 and t.human_owner == HUMAN), None)
    operation = None if main is None else {
        "task": _ref(main.id), "title": main.title, "lead_agent": main.lead_agent,
        "since": _iso(_entered(session, main, "in_progress")),
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
    # Fenêtre et tri sur `received_at` (ce que Nexus a reçu), pas sur `at` (l'heure déclarée).
    asks = [{
        "event": e.ref, "agent": e.actor, "kind": e.kind, "subject": e.subject,
        "task": _ref(e.task_id), "at": _iso(e.at),
        "received_at": _iso(e.received_at),
    } for e in session.scalars(
        select(Event).where(Event.kind.in_(ASK_KINDS), Event.received_at >= cutoff)
        .order_by(Event.received_at.desc(), Event.id.desc())
    ) if HUMAN in (e.needs or [])]

    blocked = [
        (t, _entered(session, t, "blocked")) for t in tasks.values() if t.status == "blocked"
    ]
    blocked.sort(key=lambda pair: (pair[1] is None, pair[1] or measured))
    blocks = [{
        "task": _ref(t.id), "title": t.title, "cause": t.block_cause, "since": _iso(since),
        "follow_up_at": _iso(t.follow_up_at), "lead_agent": t.lead_agent,
    } for t, since in blocked]

    # Un changement de statut touche `updated_at` : une tâche plus ancienne que la fenêtre n'a
    # pas pu passer à done dedans, inutile de relire son historique.
    finished = [
        (t, _transition(session, t, "done")) for t in tasks.values()
        if t.status == "done" and t.updated_at >= cutoff
    ]
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
