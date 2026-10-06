"""Publication des événements : validation, masquage des secrets, idempotence, effets sur la tâche.

Un événement est un fait déclaré par un agent : il est toujours enregistré s'il est valide.
Ses effets sur la tâche passent par les règles des tâches ; un effet refusé est consigné
dans l'événement (`effects`) au lieu de faire échouer la publication.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from pydantic import StringConstraints, TypeAdapter
from sqlalchemy import select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from nexus import secrets
from nexus.clock import now
from nexus.events import rules
from nexus.events.limits import EVENT_ID_MAX, EVIDENCE_REF_MAX, RUN_MAX, SUBJECT_MAX
from nexus.events.rules import Envelope
from nexus.models import Event, Task
from nexus.tasks import service as tasks
from nexus.tasks.rules import RuleViolation
from nexus.validation import has_unencodable

log = logging.getLogger("nexus.events")

RUN_OPEN_ATTEMPTS = 3
EFFECT_ATTEMPTS = 3
# Nom d'adaptateur (api, hermes, codex…) : jamais une valeur libre, qui pourrait porter un secret.
_ORIGIN = re.compile(r"[a-z][a-z0-9-]{0,31}")

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


def _text_list(value: Any, name: str) -> list[str]:
    # An adapter may pass a tuple: normalise to the list the database will re-read, otherwise the
    # fingerprint (read-back, anti-noise) compares a tuple to a list.
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
        raise RuleViolation(f"invalid_{name}", f"{name} doit être une liste de textes")
    return list(value)


# (field, violation code, message): required text, then optional text. The received value is never
# echoed in the message (it could be a secret).
_REQUIRED_TEXT = (
    ("actor", "invalid_actor", "actor doit être un texte"),
    ("kind", "invalid_kind", "kind doit être un texte"),
    ("subject", "invalid_subject", "subject doit être un texte"),
)
_OPTIONAL_TEXT = (
    ("task", "invalid_task", "task doit être un texte ou absente"),
    ("run", "invalid_run", "run doit être un texte ou absent"),
    ("body", "invalid_body", "body doit être un texte ou absent"),
)


def _check_scalars(envelope: Envelope, actor_event_id: object) -> None:
    """Refuse a wrong scalar type from a direct call (the API's Pydantic models guarantee them).

    Only the type is checked: empty or unknown values keep the behaviour of `rules.validate`.
    """
    for name, code, message in _REQUIRED_TEXT:
        if not isinstance(getattr(envelope, name), str):
            raise RuleViolation(code, message)
    for name, code, message in _OPTIONAL_TEXT:
        value = getattr(envelope, name)
        if value is not None and not isinstance(value, str):
            raise RuleViolation(code, message)
    if not isinstance(actor_event_id, str):
        raise RuleViolation("invalid_event_id", "id doit être un texte")


# The API strips evidence items with Pydantic before measuring them: reuse that exact stripping
# (it differs from `str.strip()`, which also removes U+001C to U+001F).
_API_STRIP = TypeAdapter(Annotated[str, StringConstraints(strip_whitespace=True)])


def _check_lengths(envelope: Envelope, actor_event_id: str) -> None:
    """Refuse a value longer than the API accepts (same constants, same measure).

    Run after the type checks, before redaction: the API measures the raw received length (the
    evidence items after stripping, as `Ref` does). The value is never echoed.
    """
    if len(actor_event_id) > EVENT_ID_MAX:
        raise RuleViolation("too_long_id", f"id : {EVENT_ID_MAX} caractères au plus")
    if envelope.run is not None and len(envelope.run) > RUN_MAX:
        raise RuleViolation("too_long_run", f"run : {RUN_MAX} caractères au plus")
    if len(envelope.subject) > SUBJECT_MAX:
        raise RuleViolation("too_long_subject", f"subject : {SUBJECT_MAX} caractères au plus")
    if any(len(_API_STRIP.validate_python(item)) > EVIDENCE_REF_MAX for item in envelope.evidence):
        raise RuleViolation(
            "too_long_evidence", f"evidence : {EVIDENCE_REF_MAX} caractères au plus par élément"
        )


def publish(
    session: Session,
    envelope: Envelope,
    actor_event_id: str,
    at: datetime,
    origin: str = "api",
) -> tuple[Event, bool]:
    """Enregistre l'événement ; renvoie (événement, créé). Un renvoi identique est une relecture.

    Prend la main sur la transaction : une course se résout par un rollback. L'appelant fournit
    donc une session dédiée, sans écriture en attente, et valide (commit) après l'appel.
    """
    if session.new or session.dirty or session.deleted:
        raise RuntimeError(
            "publish() demande une session dédiée : un rollback de course annulerait les "
            "écritures en attente de l'appelant"
        )
    if not isinstance(origin, str) or not _ORIGIN.fullmatch(origin) or secrets.redact(origin)[1]:
        # Stockée et renvoyée telle quelle : seul un nom d'adaptateur est accepté (ADR-006).
        raise RuleViolation("invalid_origin", "origin : nom d'adaptateur invalide")
    if not isinstance(at, datetime) or at.utcoffset() is None:
        # L'API l'exige (AwareDatetime) ; un adaptateur ferait sinon échouer l'écriture.
        raise RuleViolation("invalid_instant", "at : instant avec fuseau horaire requis")
    _check_scalars(envelope, actor_event_id)
    if not isinstance(envelope.payload, dict):
        raise RuleViolation("invalid_payload", "payload doit être un objet JSON")
    envelope.needs = _text_list(envelope.needs, "needs")
    envelope.evidence = _text_list(envelope.evidence, "evidence")
    _check_lengths(envelope, actor_event_id)
    incoming = (envelope.subject, envelope.body, envelope.payload, envelope.evidence,
                envelope.needs, envelope.run, actor_event_id)
    if has_unencodable(incoming):
        # L'API le refuse déjà (InputModel) ; un adaptateur qui appelle publish() directement
        # ferait sinon échouer chaque lecture de l'événement.
        raise RuleViolation(
            "invalid_value", "valeur non encodable : demi-paire UTF-16, NaN ou Infinity"
        )
    redacted: dict[str, list[str]] = {}
    raw_run_refs = (envelope.run, envelope.payload.get("run_ref"))
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
            "secret_in_event_id", "l'identifiant de l'événement contient un secret : change-le"
        )
    actor_event_id, envelope.run = clean["id"], clean["run"]
    if secrets.is_blank(actor_event_id):
        # Vide ou déjà « [REDACTED] » : ce serait la même clé d'idempotence pour tout le monde.
        raise RuleViolation("event_id_required", "id : identifiant lisible requis")
    actor_event_id = actor_event_id.strip()
    if (envelope.run, envelope.payload.get("run_ref")) != raw_run_refs:
        # Même raison que pour l'identifiant : "run token=alpha" et "run token=beta" deviendraient
        # le même run une fois masqués, et les clôtures ne pourraient plus les distinguer.
        raise RuleViolation(
            "secret_in_run_ref", "la référence du run contient un secret : change-la"
        )

    kind = rules.validate(envelope)
    task = _task(session, envelope.task)

    existing = session.scalar(
        select(Event).where(Event.actor == envelope.actor, Event.actor_event_id == actor_event_id)
    )
    if existing is not None:
        if (_same(existing, envelope, task) and _same_instant(existing.at, at)
                and existing.origin == origin):
            return existing, False
        raise RuleViolation(
            "event_id_reused",
            # L'identifiant reçu n'est pas recopié : ce pourrait être un secret non reconnu.
            f"id : déjà utilisé par {envelope.actor} pour un autre événement ; un événement "
            "ne se réécrit pas, publie une correction",
        )
    _refuse_noise(session, envelope, task, actor_event_id)
    serialized_from = None  # date de modification avant le verrou, si le verrou a joué
    if kind == "working":
        # Ouverture de run sérialisée : toucher la tâche fait jouer son verrou de version. Si une
        # autre écriture passe entre-temps, on relit et on revérifie la règle au lieu de refuser :
        # un autre agent peut ouvrir son propre run, seul un second run du même agent est refusé.
        for _ in range(RUN_OPEN_ATTEMPTS):
            _refuse_second_active_run(session, envelope, task)
            if task is None:
                break
            serialized_from = task.updated_at
            task.updated_at = now()
            try:
                session.flush()
                break
            except StaleDataError:
                winner = _winner_of_race(session, envelope, actor_event_id, at, task, origin)
                if winner is not None:
                    return winner, False  # renvoi identique : relecture
                task = _task(session, envelope.task)
        else:
            raise StaleDataError("ouverture de run : trop d'écritures concurrentes")

    received = now()
    event = Event(
        actor=envelope.actor, actor_event_id=actor_event_id, at=at, received_at=received,
        task_id=task.id if task else None,
        run_ref=_run_ref(envelope),
        kind=kind, requested_kind=envelope.kind if kind != envelope.kind else None,
        subject=envelope.subject, body=envelope.body, payload=envelope.payload,
        evidence=envelope.evidence, needs=envelope.needs,
        redacted=sorted({k for kinds in redacted.values() for k in kinds}),
        origin=origin,
    )
    if event.redacted:
        log.warning("secret masqué dans un événement de %s (%s)", envelope.actor, event.redacted)
    session.add(event)
    try:
        session.flush()
    except IntegrityError as exc:  # course avec un renvoi simultané du même identifiant
        winner = _winner_of_race(session, envelope, actor_event_id, at, task, origin)
        if winner is not None:
            return winner, False
        raise RuleViolation("event_id_reused", "identifiant d'événement déjà utilisé") from exc
    # Second contrôle, après l'insertion et dans la même transaction : SQLite sérialisant les
    # écritures, un fait identique publié en parallèle sous un autre identifiant est vu ici.
    _refuse_noise(session, envelope, task, actor_event_id, exclude_id=event.id)
    event.effects = _apply_effects(session, event, envelope, task) if task else []
    if serialized_from is not None and not any(e["applied"] for e in event.effects):
        # Le verrou n'a servi qu'à sérialiser : sans changement réel, la tâche ne doit pas
        # paraître récemment modifiée.
        task.updated_at = serialized_from
    return event, True


def _winner_of_race(
    session: Session,
    e: Envelope,
    actor_event_id: str,
    at: datetime,
    task: Task | None,
    origin: str,
) -> Event | None:
    """Après un conflit d'écriture : l'événement gagnant, s'il est identique à celui-ci."""
    session.rollback()
    winner = session.scalar(
        select(Event).where(Event.actor == e.actor, Event.actor_event_id == actor_event_id)
    )
    if (winner is not None and _same(winner, e, task) and _same_instant(winner.at, at)
            and winner.origin == origin):
        return winner
    return None


def _same_instant(a: datetime, b: datetime) -> bool:
    # Ramenées en UTC, les deux dates se comparent champ à champ, à la microseconde près ;
    # ni float (précision perdue loin de 1970) ni comparaison inter-fuseaux (PEP 495, fold).
    return a.astimezone(UTC) == b.astimezone(UTC)


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
    """Référence du run : `run` s'il dit quelque chose, sinon `payload.run_ref`."""
    for candidate in (e.run, e.payload.get("run_ref")):
        if isinstance(candidate, str) and not secrets.is_blank(candidate):
            return candidate.strip()
    return None


def _fingerprint(kind, task_id, run, subject, body, payload, evidence, needs) -> tuple:
    # JSON canonique : un renvoi identique aux clés imbriquées réordonnées reste identique.
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return (kind, task_id, run, subject, body, canonical, evidence, needs)


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


def _refuse_second_active_run(session: Session, e: Envelope, task: Task | None) -> None:
    """Un seul run actif par agent et par tâche (EVENT-PROTOCOL §4)."""
    if task is None:
        return
    active, closed = _runs(session, e.actor, task)
    if _run_ref(e) in closed:
        return  # working tardif d'un run clos : enregistré, sans effet (voir _stale_run)
    if active is not None and active != _run_ref(e):
        raise RuleViolation(
            "run_already_active",
            f"{e.actor} a déjà un run actif sur {task.ref} : termine-le (done, review, "
            "failed, handoff ou blocked, en nommant son run) avant d'en ouvrir un autre",
        )


def _refuse_noise(
    session: Session,
    e: Envelope,
    task: Task | None,
    actor_event_id: str,
    exclude_id: int | None = None,
) -> None:
    # `task_id = NULL` n'est jamais vrai en SQL : il faut IS NULL pour les événements sans tâche.
    same_task = Event.task_id == task.id if task else Event.task_id.is_(None)
    recent = session.scalars(
        select(Event).where(
            Event.actor == e.actor, same_task, Event.received_at >= now() - NOISE_WINDOW,
            # Le même identifiant n'est pas du bruit : c'est un renvoi, traité en relecture.
            Event.actor_event_id != actor_event_id,
            Event.id != exclude_id if exclude_id is not None else true(),
        )
    )
    for previous in recent:
        if _same(previous, e, task):
            raise RuleViolation(
                "noise",
                "cet événement vient déjà d'être publié à l'identique : rien de nouveau, "
                "rien à publier",
            )


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


def _apply_effects(session: Session, event: Event, e: Envelope, task: Task) -> list[dict]:
    """Traduit l'événement en mutations de la tâche, chacune tentée dans un point de sauvegarde."""
    effects: list[dict] = []

    def attempt(action: str, fn, watched: tuple[str, ...] = (), unchanged: str = "") -> None:
        # Un conflit de version (la tâche a changé depuis sa lecture) n'est pas un refus : on
        # relit la tâche et on retente, les règles jugeant alors son état à jour.
        for _ in range(EFFECT_ATTEMPTS):
            savepoint = session.begin_nested()
            try:
                before = [getattr(task, f) for f in watched]
                fn()
                if watched and before == [getattr(task, f) for f in watched]:
                    # update_task writes nothing when nothing differs: not an applied effect.
                    raise RuleViolation("effect_unchanged", unchanged)
                savepoint.commit()
                effects.append({"action": action, "applied": True})
                return
            except StaleDataError:
                savepoint.rollback()
                session.refresh(task)
            except (RuleViolation, IntegrityError) as exc:
                savepoint.rollback()
                session.refresh(task)
                message = exc.message if isinstance(exc, RuleViolation) else "conflit en base"
                effects.append({"action": action, "applied": False, "reason": message})
                return
        effects.append({"action": action, "applied": False,
                        "reason": "conflit en base : trop d'écritures concurrentes"})

    def move(target: str, **kwargs: Any) -> None:
        stale = _stale_run(session, event, task)
        if stale:
            effects.append({"action": f"status:{target}", "applied": False, "reason": stale})
            return
        # La tâche a pu changer depuis sa lecture (avant l'insertion de l'événement) : on juge
        # « déjà dans ce statut » sur son état courant, pas sur la copie en mémoire.
        session.refresh(task)
        if task.status == target:
            if target == "review" and kwargs.get("evidence"):
                # Déjà en review (mise par Loïc, sans preuve) : la preuve jointe compte quand même.
                attempt("evidence", lambda: tasks.attach_evidence(
                    session, task, kwargs["evidence"], event.actor
                ))
                return
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
