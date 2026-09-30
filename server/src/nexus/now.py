"""Vue Maintenant (#6) : un instantané de ce qui se passe, lu en une seule fois.

Tout vient de nexus.db, dans une seule session : les sections ne peuvent pas se contredire
parce qu'elles auraient été lues à des instants différents.
"""

from __future__ import annotations

from datetime import datetime, timedelta
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


def _entered(session: Session, task: Task, status: str) -> datetime | None:
    """Instant du dernier passage de la tâche au statut donné (aucune colonne ne le garde)."""
    rows = session.scalars(
        select(TaskHistory).where(TaskHistory.task_id == task.id).order_by(TaskHistory.id.desc())
    )
    for row in rows:
        change = (row.changes or {}).get("status")
        if isinstance(change, list) and len(change) == 2 and change[1] == status:
            return row.at
    return None


def _open_runs(session: Session) -> dict[str, Event]:
    """Par agent, le `working` le plus récent dont le run n'est pas clos.

    Même règle que `events.service._runs` : une clôture ne ferme que le run qu'elle nomme,
    pour cet agent et cette tâche.
    """
    events = session.scalars(
        select(Event).where(Event.kind.in_(("working", *RUN_CLOSERS))).order_by(Event.id.desc())
    )
    closed: set[tuple[str, int | None, str | None]] = set()
    runs: dict[str, Event] = {}
    for event in events:
        key = (event.actor, event.task_id, event.run_ref)
        if event.kind in RUN_CLOSERS:
            closed.add(key)
        elif event.actor not in runs and key not in closed:
            runs[event.actor] = event
    return runs


def snapshot(session: Session) -> dict:
    measured = now()
    tasks = {t.id: t for t in session.scalars(select(Task))}

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
        if t.operation_role == "auxiliary" and t.status not in ("done", "dropped")
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

    cutoff = measured - WINDOW
    asks = [{
        "event": e.ref, "agent": e.actor, "kind": e.kind, "subject": e.subject,
        "task": _ref(e.task_id), "at": _iso(e.at),
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

    finished = [(t, _entered(session, t, "done")) for t in tasks.values() if t.status == "done"]
    recent = [(t, at) for t, at in finished if at is not None and at >= cutoff]
    recent.sort(key=lambda pair: (pair[1], pair[0].id), reverse=True)
    done = [{
        "task": _ref(t.id), "title": t.title, "agent": t.lead_agent,
        "evidence": list(t.evidence or []), "at": _iso(at),
    } for t, at in recent[:DONE_LIMIT]]

    return {
        "source": "nexus.db", "measured_at": _iso(measured),
        "operation": operation, "auxiliaries": auxiliaries, "agents": agents,
        "asks": asks, "blocks": blocks, "done": done,
    }


@router.get("")
def read_now(session: SessionDep) -> dict:
    """Ce qui se passe en ce moment : lu en une fois, avec sa provenance (ADR-005)."""
    return snapshot(session)
