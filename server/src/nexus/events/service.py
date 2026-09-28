"""Publication des événements : validation, masquage des secrets, idempotence, effets sur la tâche.

Un événement est un fait déclaré par un agent : il est toujours enregistré s'il est valide.
Ses effets sur la tâche passent par les règles des tâches ; un effet refusé est consigné
dans l'événement (`effects`) au lieu de faire échouer la publication.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from nexus import secrets
from nexus.clock import now
from nexus.events import rules
from nexus.events.rules import Envelope
from nexus.models import Event, Task
from nexus.tasks import service as tasks
from nexus.tasks.rules import RuleViolation

log = logging.getLogger("nexus.events")

# Anti-bruit (EVENT-PROTOCOL §7) : le même fait republié dans cette fenêtre est refusé.
NOISE_WINDOW = timedelta(minutes=10)


class EventNotFound(Exception):
    def __init__(self, ref: str) -> None:
        # Jamais la valeur reçue : elle pourrait être un secret collé par erreur.
        super().__init__(f"événement introuvable : {ref}" if ref.startswith("nx-evt-") else
                         "événement introuvable : référence invalide")


def parse_task_ref(ref: str) -> int:
    raw = ref.removeprefix("nx-task-")
    if not re.fullmatch(r"[0-9]{1,12}", raw):
        # La valeur reçue n'est jamais recopiée (elle pourrait être un secret).
        raise RuleViolation("unknown_task", "référence de tâche invalide")
    return int(raw)


def publish(
    session: Session, envelope: Envelope, actor_event_id: str, at: datetime
) -> tuple[Event, bool]:
    """Enregistre l'événement ; renvoie (événement, créé). Un renvoi identique est une relecture."""
    redacted: dict[str, list[str]] = {}
    # Tout ce qui sera stocké passe par le scanner, identifiants compris (ADR-006).
    clean = secrets.redact_fields(
        {"subject": envelope.subject, "body": envelope.body, "payload": envelope.payload,
         "evidence": envelope.evidence, "id": actor_event_id, "run": envelope.run},
        redacted.__setitem__,
    )
    envelope.subject, envelope.body = clean["subject"], clean["body"]
    envelope.payload, envelope.evidence = clean["payload"], clean["evidence"]
    if "id" in redacted:
        # Masqué, l'identifiant perdrait son unicité (deux secrets → même « [REDACTED] ») :
        # on le refuse plutôt que de confondre deux événements.
        raise RuleViolation(
            "secret_in_event_id", "l'identifiant de l'événement contient un secret : changes-le"
        )
    actor_event_id, envelope.run = clean["id"], clean["run"]

    kind = rules.validate(envelope)
    task = _task(session, envelope.task)

    existing = session.scalar(
        select(Event).where(Event.actor == envelope.actor, Event.actor_event_id == actor_event_id)
    )
    if existing is not None:
        if _same(existing, envelope, task) and existing.at.timestamp() == at.timestamp():
            return existing, False
        raise RuleViolation(
            "event_id_reused",
            f"l'identifiant {actor_event_id} a déjà servi pour un autre événement de "
            f"{envelope.actor} : un événement ne se réécrit pas, publie une correction",
        )
    _refuse_noise(session, envelope, task, actor_event_id)
    if kind == "working":
        _refuse_second_active_run(session, envelope, task)
        if task is not None:
            # Sérialise les ouvertures de run : toucher la tâche fait jouer son verrou de version,
            # si bien que de deux « working » simultanés, le second échoue (409) au lieu de passer.
            task.updated_at = now()
            session.flush()

    received = now()
    event = Event(
        actor=envelope.actor, actor_event_id=actor_event_id, at=at, received_at=received,
        task_id=task.id if task else None,
        run_ref=_run_ref(envelope),
        kind=kind, requested_kind=envelope.kind if kind != envelope.kind else None,
        subject=envelope.subject, body=envelope.body, payload=envelope.payload,
        evidence=envelope.evidence, needs=envelope.needs,
        redacted=sorted({k for kinds in redacted.values() for k in kinds}),
    )
    if event.redacted:
        log.warning("secret masqué dans un événement de %s (%s)", envelope.actor, event.redacted)
    session.add(event)
    try:
        session.flush()
    except IntegrityError as exc:  # course avec un renvoi simultané du même identifiant
        session.rollback()
        winner = session.scalar(
            select(Event).where(
                Event.actor == envelope.actor, Event.actor_event_id == actor_event_id
            )
        )
        if winner is not None and _same(winner, envelope, task) and (
            winner.at.timestamp() == at.timestamp()
        ):
            return winner, False
        raise RuleViolation("event_id_reused", "identifiant d'événement déjà utilisé") from exc
    event.effects = _apply_effects(session, event, envelope, task) if task else []
    return event, True


def get_event(session: Session, ref: str) -> Event:
    raw = ref.removeprefix("nx-evt-")
    if not re.fullmatch(r"[0-9]{1,12}", raw):
        raise EventNotFound("")
    event = session.get(Event, int(raw))
    if event is None:
        raise EventNotFound(f"nx-evt-{int(raw)}")
    return event


