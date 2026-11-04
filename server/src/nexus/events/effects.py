"""Effects of an event on its task: each runs in its own SAVEPOINT and is reported, not raised."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from nexus.events import rules
from nexus.events.rules import Envelope
from nexus.events.runs import _stale_run
from nexus.models import Event, Task
from nexus.permissions import Forbidden
from nexus.tasks import service as tasks
from nexus.tasks.rules import RuleViolation

# Returned by an effect that finds nothing left to do (it wrote nothing).
ALREADY = object()


EFFECT_ATTEMPTS = 3


def _apply_effects(session: Session, event: Event, e: Envelope, task: Task) -> list[dict]:
    """Traduit l'événement en mutations de la tâche, chacune tentée dans un point de sauvegarde."""
    effects: list[dict] = []

    def attempt(
        action: str, fn, watched: tuple[str, ...] = (), unchanged: str = ""
    ) -> str:
        """Try `fn` in a savepoint, retrying on a version conflict. Returns what happened:
        "applied", "refused" (the reason is consigned), "gave_up", or "already" when `fn`
        reports that nothing was left to do (it wrote nothing)."""
        # Un conflit de version (la tâche a changé depuis sa lecture) n'est pas un refus : on
        # relit la tâche et on retente, les règles jugeant alors son état à jour.
        for _ in range(EFFECT_ATTEMPTS):
            savepoint = session.begin_nested()
            try:
                before = [getattr(task, f) for f in watched]
                outcome = fn()
                if outcome is ALREADY:
                    savepoint.rollback()
                    return "already"
                if watched and before == [getattr(task, f) for f in watched]:
                    # update_task writes nothing when nothing differs: not an applied effect.
                    raise RuleViolation("effect_unchanged", unchanged)
                savepoint.commit()
                effects.append({"action": action, "applied": True})
                return "applied"
            except StaleDataError:
                savepoint.rollback()
                session.refresh(task)
            except (RuleViolation, Forbidden, IntegrityError) as exc:
                # A right the actor never has (ADR-020) is refused like a broken rule: the event
                # stays recorded, only its effect on the task is not applied.
                savepoint.rollback()
                session.refresh(task)
                message = exc.message if isinstance(exc, RuleViolation | Forbidden) else (
                    "conflit en base"
                )
                effects.append({"action": action, "applied": False, "reason": message})
                return "refused"
        effects.append({"action": action, "applied": False,
                        "reason": "conflit en base : trop d'écritures concurrentes"})
        return "gave_up"

    def move(target: str, **kwargs: Any) -> None:
        stale = _stale_run(session, event, task)
        if stale:
            effects.append({"action": f"status:{target}", "applied": False, "reason": stale})
            return
        evidence = kwargs.get("evidence")

        def change() -> object:
            # Judged on every attempt, on the task as just read: after a version conflict the
            # task may already be in the target status (a defence: see the design, §2).
            session.refresh(task)
            if task.status == target:
                return ALREADY
            tasks.change_status(session, task, target, event.actor, **kwargs)
            return None

        # Review: an already-reviewed task still takes the evidence, and says nothing else.
        if attempt(f"status:{target}", change) != "already":
            return
        if not (target == "review" and evidence):
            effects.append(
                {"action": f"status:{target}", "applied": False, "reason": f"déjà en {target}"}
            )
        if evidence and target in ("review", "done"):
            # Its own attempt: a refusal of the evidence is its own effect, never the status's.
            attempt("evidence", lambda: tasks.attach_evidence(
                session, task, evidence, event.actor
            ))

    match event.kind:
        case "claimed":
            session.refresh(task)  # jugé sur l'état courant, pas sur la lecture initiale
            if task.lead_agent != event.actor:
                attempt(
                    "lead_agent",
                    lambda: tasks.update_task(
                        session, task, {"lead_agent": event.actor}, event.actor
                    ),
                    watched=("lead_agent",),
                    unchanged=f"{event.actor} est déjà l'agent principal",
                )
        case "working":
            move("in_progress")
        case "blocked":
            follow_up = e.payload.get("follow_up_at")
            move(
                "blocked",
                block_cause=rules.cause_of(e),
                block_plan=e.payload.get("plan"),
                follow_up_at=datetime.fromisoformat(follow_up) if follow_up else None,
            )
        case "review":
            move("review", evidence=event.evidence)
        case "done":
            move("done", evidence=event.evidence)
        case "handoff":
            stale = _stale_run(session, event, task)
            if stale:
                effects.append({"action": "handoff", "applied": False, "reason": stale})
                return effects
            session.refresh(task)  # judged on the current task, not the copy read before the event
            lead, next_action = e.needs[0], e.payload["next_action"].strip()
            attempt(
                "handoff",
                lambda: tasks.update_task(
                    session, task, {"lead_agent": lead, "next_action": next_action}, event.actor
                ),
                watched=("lead_agent", "next_action"),
                unchanged=f"{lead} a déjà la main, avec la même prochaine action",
            )
    return effects
