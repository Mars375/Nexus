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
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.types import Scope

from nexus.auth import tokens
from nexus.auth.deps import TokenIdentity, authenticated_token
from nexus.auth.tickets import TTL_SECONDS, is_well_formed
from nexus.models import Event, TaskHistory

POLL_SECONDS = 0.25
PING_SECONDS = 15.0
RESYNC_THRESHOLD = 500
REVOKED_CODE = 4401
REVOKED_REASON = "jeton révoqué"
LIVE_PROTOCOL = "nexus.live.v1"
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
    """Un WebSocket échappe à CORS : seule une origine locale (ou déclarée dans
    NEXUS_ALLOWED_ORIGINS, aussi utilisée par le CORS du REST) peut écouter."""
    if origin is None:
        return True  # non-browser client: it still needs a ticket
    if origin in extra:
        return True
    try:
        parts = urlsplit(origin)
        parts.port  # noqa: B018 — lève ValueError sur un port invalide
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and parts.hostname in _LOOPBACK_HOSTS


def origin_allowed_in_scope(scope: Scope, extra: frozenset[str]) -> bool:
    """Origin read straight from `scope["headers"]`: ASGI only `recommends` lowercase names,
    and Starlette Headers compare raw names exactly, so a wire-name `b"Origin"` was never
    found by `.get("origin")` (#61). Same reading pattern as hosts.py for Host; more than one
    Origin is ambiguous and refused rather than treated as an absent header.
    """
    origins = [v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"origin"]
    if len(origins) > 1:
        return False
    return origin_allowed(origins[0] if origins else None, extra)


router = APIRouter()


@router.post("/api/ws-ticket")
def issue_ws_ticket(
    request: Request,
    response: Response,
    identity: Annotated[TokenIdentity, Depends(authenticated_token)],
) -> dict:
    """A single-use WebSocket ticket for the presented token (#57); never cached."""
    response.headers["Cache-Control"] = "no-store"
    ticket = request.app.state.ws_tickets.issue(identity.token_hash, identity.actor)
    return {"ticket": ticket, "protocol": LIVE_PROTOCOL, "expires_in": TTL_SECONDS}


def ticket_from_subprotocols(protocols: list[str]) -> str | None:
    """The ticket offered next to `nexus.live.v1`, or None unless the offer is exactly that.

    Exactly two entries: the protocol and one well-formed ticket, in either order, no duplicate.
    """
    if len(protocols) != 2 or LIVE_PROTOCOL not in protocols:
        return None
    other = protocols[1] if protocols[0] == LIVE_PROTOCOL else protocols[0]
    return other if other != LIVE_PROTOCOL and is_well_formed(other) else None


@router.websocket("/api/ws")
async def live_updates(websocket: WebSocket) -> None:
    # Every refusal before `accept` is a bare close(1008): HTTP 403, no reason, nothing received
    # is echoed and the cases are not told apart (#57). Order: Host (middleware), Origin, ticket
    # shape, ticket, cursor. A refusal before the ticket step leaves the ticket usable; from the
    # ticket step on it is spent, whatever the next check says.
    app = websocket.app
    if not origin_allowed_in_scope(websocket.scope, app.state.settings.allowed_origins):
        await websocket.close(code=1008)
        return
    ticket = ticket_from_subprotocols(list(websocket.scope.get("subprotocols") or []))
    grant = app.state.ws_tickets.consume(ticket) if ticket is not None else None
    if grant is None:
        await websocket.close(code=1008)
        return
    make = app.state.sessionmaker

    def read_current() -> Cursor:
        with make() as session:
            return current_cursor(session)

    def token_live() -> bool:
        with make() as session:
            return tokens.is_live(session, grant.token_hash)

    def read_changes(cursor: Cursor) -> tuple[list[dict], Cursor] | None:
        """The changes beyond the cursor, or None once the token is revoked or deleted.

        The token is checked first, in the same session: nothing is sent after a revocation.
        """
        with make() as session:
            if not tokens.is_live(session, grant.token_hash):
                return None
            return changes_since(session, cursor)

    if not await asyncio.to_thread(token_live):
        await websocket.close(code=1008)  # revoked or deleted between issue and use
        return

    try:
        cursor, reset = start_cursor(
            websocket.query_params.get("history_after"),
            websocket.query_params.get("events_after"),
            websocket.query_params.get("instance"),
            await asyncio.to_thread(read_current),
            app.state.live_instance,
        )
    except ValueError:
        await websocket.close(code=1008)  # no reason: the received value is never echoed
        return
    await websocket.accept(subprotocol=LIVE_PROTOCOL)
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
            result = await asyncio.to_thread(read_changes, cursor)
            if result is None:
                await websocket.close(code=REVOKED_CODE, reason=REVOKED_REASON)
                return
            messages, cursor = result
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