def list_events(
    session: Session,
    *,
    task: str | None = None,
    actor: str | None = None,
    kind: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[Event]:
    query = select(Event).order_by(Event.id.desc()).limit(limit)
    if task:
        query = query.where(Event.task_id == parse_task_ref(task))
    if actor:
        query = query.where(Event.actor == actor)
    if kind:
        query = query.where(Event.kind == kind)
    if since:
        query = query.where(Event.received_at >= since)
    return list(session.scalars(query))


def _task(session: Session, ref: str | None) -> Task | None:
    if ref is None:
        return None
    return tasks.get_task(session, parse_task_ref(ref))


def _run_ref(e: Envelope) -> str | None:
    return e.run or e.payload.get("run_ref")


def _fingerprint(kind, task_id, run, subject, body, payload, evidence, needs) -> tuple:
    return (kind, task_id, run, subject, body, repr(sorted(payload.items())), evidence, needs)


def _same(existing: Event, e: Envelope, task: Task | None) -> bool:
    """Même contenu (type demandé, tâche, run, textes, preuves, destinataires)."""
    requested = existing.requested_kind or existing.kind
    return _fingerprint(
        requested, existing.task_id, existing.run_ref, existing.subject, existing.body,
        existing.payload, existing.evidence, existing.needs,
    ) == _fingerprint(
        e.kind, task.id if task else None, _run_ref(e), e.subject, e.body, e.payload,
        e.evidence, e.needs,
    )


# Ce qui clôt ou suspend un run : après l'un d'eux, l'agent peut en ouvrir un autre.
RUN_CLOSERS = frozenset({"done", "review", "failed", "handoff", "blocked"})


def _refuse_second_active_run(session: Session, e: Envelope, task: Task | None) -> None:
    """Un seul run actif par agent et par tâche (EVENT-PROTOCOL §4)."""
    if task is None:
        return
    history = session.scalars(
        select(Event)
        .where(Event.actor == e.actor, Event.task_id == task.id)
        .order_by(Event.id.desc())
    )
    # Du plus récent au plus ancien : les clôtures vues avant le dernier working ne comptent
    # que si elles visent ce run (ou n'en nomment aucun) — une clôture tardive d'un ancien
    # run ne libère pas le run actif.
    closed_runs: list[str | None] = []
    for previous in history:
        if previous.kind in RUN_CLOSERS:
            closed_runs.append(previous.run_ref)
            continue
        if previous.kind == "working":
            if None in closed_runs or previous.run_ref in closed_runs:
                return
            if previous.run_ref != _run_ref(e):
                raise RuleViolation(
                    "run_already_active",
                    f"{e.actor} a déjà un run actif sur {task.ref} : termine-le (done, review, "
                    "failed, handoff ou blocked) avant d'en ouvrir un autre",
                )
            return


def _refuse_noise(
    session: Session, e: Envelope, task: Task | None, actor_event_id: str
) -> None:
    # `task_id = NULL` n'est jamais vrai en SQL : il faut IS NULL pour les événements sans tâche.
    same_task = Event.task_id == task.id if task else Event.task_id.is_(None)
    recent = session.scalars(
        select(Event).where(
            Event.actor == e.actor, same_task, Event.received_at >= now() - NOISE_WINDOW,
            # Le même identifiant n'est pas du bruit : c'est un renvoi, traité en relecture.
            Event.actor_event_id != actor_event_id,
        )
    )
    for previous in recent:
        if _same(previous, e, task):
            raise RuleViolation(
                "noise",
                "cet événement vient déjà d'être publié à l'identique : rien de nouveau, "
                "rien à publier",
            )


def _apply_effects(session: Session, event: Event, e: Envelope, task: Task) -> list[dict]:
    """Traduit l'événement en mutations de la tâche, chacune tentée dans un point de sauvegarde."""
    effects: list[dict] = []

    def attempt(action: str, fn) -> None:
        savepoint = session.begin_nested()
        try:
            fn()
            savepoint.commit()
            effects.append({"action": action, "applied": True})
        except (RuleViolation, IntegrityError, StaleDataError) as exc:
            savepoint.rollback()
            session.refresh(task)
            message = exc.message if isinstance(exc, RuleViolation) else "conflit en base"
            effects.append({"action": action, "applied": False, "reason": message})

    def move(target: str, **kwargs: Any) -> None:
        if task.status == target:
            effects.append(
                {"action": f"status:{target}", "applied": False, "reason": f"déjà en {target}"}
            )
            return
        attempt(
            f"status:{target}",
            lambda: tasks.change_status(session, task, target, event.actor, **kwargs),
        )

    match event.kind:
        case "claimed":
            if task.lead_agent != event.actor:
                attempt("lead_agent", lambda: tasks.update_task(
                    session, task, {"lead_agent": event.actor}, event.actor
                ))
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
            move("review")
        case "done":
            move("done", evidence=event.evidence)
        case "handoff":
            attempt("handoff", lambda: tasks.update_task(
                session, task,
                {"lead_agent": e.needs[0], "next_action": e.payload["next_action"]},
                event.actor,
            ))
    return effects
