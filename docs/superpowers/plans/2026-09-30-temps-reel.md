# Temps réel par WebSocket — plan d'implémentation (#5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** l'interface reçoit chaque changement de tâche et chaque événement en moins d'une seconde, et rattrape tout après une coupure, sans jamais transporter de texte reçu.

**Architecture:** côté serveur, `nexus/live.py` expose des fonctions pures (curseur, lecture des changements au-delà d'un curseur, contrôle d'origine) et un point d'entrée WebSocket `/api/ws` qui relit la base toutes les 250 ms. Côté web, `web/src/live.ts` contient la connexion (machine d'états, reconnexion, silence) avec un `WebSocket` injecté ; `web/src/liveUpdates.ts` traduit les messages en invalidations TanStack Query ; `LiveStatus` affiche l'état dans la barre du bas.

**Tech Stack:** FastAPI (Starlette WebSocket, `TestClient.websocket_connect`), SQLAlchemy/SQLite, pytest ; React 19 + TypeScript, TanStack Query, Vitest (faux timers), Playwright 1.63 (`page.routeWebSocket`).

**Spec:** `docs/superpowers/specs/2026-09-30-temps-reel-design.md`

## Global Constraints

- Branche `feat/5-temps-reel`. Chaque `git commit` passe par le hook pre-commit (gitleaks, ruff/oxlint, `tsc`, toutes les suites serveur et web) : on ne commite jamais un test rouge ; `--no-verify` interdit.
- Curseur = `{"history": <id max de task_history vu>, "events": <id max de events vu>}` ; aucune nouvelle table, aucune migration.
- Messages : `hello {cursor, reset}`, `task_changed {task, cursor}`, `event {event, task|null, kind, cursor}`, `resync {cursor}`, `ping {cursor}`. Jamais de texte libre reçu (sujet, corps, charge utile, commentaire).
- Livraison « au moins une fois » : dans une même relecture, seul le **dernier** message porte le curseur de fin ; les précédents portent le curseur de début (un message rejoué ne fait qu'une invalidation de plus).
- Relecture serveur toutes les 250 ms ; `ping` après 15 s sans message ; `resync` au-delà de 500 lignes ; `task_changed` coalescé par tâche dans une relecture.
- Origines admises : absente, ou boucle locale (`http`/`https`, hôte `localhost`, `127.0.0.1`, `[::1]`, tout port), ou listée dans `NEXUS_ALLOWED_ORIGINS` (séparateur `,`, comparaison exacte). Autre origine ou curseur invalide : fermeture code 1008 avant acceptation, sans recopier la valeur reçue.
- Client : reconnexion 0,5 s, 1 s, 2 s … plafonnée à 10 s, aléa ±20 % ; `unknown` après 30 s sans connexion (depuis la perte ou le chargement) ; fermeture et reconnexion après 45 s sans message.
- La relecture toutes les 10 s (#8) reste active en toutes circonstances.
- Indicateur : « Temps réel : connecté » / « Temps réel : connexion… » / « Temps réel : reconnexion… (essai N) » / « Temps réel : unknown — relecture toutes les 10 s » (couleur attention) ; aucune animation.
- Textes d'interface en français ; identifiants en anglais. Éditer avec les outils Write/Edit (jamais sed/heredoc sur du code : ils abîment les antislashs sur cette machine).

---

### Task 1: Curseur, lecture des changements et contrôle d'origine (fonctions pures)

**Files:**
- Create: `server/src/nexus/live.py`
- Test: `server/tests/test_live.py`

**Interfaces:**
- Produces (in `nexus.live`):
  - constants `POLL_SECONDS = 0.25`, `PING_SECONDS = 15.0`, `RESYNC_THRESHOLD = 500`
  - `@dataclass(frozen=True) class Cursor: history: int; events: int` with `as_dict() -> dict[str, int]`
  - `current_cursor(session: Session) -> Cursor`
  - `start_cursor(history_after: str | None, events_after: str | None, current: Cursor) -> tuple[Cursor, bool]` (raises `ValueError`)
  - `changes_since(session: Session, cursor: Cursor) -> tuple[list[dict], Cursor]`
  - `origin_allowed(origin: str | None, extra: frozenset[str]) -> bool`

- [ ] **Step 1: Write the failing tests** (`server/tests/test_live.py`)

```python
"""Temps réel (#5) : curseur, lecture des changements, contrôle d'origine."""

import pytest

from nexus import live
from nexus.live import Cursor, changes_since, current_cursor, origin_allowed, start_cursor

AT = "2026-09-30T09:00:00+02:00"
PRIVATE = "sujet confidentiel à ne jamais diffuser"


def new_task(client, title="Pont"):
    res = client.post("/api/tasks", json={"title": title, "objective": "Lire"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def db(client):
    return client.app.state.sessionmaker()


def test_an_empty_base_has_a_zero_cursor(client):
    with db(client) as s:
        assert current_cursor(s) == Cursor(0, 0)


def test_no_change_means_no_message(client):
    with db(client) as s:
        start = current_cursor(s)
        assert changes_since(s, start) == ([], start)


def test_several_changes_of_one_task_become_one_message(client):
    with db(client) as s:
        start = current_cursor(s)
    ref = new_task(client)
    assert client.patch(f"/api/tasks/{ref}", json={"next_action": "relire"}).status_code == 200
    assert client.post(f"/api/tasks/{ref}/comments", json={"body": "noté"}).status_code == 201
    with db(client) as s:
        messages, end = changes_since(s, start)
    assert [(m["type"], m["task"]) for m in messages] == [("task_changed", ref)]
    assert messages[-1]["cursor"] == end.as_dict()
    assert end.history > start.history


def test_events_carry_kind_and_references_but_no_free_text(client):
    ref = new_task(client)
    with db(client) as s:
        start = current_cursor(s)
    res = client.post("/api/events", json={
        "id": "evt_live", "at": AT, "actor": "helios", "kind": "progress",
        "subject": PRIVATE, "body": PRIVATE, "task": ref, "payload": {"percent": 10},
    })
    assert res.status_code == 201, res.text
    with db(client) as s:
        messages, end = changes_since(s, start)
    # Un événement peut aussi changer la tâche (task_changed) : on ne juge que le message
    # d'événement, dernier de la relecture, donc porteur du curseur de fin.
    assert messages[-1] == {
        "type": "event", "event": res.json()["id"], "task": ref, "kind": "progress",
        "cursor": end.as_dict(),
    }
    assert [m for m in messages if m["type"] == "event"] == messages[-1:]
    assert PRIVATE not in str(messages)


def test_only_the_last_message_of_a_batch_advances_the_cursor(client):
    with db(client) as s:
        start = current_cursor(s)
    a = new_task(client, "A")
    b = new_task(client, "B")
    with db(client) as s:
        messages, end = changes_since(s, start)
    assert [m["task"] for m in messages] == [a, b]
    assert messages[0]["cursor"] == start.as_dict()
    assert messages[1]["cursor"] == end.as_dict()


def test_too_many_changes_become_a_single_resync(client, monkeypatch):
    monkeypatch.setattr(live, "RESYNC_THRESHOLD", 2)
    with db(client) as s:
        start = current_cursor(s)
    for i in range(3):
        new_task(client, f"T{i}")
    with db(client) as s:
        messages, end = changes_since(s, start)
        latest = current_cursor(s)
    assert messages == [{"type": "resync", "cursor": latest.as_dict()}]
    assert end == latest


def test_no_cursor_starts_from_now():
    assert start_cursor(None, None, Cursor(5, 7)) == (Cursor(5, 7), False)


def test_a_valid_cursor_is_kept():
    assert start_cursor("3", "4", Cursor(5, 7)) == (Cursor(3, 4), False)


def test_a_cursor_ahead_of_the_base_is_reset():
    assert start_cursor("9", "0", Cursor(5, 7)) == (Cursor(5, 7), True)


@pytest.mark.parametrize(
    ("history", "events"), [("x", "1"), ("-1", "0"), ("1", None), ("9" * 13, "0"), ("²", "0")]
)
def test_invalid_cursor_parameters_are_refused(history, events):
    with pytest.raises(ValueError):
        start_cursor(history, events, Cursor(5, 5))


@pytest.mark.parametrize(
    "origin",
    [None, "http://localhost:5173", "http://127.0.0.1:8765", "http://[::1]:5199", "https://localhost"],
)
def test_loopback_origins_are_allowed(origin):
    assert origin_allowed(origin, frozenset())


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "http://localhost.evil.example", "http://127.0.0.1@evil.example",
     "null", "file://", "http://localhost:99999", "ftp://localhost"],
)
def test_foreign_origins_are_refused(origin):
    assert not origin_allowed(origin, frozenset())


def test_a_configured_origin_is_allowed_exactly():
    extra = frozenset({"tauri://localhost"})
    assert origin_allowed("tauri://localhost", extra)
    assert not origin_allowed("tauri://localhost.evil", extra)
```

- [ ] **Step 2: Run them to verify they fail**

Run (from `F:\Projet\Nexus`): `uv run --directory server pytest tests/test_live.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'nexus.live'`.

- [ ] **Step 3: Implement `server/src/nexus/live.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/test_live.py -q` then `uv run --directory server ruff check src tests` then `uv run --directory server pytest -q`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add server/src/nexus/live.py server/tests/test_live.py
git commit -m "feat: curseur et lecture des changements pour le temps réel (#5)"
```

---

### Task 2: Point d'entrée WebSocket `/api/ws`

**Files:**
- Modify: `server/src/nexus/live.py` (append the endpoint), `server/src/nexus/config.py` (`allowed_origins`), `server/src/nexus/app.py` (`app.state.settings`, `include_router`)
- Test: `server/tests/test_live.py` (append)

**Interfaces:**
- Consumes: Task 1 functions and constants (read at call time through the module, so tests can monkeypatch `live.PING_SECONDS`).
- Produces: `nexus.live.router` (APIRouter) with `@router.websocket("/api/ws")`; `Settings.allowed_origins: frozenset[str]` (env `NEXUS_ALLOWED_ORIGINS`, comma-separated, stripped, empty items ignored); `app.state.settings`.

- [ ] **Step 1: Write the failing tests** (append to `server/tests/test_live.py`)

```python
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from nexus.config import Settings  # noqa: E402


def test_hello_without_cursor_starts_from_now(client):
    new_task(client)
    with db(client) as s:
        now = current_cursor(s)
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json() == {"type": "hello", "cursor": now.as_dict(), "reset": False}


def test_a_reconnection_replays_what_was_missed(client):
    with db(client) as s:
        before = current_cursor(s)
    ref = new_task(client)
    url = f"/api/ws?history_after={before.history}&events_after={before.events}"
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "hello"
        message = ws.receive_json()
    assert (message["type"], message["task"]) == ("task_changed", ref)


def test_a_change_after_connecting_is_pushed_live(client):
    with client.websocket_connect("/api/ws") as ws:
        ws.receive_json()  # hello
        ref = new_task(client)
        message = ws.receive_json()
    assert (message["type"], message["task"]) == ("task_changed", ref)


def test_silence_is_broken_by_a_ping(client, monkeypatch):
    monkeypatch.setattr(live, "PING_SECONDS", 0.3)
    with client.websocket_connect("/api/ws") as ws:
        hello = ws.receive_json()
        assert ws.receive_json() == {"type": "ping", "cursor": hello["cursor"]}


def test_a_cursor_ahead_of_the_base_announces_a_reset(client):
    with client.websocket_connect("/api/ws?history_after=999&events_after=999") as ws:
        assert ws.receive_json()["reset"] is True


def test_a_foreign_origin_is_refused(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws", headers={"origin": "https://evil.example"}):
            pass


def test_a_loopback_origin_is_accepted(client):
    with client.websocket_connect("/api/ws", headers={"origin": "http://localhost:5199"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_an_invalid_cursor_is_refused_without_echo(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/api/ws?history_after=ghp_trace&events_after=0"):
            pass
    assert "ghp_trace" not in str(closed.value.reason or "")


def test_allowed_origins_are_read_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_ALLOWED_ORIGINS", " tauri://localhost , ,http://tauri.localhost")
    assert Settings.from_env().allowed_origins == frozenset(
        {"tauri://localhost", "http://tauri.localhost"}
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --directory server pytest tests/test_live.py -q`
Expected: the new WebSocket tests FAIL (route not found → `WebSocketDisconnect` on connect for the accepting tests; `AttributeError`/`TypeError` for `allowed_origins`). If a test hangs on `receive_json`, stop it (Ctrl+C) — that means the route answered but sent nothing; report it.

- [ ] **Step 3: Implement**

`server/src/nexus/config.py` — add the field after `nodes_refresh_seconds` and read it in `from_env`:

```python
    nodes_refresh_seconds: float = 60.0
    # Origines admises en plus de la boucle locale pour le WebSocket (ex. Tauri plus tard).
    allowed_origins: frozenset[str] = frozenset()
```

```python
            nodes_refresh_seconds=float(os.environ.get("NEXUS_NODES_REFRESH_SECONDS", "60")),
            allowed_origins=frozenset(
                item.strip()
                for item in os.environ.get("NEXUS_ALLOWED_ORIGINS", "").split(",")
                if item.strip()
            ),
```

`server/src/nexus/live.py` — add imports at the top (`import asyncio`, `from contextlib import suppress`, `from fastapi import APIRouter, WebSocket, WebSocketDisconnect`) and append:

```python
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
            await asyncio.to_thread(read_current),
        )
    except ValueError:
        # Raison générique : la valeur reçue n'est jamais recopiée.
        await websocket.close(code=1008, reason="curseur invalide")
        return
    await websocket.accept()
    await websocket.send_json({"type": "hello", "cursor": cursor.as_dict(), "reset": reset})

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
        with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await task
    for task in done:
        with suppress(WebSocketDisconnect, RuntimeError):
            task.result()  # une fermeture côté client pendant un envoi n'est pas une erreur
```

`server/src/nexus/app.py` — import `live` with the other routers (`from nexus import live`), store the settings, include the router:

```python
    app = FastAPI(title="Nexus", version=version("nexus"), lifespan=lifespan)
    app.state.settings = settings
    app.include_router(tasks_api.router)
    app.include_router(events_api.router)
    app.include_router(live.router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/test_live.py -q`, then `uv run --directory server ruff check src tests`, then `uv run --directory server pytest -q`.
Expected: all PASS; no warning about un-awaited coroutines or tasks destroyed while pending.

- [ ] **Step 5: Commit**

```bash
git add server/src/nexus/live.py server/src/nexus/config.py server/src/nexus/app.py server/tests/test_live.py
git commit -m "feat: WebSocket /api/ws, rattrapage par curseur et contrôle d'origine (#5)"
```

---

### Task 3: Connexion côté web (`live.ts`)

**Files:**
- Create: `web/src/live.ts`, `web/src/live.test.ts`

**Interfaces:**
- Produces:
  - `type Cursor = { history: number; events: number }`
  - `type LiveMessage = { type: 'hello'; cursor: Cursor; reset: boolean } | { type: 'task_changed'; task: string; cursor: Cursor } | { type: 'event'; event: string; task: string | null; kind: string; cursor: Cursor } | { type: 'resync'; cursor: Cursor } | { type: 'ping'; cursor: Cursor }`
  - `type LiveState = { status: 'connecting' } | { status: 'connected' } | { status: 'reconnecting'; attempt: number } | { status: 'unknown'; attempt: number }`
  - `type LiveSocket = { onopen: ((event: Event) => void) | null; onmessage: ((event: MessageEvent) => void) | null; onclose: ((event: CloseEvent) => void) | null; close(): void }` (a real `WebSocket` is assignable to it; not `Pick<WebSocket, …>`, whose handlers demand `this: WebSocket` and would not typecheck on the test fake)
  - constants `RECONNECT_MIN_MS = 500`, `RECONNECT_MAX_MS = 10_000`, `UNKNOWN_AFTER_MS = 30_000`, `SILENCE_MS = 45_000`
  - `reconnectDelay(attempt: number, random?: () => number): number`
  - `liveUrl(cursor: Cursor | null, location?: { protocol: string; host: string }): string`
  - `connectLive(options: { open: (url: string) => LiveSocket; onMessage: (m: LiveMessage) => void; onState: (s: LiveState) => void; random?: () => number }): () => void` (returns `stop`)

- [ ] **Step 1: Write the failing tests** (`web/src/live.test.ts`)

```ts
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import {
  connectLive,
  liveUrl,
  reconnectDelay,
  SILENCE_MS,
  UNKNOWN_AFTER_MS,
  type LiveMessage,
  type LiveSocket,
  type LiveState,
} from './live'

type Fake = LiveSocket & { url: string; closed: boolean }

function harness() {
  const sockets: Fake[] = []
  const states: LiveState[] = []
  const messages: LiveMessage[] = []
  const stop = connectLive({
    open: (url) => {
      const socket: Fake = {
        url,
        closed: false,
        onopen: null,
        onmessage: null,
        onclose: null,
        close() {
          this.closed = true
        },
      }
      sockets.push(socket)
      return socket
    },
    onMessage: (m) => messages.push(m),
    onState: (s) => states.push(s),
    random: () => 0.5, // aléa neutre : attente exacte
  })
  const last = () => sockets[sockets.length - 1]
  const open = () => last().onopen?.(new Event('open'))
  const send = (data: unknown) =>
    last().onmessage?.({ data: typeof data === 'string' ? data : JSON.stringify(data) } as MessageEvent)
  const drop = () => last().onclose?.({} as CloseEvent)
  return { sockets, states, messages, stop, last, open, send, drop }
}

const HELLO = { type: 'hello', cursor: { history: 3, events: 4 }, reset: false }

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('reconnectDelay', () => {
  test('double à chaque essai à partir de 0,5 s', () => {
    expect([1, 2, 3].map((n) => reconnectDelay(n, () => 0.5))).toEqual([500, 1000, 2000])
  })
  test('plafonne à 10 s', () => {
    expect(reconnectDelay(12, () => 0.5)).toBe(10_000)
  })
  test('ajoute un aléa de ±20 %', () => {
    expect(reconnectDelay(1, () => 0)).toBe(400)
    expect(reconnectDelay(1, () => 1)).toBe(600)
  })
})

describe('liveUrl', () => {
  test('sans curseur, part de maintenant', () => {
    expect(liveUrl(null, { protocol: 'http:', host: 'localhost:5173' })).toBe('ws://localhost:5173/api/ws')
  })
  test('avec curseur, demande le rattrapage ; https donne wss', () => {
    expect(liveUrl({ history: 3, events: 4 }, { protocol: 'https:', host: 'nexus.local' })).toBe(
      'wss://nexus.local/api/ws?history_after=3&events_after=4',
    )
  })
})

describe('connectLive', () => {
  test('connexion : connecting puis connected', () => {
    const h = harness()
    expect(h.states).toEqual([{ status: 'connecting' }])
    h.open()
    expect(h.states.at(-1)).toEqual({ status: 'connected' })
  })

  test('transmet les messages et ignore un message illisible', () => {
    const h = harness()
    h.open()
    h.send(HELLO)
    h.send('pas du json')
    expect(h.messages).toEqual([HELLO])
  })

  test('après une coupure, attend puis se reconnecte avec le dernier curseur', () => {
    const h = harness()
    h.open()
    h.send(HELLO)
    h.drop()
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    vi.advanceTimersByTime(499)
    expect(h.sockets).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(h.sockets).toHaveLength(2)
    expect(h.last().url).toContain('history_after=3&events_after=4')
  })

  test('passe à unknown après 30 s sans connexion', () => {
    const h = harness()
    h.open()
    h.drop()
    vi.advanceTimersByTime(UNKNOWN_AFTER_MS - 1)
    expect(h.states.at(-1)?.status).not.toBe('unknown')
    vi.advanceTimersByTime(1)
    expect(h.states.at(-1)?.status).toBe('unknown')
  })

  test('unknown tient pendant les essais suivants', () => {
    const h = harness()
    h.open()
    h.drop()
    vi.advanceTimersByTime(UNKNOWN_AFTER_MS)
    h.drop() // un nouvel essai échoue
    expect(h.states.at(-1)?.status).toBe('unknown')
  })

  test('sans connexion depuis le chargement, unknown compte depuis le chargement', () => {
    const h = harness()
    vi.advanceTimersByTime(10_000)
    h.drop() // le premier essai échoue au bout de 10 s
    vi.advanceTimersByTime(UNKNOWN_AFTER_MS - 10_000)
    expect(h.states.at(-1)?.status).toBe('unknown')
  })

  test('une connexion rétablie efface unknown', () => {
    const h = harness()
    vi.advanceTimersByTime(UNKNOWN_AFTER_MS) // jamais connecté depuis le chargement
    expect(h.states.at(-1)?.status).toBe('unknown')
    h.open()
    expect(h.states.at(-1)).toEqual({ status: 'connected' })
  })

  test('ferme une connexion restée muette 45 s', () => {
    const h = harness()
    h.open()
    vi.advanceTimersByTime(SILENCE_MS - 1)
    expect(h.last().closed).toBe(false)
    vi.advanceTimersByTime(1)
    expect(h.last().closed).toBe(true)
  })

  test('un message repousse le délai de silence', () => {
    const h = harness()
    h.open()
    vi.advanceTimersByTime(SILENCE_MS - 1)
    h.send({ type: 'ping', cursor: { history: 0, events: 0 } })
    vi.advanceTimersByTime(SILENCE_MS - 1)
    expect(h.last().closed).toBe(false)
  })

  test('stop ferme la connexion et ne reconnecte plus', () => {
    const h = harness()
    h.open()
    h.stop()
    expect(h.last().closed).toBe(true)
    h.drop()
    vi.advanceTimersByTime(60_000)
    expect(h.sockets).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm --dir web exec vitest run src/live.test.ts`
Expected: FAIL — `Failed to resolve import "./live"`.

- [ ] **Step 3: Implement `web/src/live.ts`**

```ts
/*
 * Temps réel (#5) : une connexion WebSocket vers /api/ws, avec reconnexion et rattrapage.
 * Le WebSocket est injecté (`open`) pour que la logique se teste sans réseau. Les messages
 * ne portent que des références : l'interface relit toujours les données par l'API REST.
 */
export type Cursor = { history: number; events: number }

export type LiveMessage =
  | { type: 'hello'; cursor: Cursor; reset: boolean }
  | { type: 'task_changed'; task: string; cursor: Cursor }
  | { type: 'event'; event: string; task: string | null; kind: string; cursor: Cursor }
  | { type: 'resync'; cursor: Cursor }
  | { type: 'ping'; cursor: Cursor }

export type LiveState =
  | { status: 'connecting' }
  | { status: 'connected' }
  | { status: 'reconnecting'; attempt: number }
  | { status: 'unknown'; attempt: number }

export type LiveSocket = {
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  close(): void
}

export const RECONNECT_MIN_MS = 500
export const RECONNECT_MAX_MS = 10_000
export const UNKNOWN_AFTER_MS = 30_000
export const SILENCE_MS = 45_000

export function reconnectDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(RECONNECT_MAX_MS, RECONNECT_MIN_MS * 2 ** (attempt - 1))
  return Math.round(base * (0.8 + 0.4 * random()))
}

export function liveUrl(
  cursor: Cursor | null,
  location: { protocol: string; host: string } = window.location,
): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  const query = cursor ? `?history_after=${cursor.history}&events_after=${cursor.events}` : ''
  return `${scheme}://${location.host}/api/ws${query}`
}

export function connectLive(options: {
  open: (url: string) => LiveSocket
  onMessage: (message: LiveMessage) => void
  onState: (state: LiveState) => void
  random?: () => number
}): () => void {
  let cursor: Cursor | null = null
  let socket: LiveSocket | null = null
  let attempt = 0
  let stopped = false
  let connected = false // une connexion est établie et pas encore perdue
  let unknown = false // plus de 30 s sans connexion : l'état reste tel jusqu'à la reconnexion
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined
  let silenceTimer: ReturnType<typeof setTimeout> | undefined
  let unknownTimer: ReturnType<typeof setTimeout> | undefined

  const armUnknown = () => {
    clearTimeout(unknownTimer)
    unknownTimer = setTimeout(() => {
      unknown = true
      options.onState({ status: 'unknown', attempt })
    }, UNKNOWN_AFTER_MS)
  }
  const armSilence = () => {
    clearTimeout(silenceTimer)
    silenceTimer = setTimeout(() => socket?.close(), SILENCE_MS) // la fermeture relance la reconnexion
  }

  const connect = () => {
    const current = options.open(liveUrl(cursor))
    socket = current
    current.onopen = () => {
      if (stopped) return
      attempt = 0
      connected = true
      unknown = false
      clearTimeout(unknownTimer)
      armSilence()
      options.onState({ status: 'connected' })
    }
    current.onmessage = (event) => {
      if (stopped) return
      armSilence()
      let message: LiveMessage
      try {
        message = JSON.parse(String(event.data)) as LiveMessage
      } catch {
        return // message illisible : ignoré, la relecture régulière reste le filet
      }
      cursor = message.cursor
      options.onMessage(message)
    }
    current.onclose = () => {
      if (stopped || socket !== current) return
      clearTimeout(silenceTimer)
      if (connected) {
        // Perte d'une connexion établie : les 30 s comptent d'ici. Sans connexion depuis le
        // chargement, elles comptent déjà depuis le chargement (on ne réarme pas).
        connected = false
        armUnknown()
      }
      attempt += 1
      options.onState(unknown ? { status: 'unknown', attempt } : { status: 'reconnecting', attempt })
      reconnectTimer = setTimeout(connect, reconnectDelay(attempt, options.random))
    }
  }

  options.onState({ status: 'connecting' })
  armUnknown() // aucune connexion depuis le chargement de la page
  connect()

  return () => {
    stopped = true
    clearTimeout(reconnectTimer)
    clearTimeout(silenceTimer)
    clearTimeout(unknownTimer)
    socket?.close()
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir web exec vitest run src/live.test.ts`, `pnpm typecheck`, `pnpm --dir web exec oxlint src`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/live.ts web/src/live.test.ts
git commit -m "feat: connexion temps réel côté web, reconnexion et silence (#5)"
```

---

### Task 4: Invalidation des données et indicateur dans la barre d'état

**Files:**
- Create: `web/src/liveUpdates.ts`, `web/src/liveUpdates.test.ts`, `web/src/LiveStatus.tsx`, `web/src/LiveStatus.test.tsx`
- Modify: `web/src/App.tsx` (call the hook, pass the state to `HealthStatus`), `web/src/HealthStatus.tsx` (optional `live` prop rendered with `LiveStatus`)

**Interfaces:**
- Consumes: `connectLive`, `LiveMessage`, `LiveState` (Task 3); `tasksKey = ['tasks']` from `web/src/tasks/queries.ts` (task detail keys are `['tasks', <task id like 'nx-task-3'>, 'comments' | 'history']`); `REFRESH_MS` from `web/src/freshness.ts`.
- Produces: `applyLiveMessage(client: QueryClient, message: LiveMessage): void`; `useLiveUpdates(): LiveState`; `LiveStatus({ state }: { state: LiveState })`; `HealthStatus({ live }: { live?: LiveState })`.

- [ ] **Step 1: Write the failing tests**

`web/src/liveUpdates.test.ts`:

```ts
import { QueryClient } from '@tanstack/react-query'
import { describe, expect, test, vi } from 'vitest'
import { applyLiveMessage } from './liveUpdates'

const CURSOR = { history: 1, events: 1 }

function spyClient() {
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue(undefined)
  return { client, invalidate }
}

describe('applyLiveMessage', () => {
  test('une tâche changée relit la liste et le détail de cette tâche', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'task_changed', task: 'nx-task-3', cursor: CURSOR })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks'], exact: true })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks', 'nx-task-3'] })
  })

  test('un événement relit les événements et sa tâche', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'event', event: 'nx-evt-9', task: 'nx-task-3', kind: 'done', cursor: CURSOR })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['events'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks', 'nx-task-3'] })
  })

  test('un événement sans tâche ne relit que les événements', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'event', event: 'nx-evt-9', task: null, kind: 'unknown', cursor: CURSOR })
    expect(invalidate).toHaveBeenCalledTimes(1)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['events'] })
  })

  test('resync ou reset relisent tout', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'resync', cursor: CURSOR })
    applyLiveMessage(client, { type: 'hello', cursor: CURSOR, reset: true })
    expect(invalidate).toHaveBeenCalledTimes(2)
    expect(invalidate).toHaveBeenNthCalledWith(1)
    expect(invalidate).toHaveBeenNthCalledWith(2)
  })

  test('hello ordinaire et ping ne relisent rien', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'hello', cursor: CURSOR, reset: false })
    applyLiveMessage(client, { type: 'ping', cursor: CURSOR })
    expect(invalidate).not.toHaveBeenCalled()
  })
})
```

`web/src/LiveStatus.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { LiveStatus } from './LiveStatus'

test.each([
  [{ status: 'connected' } as const, 'Temps réel : connecté'],
  [{ status: 'connecting' } as const, 'Temps réel : connexion…'],
  [{ status: 'reconnecting', attempt: 3 } as const, 'Temps réel : reconnexion… (essai 3)'],
  [{ status: 'unknown', attempt: 5 } as const, 'Temps réel : unknown — relecture toutes les 10 s'],
])('affiche l’état %o', (state, text) => {
  render(<LiveStatus state={state} />)
  expect(screen.getByText(text)).toBeInTheDocument()
})

test('unknown est mis en évidence', () => {
  render(<LiveStatus state={{ status: 'unknown', attempt: 1 }} />)
  expect(screen.getByText(/unknown/)).toHaveClass('text-attention')
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm --dir web exec vitest run src/liveUpdates.test.ts src/LiveStatus.test.tsx`
Expected: FAIL — imports cannot be resolved.

- [ ] **Step 3: Implement**

`web/src/liveUpdates.ts`:

```ts
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { connectLive, type LiveMessage, type LiveState } from './live'
import { tasksKey } from './tasks/queries'

/** Un message ne fait que dire quoi relire : les données passent toujours par l'API REST. */
export function applyLiveMessage(client: QueryClient, message: LiveMessage): void {
  switch (message.type) {
    case 'task_changed':
      void client.invalidateQueries({ queryKey: tasksKey, exact: true })
      void client.invalidateQueries({ queryKey: ['tasks', message.task] })
      return
    case 'event':
      void client.invalidateQueries({ queryKey: ['events'] })
      if (message.task) void client.invalidateQueries({ queryKey: ['tasks', message.task] })
      return
    case 'resync':
      void client.invalidateQueries()
      return
    case 'hello':
      if (message.reset) void client.invalidateQueries()
      return
    case 'ping':
      return
  }
}

/** Connexion temps réel de l'application ; la relecture toutes les 10 s reste le filet. */
export function useLiveUpdates(): LiveState {
  const client = useQueryClient()
  const [state, setState] = useState<LiveState>({ status: 'connecting' })
  useEffect(
    () =>
      connectLive({
        open: (url) => new WebSocket(url),
        onMessage: (message) => applyLiveMessage(client, message),
        onState: setState,
      }),
    [client],
  )
  return state
}
```

`web/src/LiveStatus.tsx`:

```tsx
import clsx from 'clsx'
import { REFRESH_MS } from './freshness'
import type { LiveState } from './live'

function describe(state: LiveState): string {
  switch (state.status) {
    case 'connected':
      return 'Temps réel : connecté'
    case 'connecting':
      return 'Temps réel : connexion…'
    case 'reconnecting':
      return `Temps réel : reconnexion… (essai ${state.attempt})`
    case 'unknown':
      return `Temps réel : unknown — relecture toutes les ${REFRESH_MS.tasks / 1000} s`
  }
}

/** État du temps réel dans la barre du bas ; aucune animation, seul l'état change le texte. */
export function LiveStatus({ state }: { state: LiveState }) {
  return (
    <span className={clsx('shrink-0', state.status === 'unknown' ? 'text-attention' : 'text-muted')}>
      {describe(state)}
    </span>
  )
}
```

`web/src/HealthStatus.tsx` — accept an optional `live` prop and render it at the end of the footer (existing tests render `<HealthStatus />` without it and must keep passing):

```tsx
import type { LiveState } from './live'
import { LiveStatus } from './LiveStatus'
// …
export function HealthStatus({ live }: { live?: LiveState } = {}) {
  // … existing body unchanged …
      {detail && <span className="min-w-0 break-words">{detail}</span>}
      {live && <LiveStatus state={live} />}
    </footer>
```

(Keep the existing `detail` span exactly as it is today; only add the `live` line before `</footer>`.)

`web/src/App.tsx` — call the hook once and pass it down:

```tsx
import { useLiveUpdates } from './liveUpdates'
// … inside App():
  const live = useLiveUpdates()
// …
      <HealthStatus live={live} />
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir web exec vitest run`, `pnpm typecheck`, `pnpm --dir web exec oxlint src`
Expected: all PASS (existing HealthStatus tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add web/src/liveUpdates.ts web/src/liveUpdates.test.ts web/src/LiveStatus.tsx web/src/LiveStatus.test.tsx web/src/HealthStatus.tsx web/src/App.tsx
git commit -m "feat: invalidations temps réel et état dans la barre du bas (#5)"
```

---

### Task 5: Parcours Playwright — moins d'une seconde, et rien de perdu après une coupure

**Files:**
- Modify: `web/e2e/work.spec.ts` (append two tests)

**Interfaces:**
- Consumes: the API on `http://127.0.0.1:8799` (see `web/playwright.config.ts`: `API_PORT = '8799'`) and the helper already in the file: `const card = (page: Page, title: string) => page.getByRole('button', { name: new RegExp(`^${title} —`) })`. The task creation response's `id` is the task ref (`nx-task-N`).

- [ ] **Step 1: Write the tests** (append to `web/e2e/work.spec.ts`)

```ts
const API = 'http://127.0.0.1:8799'

test('une tâche créée par l’API apparaît en moins d’une seconde', async ({ page, request }) => {
  await page.goto('/')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  const res = await request.post(`${API}/api/tasks`, {
    data: { title: 'Arrivée en direct', objective: 'Prouver le temps réel' },
  })
  expect(res.ok()).toBeTruthy()
  await expect(card(page, 'Arrivée en direct')).toBeVisible({ timeout: 1000 })
})

test('après une coupure, la reconnexion rattrape ce qui a changé', async ({ page, request }) => {
  // Chaque connexion est numérotée : seuls comptent les messages reçus APRÈS la coupure.
  // Sans cela, la connexion d'avant (côté serveur) pourrait livrer le changement en direct
  // et le test passerait sans prouver le rattrapage.
  const log: { connection: number; message: string }[] = []
  let connections = 0
  let blocked = false
  let open: { page: WebSocketRoute; server: WebSocketRoute } | null = null
  await page.routeWebSocket(/\/api\/ws/, (ws) => {
    if (blocked) {
      void ws.close({ code: 1011, reason: 'coupure simulée' })
      return
    }
    const connection = ++connections
    const server = ws.connectToServer()
    server.onMessage((message) => {
      log.push({ connection, message: String(message) })
      ws.send(message)
    })
    open = { page: ws, server }
  })
  await page.goto('/')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()

  blocked = true
  const cut = connections
  await open!.server.close()
  await open!.page.close({ code: 1011, reason: 'coupure simulée' })
  await expect(page.getByText(/Temps réel : reconnexion/)).toBeVisible()

  const res = await request.post(`${API}/api/tasks`, {
    data: { title: 'Pendant la coupure', objective: 'Rattrapage' },
  })
  expect(res.ok()).toBeTruthy()
  const ref = (await res.json()).id as string

  blocked = false
  await expect(page.getByText('Temps réel : connecté')).toBeVisible({ timeout: 15_000 })
  await expect
    .poll(
      () =>
        log.some(
          (entry) =>
            entry.connection > cut &&
            entry.message.includes('"task_changed"') &&
            entry.message.includes(`"${ref}"`),
        ),
      { timeout: 5000 },
    )
    .toBe(true)
  await expect(card(page, 'Pendant la coupure')).toBeVisible()
})
```

Add `type WebSocketRoute` to the existing `@playwright/test` import at the top of the file (`import { expect, test, type Page, type WebSocketRoute } from '@playwright/test'`).

Note for the implementer: the test's goal is fixed — cut the live connection, create a task through the API while cut, reconnect, and prove the **reconnection** delivered a `task_changed` for that task (log entries from a connection numbered after the cut), not the 10 s polling nor the old connection. If a Playwright 1.63 detail differs (e.g. `WebSocketRoute.close()` signature), adapt the mechanics, never the assertions. A route-level refusal while `blocked` makes the page see an immediate close, so the client keeps retrying with backoff (0.5 s, 1 s, 2 s…) and reconnects within a few seconds of `blocked = false`.

- [ ] **Step 2: Run the suite**

Run: `pnpm e2e`
Expected: all scenarios PASS, including both new ones.

- [ ] **Step 3: Prove each test bites** (do not commit the mutations)

- Temporarily make `applyLiveMessage` a no-op for `task_changed` (`return` at the top of the case) → the first test must FAIL on the 1 s timeout. Restore. (The 10 s polling can coincide with the 1 s window about one run in ten: if the mutant passes once, run it again; it must fail at least twice in three runs.)
- Temporarily make `liveUrl` ignore the cursor (always return the URL without query) → the second test must FAIL on the `received` poll. Restore. `git diff -- web/src` must be empty afterwards.

- [ ] **Step 4: Commit**

```bash
git add web/e2e/work.spec.ts
git commit -m "test: parcours temps réel, moins d'une seconde et rattrapage après coupure (#5)"
```

---

### Task 6: Documentation et checklist

**Files:**
- Modify: `docs/EVENT-PROTOCOL.md` (§6 « Diffusion »), `docs/agents/review-checklist.md`

- [ ] **Step 1: EVENT-PROTOCOL §6** — replace the current line 128 (`- **Diffusion :** l'UI reçoit les nouveaux événements par WebSocket ; les alertes urgentes (`needs_human`, `blocked` critique) partent aussi sur Telegram.`) with:

```markdown
- **Diffusion :** l'interface écoute `/api/ws` (WebSocket) : messages minces (`hello`, `task_changed`, `event`, `resync`, `ping`) qui ne portent que des références et un curseur ; l'interface relit ensuite par l'API REST. Rattrapage après coupure par le curseur `{history, events}`. Format et règles : `docs/superpowers/specs/2026-09-30-temps-reel-design.md`. Les alertes urgentes (`needs_human`, `blocked` critique) partiront aussi sur Telegram (hors Phase 1).
```

- [ ] **Step 2: Checklist** — in §1 Secrets add:

```markdown
- [ ] A WebSocket route checks the `Origin` header (loopback or explicitly configured only — CORS does not protect WebSockets) and never sends received free text: messages carry references, kinds and cursors; the UI re-reads through the REST API.
```

- [ ] **Step 3: Commit**

```bash
git add docs/EVENT-PROTOCOL.md docs/agents/review-checklist.md
git commit -m "docs: diffusion temps réel et règle WebSocket dans la checklist (#5)"
```

- [ ] **Step 4: Pre-PR gate** — walk `docs/agents/review-checklist.md`; run `pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm --dir web build`, `pnpm e2e`; push; open the PR (`Closes #5`) with the checklist notes; run the `antigravity` skill review until clean (and, as agreed with Loïc, a comparison run with `claude-opus-4-6-thinking`); then `@codex review` (final gate; merge when a round has no P1, P2s go to an issue).
