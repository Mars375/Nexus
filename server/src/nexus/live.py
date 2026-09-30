"""Temps réel (#5) : ce qui a changé au-delà d'un curseur, et qui peut l'écouter.

Chaque connexion relit la base au-delà de son curseur (spec #5, approche B) : la même
lecture sert au rattrapage après une reconnexion et au direct. Les messages ne portent que
des références et des types, jamais de texte reçu : l'interface relit par l'API REST.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus.models import Event, TaskHistory

POLL_SECONDS = 0.25
PING_SECONDS = 15.0
RESYNC_THRESHOLD = 500
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class Cursor:
    """Tout ce qui a été vu jusqu'à ces identifiants inclus."""

    history: int
    events: int

    def as_dict(self) -> dict[str, int]:
        return {"history": self.history, "events": self.events}


def current_cursor(session: Session) -> Cursor:
    history = session.scalar(select(func.max(TaskHistory.id))) or 0
    events = session.scalar(select(func.max(Event.id))) or 0
    return Cursor(history, events)


def _parse(raw: str) -> int:
    if not (raw.isascii() and raw.isdigit() and len(raw) <= 12):
        raise ValueError("curseur invalide")
    return int(raw)


def start_cursor(
    history_after: str | None, events_after: str | None, current: Cursor
) -> tuple[Cursor, bool]:
    """Curseur de départ et `reset` ; les deux paramètres vont ensemble ou pas du tout."""
    if history_after is None and events_after is None:
        return current, False
    if history_after is None or events_after is None:
        raise ValueError("curseur incomplet")
    requested = Cursor(_parse(history_after), _parse(events_after))
    if requested.history > current.history or requested.events > current.events:
        # Base restaurée ou recréée : on repart de l'existant et le client relit tout.
        return current, True
    return requested, False


def changes_since(session: Session, cursor: Cursor) -> tuple[list[dict], Cursor]:
    history = session.execute(
        select(TaskHistory.id, TaskHistory.task_id)
        .where(TaskHistory.id > cursor.history)
        .order_by(TaskHistory.id)
        .limit(RESYNC_THRESHOLD + 1)
    ).all()
    events = session.execute(
        select(Event.id, Event.task_id, Event.kind)
        .where(Event.id > cursor.events)
        .order_by(Event.id)
        .limit(RESYNC_THRESHOLD + 1)
    ).all()
    if not history and not events:
        return [], cursor
    if len(history) + len(events) > RESYNC_THRESHOLD:
        latest = current_cursor(session)
        return [{"type": "resync", "cursor": latest.as_dict()}], latest
    end = Cursor(
        history[-1].id if history else cursor.history,
        events[-1].id if events else cursor.events,
    )
    messages: list[dict] = []
    seen: set[int] = set()
    for row in history:  # une tâche modifiée plusieurs fois : un seul message
        if row.task_id not in seen:
            seen.add(row.task_id)
            messages.append({"type": "task_changed", "task": f"nx-task-{row.task_id}"})
    for row in events:
        messages.append({
            "type": "event",
            "event": f"nx-evt-{row.id}",
            "task": f"nx-task-{row.task_id}" if row.task_id is not None else None,
            "kind": row.kind,
        })
    # Au moins une fois : seul le dernier message avance le curseur ; une coupure au milieu
    # fait rejouer la relecture, ce qui ne coûte qu'une invalidation de plus.
    for message in messages[:-1]:
        message["cursor"] = cursor.as_dict()
    messages[-1]["cursor"] = end.as_dict()
    return messages, end


def origin_allowed(origin: str | None, extra: frozenset[str]) -> bool:
    """Un WebSocket échappe à CORS : seule une origine locale (ou déclarée) peut écouter."""
    if origin is None:
        return True  # client non navigateur, local : il lirait l'API REST de toute façon
    if origin in extra:
        return True
    try:
        parts = urlsplit(origin)
        parts.port  # noqa: B018 — lève ValueError sur un port invalide
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and parts.hostname in _LOOPBACK_HOSTS
