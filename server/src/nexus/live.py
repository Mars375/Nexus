"""Temps réel (#5) : ce qui a changé au-delà d'un curseur, et qui peut l'écouter.

Chaque connexion relit la base au-delà de son curseur (spec #5, approche B) : la même
lecture sert au rattrapage après une reconnexion et au direct. Les messages ne portent que
des références et des types, jamais de texte reçu : l'interface relit par l'API REST.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
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


# ASCII-strict on purpose: `\d` and `$` would accept non-ASCII digits and a trailing newline.
_INSTANCE = re.compile(r"[0-9a-f]{16}")


def start_cursor(
    history_after: str | None,
    events_after: str | None,
    instance: str | None,
    current: Cursor,
    live_instance: str,
) -> tuple[Cursor, bool]:
    """Starting cursor and `reset`; the two cursors come together or not at all.

    `instance` is the id of the server run that issued the cursor: when it differs from
    `live_instance` (restart, restored base) ids may have been rewritten, so restart from what
    exists and let the client reread. An old client sends no instance: no comparison, as before.
    """
    if history_after is None and events_after is None:
        if instance is not None:
            raise ValueError("curseur incomplet")
        return current, False
    if history_after is None or events_after is None:
        raise ValueError("curseur incomplet")
    requested = Cursor(_parse(history_after), _parse(events_after))
    if instance is not None and _INSTANCE.fullmatch(instance) is None:
        raise ValueError("instance invalide")  # the received value is never echoed
    if (
        (instance is not None and instance != live_instance)
        or requested.history > current.history
        or requested.events > current.events
    ):
        # Restored or recreated base, or another instance: restart from what exists, client rereads.
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


router = APIRouter()


@router.websocket("/api/ws")
async def live_updates(websocket: WebSocket) -> None:
    app = websocket.app
    if not origin_allowed(websocket.headers.get("origin"), app.state.settings.allowed_origins):
        await websocket.close(code=1008)  # avant acceptation : poignée de main refusée
        return
    make = app.state.sessionmaker

    def read_current() -> Cursor:
        with make() as session:
            return current_cursor(session)

    def read_changes(cursor: Cursor) -> tuple[list[dict], Cursor]:
        with make() as session:
            return changes_since(session, cursor)

    try:
        cursor, reset = start_cursor(
            websocket.query_params.get("history_after"),
            websocket.query_params.get("events_after"),
            websocket.query_params.get("instance"),
            await asyncio.to_thread(read_current),
            app.state.live_instance,
        )
    except ValueError:
        # Raison générique : la valeur reçue n'est jamais recopiée.
        await websocket.close(code=1008, reason="curseur invalide")
        return
    await websocket.accept()
    await websocket.send_json({
        "type": "hello",
        "cursor": cursor.as_dict(),
        "reset": reset,
        "instance": app.state.live_instance,
    })

    async def push() -> None:
        nonlocal cursor
        silent = 0.0
        while True:
            messages, cursor = await asyncio.to_thread(read_changes, cursor)
            for message in messages:
                await websocket.send_json(message)
            if messages:
                silent = 0.0
            else:
                silent += POLL_SECONDS
                if silent >= PING_SECONDS:
                    await websocket.send_json({"type": "ping", "cursor": cursor.as_dict()})
                    silent = 0.0
            await asyncio.sleep(POLL_SECONDS)

    async def wait_for_disconnect() -> None:
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass  # le client n'envoie rien d'utile : on ne fait qu'attendre sa fermeture

    sender = asyncio.create_task(push())
    watcher = asyncio.create_task(wait_for_disconnect())
    done, pending = await asyncio.wait({sender, watcher}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        with suppress(asyncio.CancelledError, WebSocketDisconnect):
            await task
    for task in done:
        with suppress(WebSocketDisconnect):
            task.result()  # une fermeture côté client pendant un envoi n'est pas une erreur
