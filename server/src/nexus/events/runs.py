"""Read-only run queries shared by the second-run guard and the stale-run check of an event."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.models import Event, Task

# Ce qui clôt ou suspend un run : après l'un d'eux, l'agent peut en ouvrir un autre.
RUN_CLOSERS = frozenset({"done", "review", "failed", "handoff", "blocked"})


def _runs(
    session: Session, actor: str, task: Task, before_id: int | None = None
) -> tuple[str | None, set[str | None]]:
    """Runs de l'agent sur la tâche : (référence du run actif ou None, références closes).

    Une clôture ne ferme que le run qu'elle nomme, et pour de bon : une clôture tardive d'un
    ancien run ne libère pas le run actif, et un `working` tardif d'un run clos ne le rouvre pas.
    """
    query = select(Event).where(Event.actor == actor, Event.task_id == task.id)
    if before_id is not None:
        query = query.where(Event.id < before_id)
    history = list(session.scalars(query.order_by(Event.id.desc())))
    closed = {e.run_ref for e in history if e.kind in RUN_CLOSERS}
    for previous in history:
        if previous.kind == "working" and previous.run_ref not in closed:
            return previous.run_ref, closed
    return None, closed


def _stale_run(session: Session, event: Event, task: Task) -> str | None:
    """Si l'événement ne vise pas le run actif de l'agent, la raison de l'ignorer.

    Ex. : `done(r1)` arrivé après `working(r2)` ne clôt pas la tâche pendant que r2 tourne ;
    un `done` sans run non plus, puisque rien ne dit qu'il ne vient pas de r1.
    """
    active, closed = _runs(session, event.actor, task, before_id=event.id)
    if event.kind == "working":
        if event.run_ref in closed:
            return f"le run {event.run_ref} de {event.actor} est déjà clos : ouvre un nouveau run"
        return None
    if active is None or event.run_ref == active:
        # Pas d'autre run en cours : une clôture tardive d'un run déjà clos (done(r1) après
        # handoff(r1)) ne rejoue pas pour autant son effet.
        if event.run_ref is not None and event.run_ref in closed:
            return f"le run {event.run_ref} de {event.actor} est déjà clos : ouvre un nouveau run"
        return None
    if event.run_ref is None:
        return (
            f"ne nomme aucun run, alors que le run actif de {event.actor} est {active} : "
            "précise le run concerné"
        )
    return (
        f"concerne le run {event.run_ref}, alors que le run actif de {event.actor} "
        f"est {active}"
    )
