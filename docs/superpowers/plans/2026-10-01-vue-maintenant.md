# Vue Maintenant — plan d'implémentation (#6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** la page d'accueil « Maintenant » montre en 5 secondes, sur un étage isométrique, qui travaille, ce qui t'attend, ce qui bloque, ce qui vient d'être fini et l'état des machines — uniquement à partir de mesures réelles.

**Architecture:** le serveur ajoute `GET /api/now` (`nexus/now.py`), un instantané lu en une transaction. Côté web, `web/src/now/` contient : les requêtes (`queries.ts`), la géométrie isométrique pure (`iso.ts`), le modèle des postes (`model.ts`), le déclencheur de mouvement (`useArrivals.ts`), la scène (`Floor.tsx`), la liste des agents (`AgentList.tsx`) et la vue (`NowView.tsx`). Le thème sombre « Salle orbitale » est une classe CSS `orbital` qui redéfinit les jetons, appliquée à la navigation, la barre d'état et Maintenant.

**Tech Stack:** FastAPI + SQLAlchemy/SQLite, pytest ; React 19 + TypeScript, Tailwind 4, TanStack Query, Vitest, Playwright ; polices `@fontsource` embarquées.

**Spec:** `docs/superpowers/specs/2026-10-01-vue-maintenant-design.md` · maquette validée : https://claude.ai/artifact/CDYbnTCWL6VoE66YkaYvkW

## Global Constraints

- Branche `feat/6-maintenant`. Chaque commit passe par le hook pre-commit (gitleaks, lint, `tsc`, toutes les suites) ; `--no-verify` interdit. Éditer avec Write/Edit, jamais sed/heredoc sur du code.
- Textes d'interface en français ; identifiants en anglais. Messages de commit terminés par une ligne vide puis `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Demandes reçues = événements `question` et `needs_human` dont `needs` contient `loic`, reçus dans les 7 derniers jours, les plus récents d'abord ; jamais le mot « en attente ».
- Derniers done : 7 derniers jours, 5 au plus, plus récents d'abord.
- Couleurs d'état (thème orbital) : run `#5eead4`, attend Loïc `#fb923c`, blocage `#f87171`, en ligne `#4ade80`, unknown/hors ligne `#8b8b95` ; fond `#07080a`, surface `#0b0c0e`, filet `#22252b`, encre `#f4f4f5`, secondaire `#a1a1aa`. Texte ≥ 11 px, contraste ≥ 4,5:1.
- Mouvement seulement sur un vrai changement d'état ; aucun au premier rendu ; rien en boucle ; `prefers-reduced-motion` coupe tout.
- Durées : balise 500 ms, étincelle 1,1 s (une fois), fond ambre d'une nouvelle ligne 1,8 s, écran 450 ms, flaque 700 ms, hachures 300 ms, LED 400 ms.
- Aucun texte libre reçu n'est inventé ou recopié ailleurs que dans les champs déjà masqués par l'API (ADR-006). Aucune donnée décorative (ADR-005).
- Polices embarquées (pas de CDN) : Barlow 400/500/600, Barlow Condensed 500/600, IBM Plex Mono 400/500.

---

### Task 1: `GET /api/now` — l'instantané du serveur

**Files:**
- Create: `server/src/nexus/now.py`
- Modify: `server/src/nexus/app.py` (inclure le routeur)
- Test: `server/tests/test_now.py`

**Interfaces:**
- Produces: route `GET /api/now` → JSON :
  `{ source: "nexus.db", measured_at, operation: {task,title,lead_agent,since,next_action,due_at} | null, auxiliaries: [{task,title}], agents: [{agent, state: "run"|"idle", task, title, run, since}], asks: [{event, agent, kind, subject, task, at}], blocks: [{task,title,cause,since,follow_up_at,lead_agent}], done: [{task,title,agent,evidence,at}] }` — refs `nx-task-N` / `nx-evt-N`, instants ISO 8601 avec fuseau.
- `agents` suit l'ordre de `typing.get_args(nexus.actors.Agent)` : helios, mnema, aether, artemis, claude, codex, orca, hermes.

- [ ] **Step 1: Write the failing tests** (`server/tests/test_now.py`)

```python
"""Vue Maintenant (#6) : l'instantané GET /api/now."""

from datetime import timedelta

from nexus.clock import now

AT = "2026-09-30T09:00:00+02:00"


def create(client, **fields):
    body = {"title": "Pont lecture", "objective": "Lire les runs"} | fields
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def move(client, ref, status, **fields):
    res = client.post(f"/api/tasks/{ref}/status", json={"status": status} | fields)
    assert res.status_code == 200, res.text
    return res.json()


def publish(client, kind, actor="helios", **fields):
    publish.n = getattr(publish, "n", 0) + 1
    body = {"id": f"evt_now_{publish.n}", "at": AT, "actor": actor, "kind": kind, "subject": "s"} | fields
    res = client.post("/api/events", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def snapshot(client):
    res = client.get("/api/now")
    assert res.status_code == 200, res.text
    return res.json()


def test_an_empty_base_is_an_honest_snapshot(client):
    s = snapshot(client)
    assert s["source"] == "nexus.db" and s["measured_at"]
    assert s["operation"] is None and s["auxiliaries"] == []
    assert [a["agent"] for a in s["agents"]] == [
        "helios", "mnema", "aether", "artemis", "claude", "codex", "orca", "hermes"]
    assert all(a["state"] == "idle" and a["task"] is None for a in s["agents"])
    assert s["asks"] == [] and s["blocks"] == [] and s["done"] == []


def test_the_main_operation_and_its_auxiliaries(client):
    main = create(client, title="Refonte du pont", next_action="relire les tables")
    move(client, main, "in_progress")
    aux = create(client, title="Doc d'installation", operation_role="auxiliary", next_action="x")
    s = snapshot(client)
    assert s["operation"]["task"] == main
    assert s["operation"]["title"] == "Refonte du pont"
    assert s["operation"]["next_action"] == "relire les tables"
    assert s["operation"]["since"]
    assert s["auxiliaries"] == [{"task": aux, "title": "Doc d'installation"}]


def test_an_open_run_makes_the_agent_run_and_a_closer_makes_it_idle(client):
    ref = create(client, title="Refonte du pont", status="todo", next_action="x")
    publish(client, "claimed", task=ref)
    publish(client, "working", task=ref, payload={"run_ref": "session:abc"})
    helios = snapshot(client)["agents"][0]
    assert helios == {"agent": "helios", "state": "run", "task": ref, "title": "Refonte du pont",
                      "run": "session:abc", "since": helios["since"]}
    assert helios["since"]
    publish(client, "blocked", task=ref, run="session:abc", body="SSH", payload={"plan": "rallumer"})
    assert snapshot(client)["agents"][0]["state"] == "idle"


def test_asks_are_questions_and_needs_human_for_loic_within_seven_days(client):
    ref = create(client)
    q = publish(client, "question", actor="mnema", subject="Quelle version ?", task=ref, needs=["loic"])
    publish(client, "question", actor="mnema", subject="Pour Helios", needs=["helios"])
    publish(client, "progress", actor="mnema", task=ref, payload={"percent": 5})
    s = snapshot(client)
    assert [a["event"] for a in s["asks"]] == [q["id"]]
    assert s["asks"][0] == {"event": q["id"], "agent": "mnema", "kind": "question",
                            "subject": "Quelle version ?", "task": ref, "at": s["asks"][0]["at"]}


def test_the_seven_day_window_is_on_reception_not_on_the_claimed_date(client):
    old = (now() - timedelta(days=8)).isoformat()
    publish(client, "needs_human", actor="helios", at=old, needs=["loic"], subject="Antidaté")
    # un événement antidaté mais reçu aujourd'hui est bien une demande récente
    assert [a["subject"] for a in snapshot(client)["asks"]] == ["Antidaté"]


def test_asks_received_more_than_seven_days_ago_are_left_out(client, monkeypatch):
    publish(client, "needs_human", actor="helios", needs=["loic"], subject="Ancienne")
    later = now() + timedelta(days=7, minutes=1)
    monkeypatch.setattr("nexus.now.now", lambda: later)
    assert snapshot(client)["asks"] == []


def test_blocks_and_their_start(client):
    ref = create(client, title="Sauvegarde distante", next_action="x", lead_agent="artemis")
    move(client, ref, "in_progress")
    move(client, ref, "blocked", block_cause="Artemis hors ligne", block_plan="rallumer")
    b = snapshot(client)["blocks"]
    assert len(b) == 1
    assert b[0]["task"] == ref and b[0]["cause"] == "Artemis hors ligne"
    assert b[0]["lead_agent"] == "artemis" and b[0]["since"]


def test_recent_done_with_evidence_at_most_five(client):
    refs = []
    for i in range(6):
        ref = create(client, title=f"T{i}", next_action="x")
        move(client, ref, "in_progress")
        move(client, ref, "done", evidence=[f"PR #{i}"])
        refs.append(ref)
    done = snapshot(client)["done"]
    assert [d["task"] for d in done] == list(reversed(refs))[:5]
    assert done[0]["evidence"] == ["PR #5"] and done[0]["at"]
```

- [ ] **Step 2: Run them to verify they fail**

Run (repo root): `uv run --directory server pytest tests/test_now.py -q`
Expected: every test FAILS with 404 on `/api/now`.
If a helper's API call is refused for a reason unrelated to `/api/now` (a task rule: e.g. `move(..., "done", evidence=...)` needs a different field name, or `blocked` needs `follow_up_at`), read `server/tests/test_tasks_api.py` / `test_events_api.py`, fix the helper call to follow the real rule, and note it in the report — never weaken the `/api/now` assertions.

- [ ] **Step 3: Implement `server/src/nexus/now.py`**

```python
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
    auxiliaries = [{"task": _ref(t.id), "title": t.title} for t in sorted(tasks.values(), key=lambda t: t.id)
                   if t.operation_role == "auxiliary" and t.status not in ("done", "dropped")]

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

    blocked = [(t, _entered(session, t, "blocked")) for t in tasks.values() if t.status == "blocked"]
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
```

`server/src/nexus/app.py`: import the module with the others (`from nexus import now as now_view` — the name `now` is already the clock import there) and add `app.include_router(now_view.router)` after `events_api.router`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest tests/test_now.py tests/test_provenance_contract.py -q`, then `uv run --directory server ruff check src tests`, then `uv run --directory server pytest -q`.
Expected: all PASS; the provenance contract test now also walks `/api/now`.

- [ ] **Step 5: Commit**

```bash
git add server/src/nexus/now.py server/src/nexus/app.py server/tests/test_now.py
git commit -m "feat: instantané GET /api/now pour la vue Maintenant (#6)"
```

---

### Task 2: Données côté web — types, requêtes, temps réel

**Files:**
- Modify: `web/src/api.ts` (types `NowSnapshot`, `NodeState`, `nowApi`, `nodesApi`)
- Modify: `web/src/freshness.ts` (`'now'` dans `FreshnessKind`, `REFRESH_MS`, `SOURCE_OF`)
- Create: `web/src/now/queries.ts`
- Modify: `web/src/liveUpdates.ts` (invalider `['now']`)
- Test: `web/src/liveUpdates.test.ts`, `web/src/freshness.test.ts`

**Interfaces:**
- Produces (in `web/src/api.ts`):

```ts
export type AgentId = Exclude<Actor, 'loic'>
export type NowAgent = { agent: AgentId; state: 'run' | 'idle'; task: string | null; title: string | null; run: string | null; since: string | null }
export type NowAsk = { event: string; agent: Actor; kind: 'question' | 'needs_human'; subject: string; task: string | null; at: string; received_at: string }
export type NowBlock = { task: string; title: string; cause: string | null; since: string | null; follow_up_at: string | null; lead_agent: Actor | null }
export type NowDone = { task: string; title: string; agent: Actor | null; evidence: string[]; at: string }
export type NowSnapshot = {
  source: string; measured_at: string
  operation: { task: string; title: string; lead_agent: Actor | null; since: string | null; next_action: string | null; due_at: string | null } | null
  auxiliaries: { task: string; title: string }[]
  agents: NowAgent[]; asks: NowAsk[]; blocks: NowBlock[]; done: NowDone[]
}
export type NodeState = { id: string; kind: string; guardian_agent: string; status: 'online' | 'offline' | 'offline-by-design' | 'unknown'; last_seen: string | null; detail: string | null; source: string; measured_at: string }
export const nowApi = { get: (signal?: AbortSignal) => request<NowSnapshot>('/api/now', { signal }) }
export const nodesApi = { list: (signal?: AbortSignal) => request<NodeState[]>('/api/nodes', { signal }) }
```

- Produces (in `web/src/now/queries.ts`): `nowKey = ['now'] as const`, `nodesKey = ['nodes'] as const`, `useNowSnapshot()`, `useNodes()` (TanStack `useQuery`, `networkMode: 'always'`, `refetchInterval: REFRESH_MS.now` / `REFRESH_MS.nodes`).
- `REFRESH_MS.now = 10_000`, `SOURCE_OF.now = 'nexus.db'`.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/liveUpdates.test.ts` (inside the existing `describe`):

```ts
  test('un changement de tâche ou un événement relit aussi Maintenant', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'task_changed', task: 'nx-task-3', cursor: CURSOR })
    applyLiveMessage(client, { type: 'event', event: 'nx-evt-9', task: null, kind: 'question', cursor: CURSOR })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['now'] })
    expect(invalidate.mock.calls.filter(([f]) => JSON.stringify(f) === JSON.stringify({ queryKey: ['now'] }))).toHaveLength(2)
  })
```

The existing test « un événement sans tâche ne relit que les événements » asserts `toHaveBeenCalledTimes(1)`: update it to expect exactly two calls — `['events']` and `['now']` — and rename it « un événement sans tâche relit les événements et Maintenant ».

Append to `web/src/freshness.test.ts`:

```ts
test('Maintenant se relit comme les tâches, depuis nexus.db', () => {
  expect(REFRESH_MS.now).toBe(10_000)
  expect(SOURCE_OF.now).toBe('nexus.db')
})
```

(import `SOURCE_OF` if the file does not already.)

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm --dir web exec vitest run src/liveUpdates.test.ts src/freshness.test.ts`
Expected: FAIL (`['now']` never invalidated; `REFRESH_MS.now` undefined / typecheck error).

- [ ] **Step 3: Implement**

`web/src/freshness.ts`: `export type FreshnessKind = 'tasks' | 'health' | 'nodes' | 'now'`, add `now: 10_000` to `REFRESH_MS` and `now: 'nexus.db'` to `SOURCE_OF`.

`web/src/api.ts`: add the types and the two API objects above (after `tasksApi`).

`web/src/now/queries.ts`:

```ts
import { useQuery } from '@tanstack/react-query'
import { nodesApi, nowApi } from '@/api'
import { REFRESH_MS } from '@/freshness'

export const nowKey = ['now'] as const
export const nodesKey = ['nodes'] as const

// Serveur local : toujours tenter la requête, jamais de pause « hors ligne ».
const local = { networkMode: 'always' } as const

export function useNowSnapshot() {
  return useQuery({ queryKey: nowKey, queryFn: ({ signal }) => nowApi.get(signal), refetchInterval: REFRESH_MS.now, ...local })
}

export function useNodes() {
  return useQuery({ queryKey: nodesKey, queryFn: ({ signal }) => nodesApi.list(signal), refetchInterval: REFRESH_MS.nodes, ...local })
}
```

`web/src/liveUpdates.ts`: import `nowKey` from `./now/queries`; in `task_changed` and in `event`, add `void client.invalidateQueries({ queryKey: nowKey })`.

- [ ] **Step 4: Run tests**

Run: `pnpm --dir web exec vitest run`, `pnpm typecheck`, `pnpm --dir web exec oxlint src`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/api.ts web/src/freshness.ts web/src/freshness.test.ts web/src/now/queries.ts web/src/liveUpdates.ts web/src/liveUpdates.test.ts
git commit -m "feat: données de la vue Maintenant côté web, relues par le temps réel (#6)"
```

---

### Task 3: Thème « Salle orbitale » et polices embarquées

**Files:**
- Modify: `web/package.json` (dépendances `@fontsource/barlow`, `@fontsource/barlow-condensed`, `@fontsource/ibm-plex-mono`) via `pnpm --dir web add …`
- Modify: `web/src/main.tsx` (imports des poids de police)
- Modify: `web/src/index.css` (classe `.orbital`, jetons `--run`, `--unknown`, polices)
- Modify: `web/src/App.tsx` (classe `orbital` sur la navigation), `web/src/HealthStatus.tsx` (classe `orbital` sur la barre d'état)
- Test: `web/src/HealthStatus.test.tsx`

**Interfaces:**
- Produces: CSS class `orbital` (any element; redefines `--paper --surface --surface-sunken --ink --muted --line --accent --accent-soft --attention --attention-soft --danger --ok` and adds `--run --unknown`); Tailwind colors `bg-run text-run text-unknown` etc. via `--color-run`, `--color-unknown`; font utilities `font-orbital` (Barlow), `font-orbital-display` (Barlow Condensed), `font-data` (IBM Plex Mono).

- [ ] **Step 1: Write the failing test** (append to `web/src/HealthStatus.test.tsx`)

```tsx
test('la barre d\'état porte le thème orbital', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => healthy()))
  renderApp()
  expect(await screen.findByText('Base OK')).toBeInTheDocument()
  expect(screen.getByRole('contentinfo')).toHaveClass('orbital')
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm --dir web exec vitest run src/HealthStatus.test.tsx` — Expected: FAIL (no `orbital` class).

- [ ] **Step 3: Implement**

Run: `pnpm --dir web add @fontsource/barlow @fontsource/barlow-condensed @fontsource/ibm-plex-mono`

`web/src/main.tsx` (after `import './index.css'`):

```ts
import '@fontsource/barlow/400.css'
import '@fontsource/barlow/500.css'
import '@fontsource/barlow/600.css'
import '@fontsource/barlow-condensed/500.css'
import '@fontsource/barlow-condensed/600.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
```

`web/src/index.css` — after the dark `@media` block, add:

```css
/*
 * Thème « Salle orbitale » (#6) : quasi-noir, filets fins, couleur réservée aux états.
 * Palette proposée par Gemini, contrastes recalculés (texte ≥ 4,5:1). Appliqué par la classe
 * `orbital` : navigation, barre d'état, Maintenant. Travail garde le thème clair pour l'instant.
 */
.orbital {
  --paper: #07080a;
  --surface: #0b0c0e;
  --surface-sunken: #0e1013;
  --ink: #f4f4f5;
  --muted: #a1a1aa;
  --line: #22252b;
  --accent: #5eead4;
  --accent-soft: rgba(94, 234, 212, 0.08);
  --attention: #fb923c;
  --attention-soft: rgba(251, 146, 60, 0.06);
  --danger: #f87171;
  --ok: #4ade80;
  --run: #5eead4;
  --unknown: #8b8b95;
  color-scheme: dark;
  color: var(--ink);
}
```

In `@theme inline` add:

```css
  --font-orbital: 'Barlow', 'Segoe UI', system-ui, sans-serif;
  --font-orbital-display: 'Barlow Condensed', 'Bahnschrift', 'Segoe UI', sans-serif;
  --font-data: 'IBM Plex Mono', 'Cascadia Mono', ui-monospace, monospace;
  --color-run: var(--run);
  --color-unknown: var(--unknown);
```

and in `:root` (light) add `--run: #0f766e; --unknown: #575f6e;` so the utilities resolve outside `.orbital` too.

`web/src/App.tsx`: add `orbital` to the `<nav>` className (keep existing classes). `web/src/HealthStatus.tsx`: add `orbital` to the `<footer>` className.

- [ ] **Step 4: Run tests + look**

Run: `pnpm --dir web exec vitest run`, `pnpm typecheck`, `pnpm --dir web exec oxlint src`, `pnpm --dir web build`. Expected: PASS; the build output lists the `.woff2` files (fonts bundled, no Google Fonts URL anywhere: `grep -r "fonts.googleapis" web/src web/index.html` prints nothing).

- [ ] **Step 5: Commit**

```bash
git add web/package.json pnpm-lock.yaml web/src/main.tsx web/src/index.css web/src/App.tsx web/src/HealthStatus.tsx web/src/HealthStatus.test.tsx
git commit -m "feat: thème Salle orbitale et polices embarquées (#6)"
```
(If the lockfile lives in `web/`, add `web/pnpm-lock.yaml` instead; check `git status`.)

---

### Task 4: Géométrie isométrique et modèle des postes (fonctions pures)

**Files:**
- Create: `web/src/now/iso.ts`, `web/src/now/model.ts`
- Test: `web/src/now/iso.test.ts`, `web/src/now/model.test.ts`

**Interfaces:**
- Produces (`iso.ts`):

```ts
export type Pt = readonly [number, number]
export type Box = { top: string; left: string; right: string }       // attributs `points` des trois faces visibles
export type Seat = { x: number; y: number; back: boolean }           // coin du bureau, en unités de sol
export type Layout = {
  width: number; depth: number                                        // sol, en unités
  seats: Seat[]                                                       // dans l'ordre des agents
  table: { x: number; y: number; w: number; d: number }
  racks: { x: number; y: number }[]                                   // dans l'ordre des nœuds
  viewBox: { x: number; y: number; w: number; h: number }             // en px
  project: (x: number, y: number, z?: number) => Pt
}
export const DESK = { w: 3, d: 1.5, h: 0.75 }
export function layoutFloor(agentCount: number, rackCount: number): Layout
export function box(project: Layout['project'], x: number, y: number, z: number, w: number, d: number, h: number): Box
export function toPercent(layout: Layout, p: Pt): readonly [number, number]   // position dans le viewBox, en %
```

- Produces (`model.ts`): `AGE_TICK_MS = 30_000` (horloge des âges de la vue) and:

```ts
/** Les âges affichés sur Maintenant sont à la minute : une horloge à 30 s suffit, sans redessiner l'étage chaque seconde. */
export const AGE_TICK_MS = 30_000

export type SeatModel = { agent: AgentId; run: boolean; wait: boolean; block: boolean; task: string | null; title: string | null; since: string | null; asks: number }
export function seatModels(s: NowSnapshot): SeatModel[]        // même ordre que s.agents
export type RackTone = 'ok' | 'unknown' | 'off'
export function rackTone(n: NodeState): RackTone                // online → ok ; unknown → unknown ; offline / offline-by-design → off
export function rackLabel(n: NodeState): string                 // « en ligne », « unknown », « hors ligne », « hors ligne, prévu »
```

- [ ] **Step 1: Write the failing tests**

`web/src/now/iso.test.ts`:

```ts
import { describe, expect, test } from 'vitest'
import { DESK, box, layoutFloor, toPercent } from './iso'

describe('layoutFloor', () => {
  test('8 agents : deux rangées de 4, la table au centre', () => {
    const l = layoutFloor(8, 4)
    expect(l.seats).toHaveLength(8)
    expect(l.seats.filter((s) => s.back)).toHaveLength(4)
    const tableCenterX = l.table.x + l.table.w / 2
    const seatsCenterX = (Math.min(...l.seats.map((s) => s.x)) + Math.max(...l.seats.map((s) => s.x + DESK.w))) / 2
    expect(Math.abs(tableCenterX - seatsCenterX)).toBeLessThan(0.01)
    expect(l.racks).toHaveLength(4)
  })
  test('12 agents : les rangées s\'allongent, l\'étage s\'élargit', () => {
    const eight = layoutFloor(8, 4), twelve = layoutFloor(12, 4)
    expect(twelve.seats.filter((s) => s.back)).toHaveLength(6)
    expect(twelve.width).toBeGreaterThan(eight.width)
  })
  test('aucun bureau ne chevauche la table ni un autre bureau', () => {
    const l = layoutFloor(12, 4)
    const rects = [...l.seats.map((s) => ({ x: s.x, y: s.y, w: DESK.w, d: DESK.d })), { x: l.table.x, y: l.table.y, w: l.table.w, d: l.table.d }]
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i], b = rects[j]
      const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.d && b.y < a.y + a.d
      expect(overlap).toBe(false)
    }
  })
  test('tout le sol tient dans le viewBox', () => {
    const l = layoutFloor(8, 4), { x, y, w, h } = l.viewBox
    for (const [px, py] of [l.project(0, 0), l.project(l.width, 0), l.project(0, l.depth), l.project(l.width, l.depth)]) {
      expect(px).toBeGreaterThanOrEqual(x); expect(px).toBeLessThanOrEqual(x + w)
      expect(py).toBeGreaterThanOrEqual(y); expect(py).toBeLessThanOrEqual(y + h)
    }
  })
  test('1 agent et aucun nœud : un étage valable', () => {
    const l = layoutFloor(1, 0)
    expect(l.seats).toHaveLength(1)
    expect(l.racks).toHaveLength(0)
  })
})

describe('box', () => {
  test('rend trois faces de quatre points chacune', () => {
    const l = layoutFloor(8, 4)
    const b = box(l.project, 1, 1, 0, 3, 1.5, 0.75)
    for (const face of [b.top, b.left, b.right]) expect(face.split(' ')).toHaveLength(4)
  })
  test('le dessus est plus haut à l\'écran que le bas (z monte)', () => {
    const l = layoutFloor(8, 4)
    expect(l.project(1, 1, 1)[1]).toBeLessThan(l.project(1, 1, 0)[1])
  })
})

test('toPercent place un point du viewBox en pourcentage', () => {
  const l = layoutFloor(8, 4)
  const [px, py] = toPercent(l, [l.viewBox.x + l.viewBox.w / 2, l.viewBox.y + l.viewBox.h / 4])
  expect(px).toBeCloseTo(50); expect(py).toBeCloseTo(25)
})
```

`web/src/now/model.test.ts`:

```ts
import { expect, test } from 'vitest'
import type { NodeState, NowSnapshot } from '@/api'
import { rackLabel, rackTone, seatModels } from './model'

const base: NowSnapshot = {
  source: 'nexus.db', measured_at: '2026-10-01T10:00:00+02:00', operation: null, auxiliaries: [],
  agents: [
    { agent: 'helios', state: 'run', task: 'nx-task-31', title: 'Refonte du pont', run: 'session:a', since: '2026-10-01T09:18:00+02:00' },
    { agent: 'mnema', state: 'idle', task: null, title: null, run: null, since: null },
    { agent: 'artemis', state: 'idle', task: null, title: null, run: null, since: null },
  ],
  asks: [
    { event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: 'nx-task-32', at: '2026-10-01T09:59:00+02:00' },
    { event: 'nx-evt-2', agent: 'mnema', kind: 'question', subject: 'Et aussi ?', task: null, at: '2026-10-01T09:59:30+02:00' },
  ],
  blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: 'hors ligne', since: '2026-09-29T10:00:00+02:00', follow_up_at: null, lead_agent: 'artemis' }],
  done: [],
}

test('un poste reflète run, demandes et blocage de son agent', () => {
  const [helios, mnema, artemis] = seatModels(base)
  expect(helios).toMatchObject({ agent: 'helios', run: true, wait: false, block: false, task: 'nx-task-31', asks: 0 })
  expect(mnema).toMatchObject({ run: false, wait: true, block: false, asks: 2 })
  expect(artemis).toMatchObject({ run: false, wait: false, block: true })
})

test('état des baies : jamais vert sans preuve', () => {
  const node = (status: NodeState['status']): NodeState => ({ id: 'synapse', kind: 'homelab', guardian_agent: 'aether', status, last_seen: null, detail: null, source: 'tailscale', measured_at: '2026-10-01T10:00:00+02:00' })
  expect(rackTone(node('online'))).toBe('ok')
  expect(rackTone(node('unknown'))).toBe('unknown')
  expect(rackTone(node('offline'))).toBe('off')
  expect(rackTone(node('offline-by-design'))).toBe('off')
  expect(rackLabel(node('offline-by-design'))).toBe('hors ligne, prévu')
  expect(rackLabel(node('unknown'))).toBe('unknown')
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm --dir web exec vitest run src/now` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

`web/src/now/iso.ts`:

```ts
/*
 * Géométrie de l'étage (#6) : projection isométrique et placement des postes, en fonctions
 * pures. Unités de sol : un bureau fait 3 × 1,5. L'écran ne fait que lire ce plan.
 */
export type Pt = readonly [number, number]
export type Box = { top: string; left: string; right: string }
export type Seat = { x: number; y: number; back: boolean }
export type Layout = {
  width: number
  depth: number
  seats: Seat[]
  table: { x: number; y: number; w: number; d: number }
  racks: { x: number; y: number }[]
  viewBox: { x: number; y: number; w: number; h: number }
  project: (x: number, y: number, z?: number) => Pt
}

export const DESK = { w: 3, d: 1.5, h: 0.75 }
export const RACK = { w: 1.4, d: 1.4, h: 2.4 }
const UNIT = 26
const A = Math.cos(Math.PI / 6) * UNIT
const B = Math.sin(Math.PI / 6) * UNIT
const PITCH = 4 // un poste tous les 4 unités sur une rangée
const MARGIN = { side: 150, top: 110, bottom: 90 } // place pour les étiquettes, en px

const round = (v: number) => Math.round(v * 10) / 10

export function layoutFloor(agentCount: number, rackCount: number): Layout {
  const perRow = Math.max(4, Math.ceil(agentCount / 2))
  const rowWidth = perRow * PITCH
  const serverWidth = rackCount > 0 ? 3.2 : 0
  const width = rowWidth + 1 + serverWidth
  const depth = 14
  const seats: Seat[] = []
  for (let i = 0; i < agentCount; i++) {
    const back = i < perRow
    const col = back ? i : i - perRow
    seats.push({ x: 1.2 + col * PITCH, y: back ? 1.4 : 10.8, back })
  }
  // table centrée sur l'étendue réelle des postes
  const first = 1.2, last = 1.2 + (perRow - 1) * PITCH + DESK.w
  const table = { w: 5, d: 3.2, x: (first + last) / 2 - 2.5, y: 5.4 }
  const racks = Array.from({ length: rackCount }, (_, i) => ({ x: width - 2.1, y: 0.8 + i * 1.85 }))

  // origine choisie pour que le coin gauche du sol (0, depth) tombe à MARGIN.side
  const ox = MARGIN.side + depth * A
  const oy = MARGIN.top
  const project = (x: number, y: number, z = 0): Pt => [round(ox + (x - y) * A), round(oy + (x + y) * B - z * UNIT)]
  const right = project(width, 0)[0], bottom = project(width, depth)[1]
  const viewBox = { x: 0, y: 0, w: round(right + MARGIN.side), h: round(bottom + MARGIN.bottom) }
  return { width, depth, seats, table, racks, viewBox, project }
}

const pts = (list: Pt[]) => list.map((p) => `${p[0]},${p[1]}`).join(' ')

export function box(project: Layout['project'], x: number, y: number, z: number, w: number, d: number, h: number): Box {
  return {
    top: pts([project(x, y, z + h), project(x + w, y, z + h), project(x + w, y + d, z + h), project(x, y + d, z + h)]),
    left: pts([project(x, y + d, z + h), project(x + w, y + d, z + h), project(x + w, y + d, z), project(x, y + d, z)]),
    right: pts([project(x + w, y, z + h), project(x + w, y + d, z + h), project(x + w, y + d, z), project(x + w, y, z)]),
  }
}

export function toPercent(layout: Layout, p: Pt): readonly [number, number] {
  const { x, y, w, h } = layout.viewBox
  return [((p[0] - x) / w) * 100, ((p[1] - y) / h) * 100]
}
```

`web/src/now/model.ts`:

```ts
import type { AgentId, NodeState, NowSnapshot } from '@/api'

/** Les âges affichés sur Maintenant sont à la minute : une horloge à 30 s suffit, sans redessiner l'étage chaque seconde. */
export const AGE_TICK_MS = 30_000

export type SeatModel = { agent: AgentId; run: boolean; wait: boolean; block: boolean; task: string | null; title: string | null; since: string | null; asks: number }

/** Un poste par agent : run d'après ses événements, demandes reçues, blocage de ses tâches. */
export function seatModels(s: NowSnapshot): SeatModel[] {
  return s.agents.map((a) => {
    const asks = s.asks.filter((q) => q.agent === a.agent).length
    return {
      agent: a.agent, run: a.state === 'run', wait: asks > 0,
      block: s.blocks.some((b) => b.lead_agent === a.agent),
      task: a.task, title: a.title, since: a.since, asks,
    }
  })
}

export type RackTone = 'ok' | 'unknown' | 'off'

export function rackTone(n: NodeState): RackTone {
  if (n.status === 'online') return 'ok'
  if (n.status === 'unknown') return 'unknown'
  return 'off'
}

const LABEL: Record<NodeState['status'], string> = {
  online: 'en ligne', unknown: 'unknown', offline: 'hors ligne', 'offline-by-design': 'hors ligne, prévu',
}
export function rackLabel(n: NodeState): string {
  return LABEL[n.status]
}
```

- [ ] **Step 4: Run tests**

Run: `pnpm --dir web exec vitest run src/now`, `pnpm typecheck`, `pnpm --dir web exec oxlint src`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/now/iso.ts web/src/now/iso.test.ts web/src/now/model.ts web/src/now/model.test.ts
git commit -m "feat: géométrie de l'étage et modèle des postes (#6)"
```

---

### Task 5: La scène de l'étage et son mouvement

**Files:**
- Create: `web/src/now/useArrivals.ts`, `web/src/now/Floor.tsx`, `web/src/now/floor.css`
- Test: `web/src/now/useArrivals.test.tsx`, `web/src/now/Floor.test.tsx`

**Interfaces:**
- Consumes: `layoutFloor`, `box`, `toPercent`, `DESK`, `RACK` (Task 4); `seatModels`, `rackTone`, `rackLabel`, `SeatModel` (Task 4); `NowSnapshot`, `NodeState` (Task 2); `age()` from `web/src/format.ts`; `useNow()` from `web/src/useNow.ts`.
- Produces: `useArrivals(keys: readonly string[], holdMs?: number): ReadonlySet<string>`; `ARRIVAL_HOLD_MS = 1800`; `<Floor snapshot={NowSnapshot} nodes={NodeState[] | undefined} onOpenTask={(ref: string) => void} />`. DOM contract used by tests and e2e: each desk `<g data-agent="helios" data-run="true|false" data-wait="true|false" data-block="true|false">`; each ticket on the table `data-ticket="nx-evt-1"`; each rack `data-node="synapse" data-tone="ok|unknown|off"`; the svg has `role="img"` and an `aria-label`.

- [ ] **Step 1: Write the failing tests**

`web/src/now/useArrivals.test.tsx`:

```tsx
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { useArrivals } from './useArrivals'

function Probe({ keys }: { keys: string[] }) {
  const fresh = useArrivals(keys, 1000)
  return <p>{[...fresh].sort().join(',') || 'aucune'}</p>
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

test('rien n\'est nouveau au premier rendu', () => {
  render(<Probe keys={['a', 'b']} />)
  expect(screen.getByText('aucune')).toBeInTheDocument()
})

test('une clé qui apparaît est nouvelle, puis ne l\'est plus après le délai', () => {
  const { rerender } = render(<Probe keys={['a']} />)
  rerender(<Probe keys={['a', 'b']} />)
  expect(screen.getByText('b')).toBeInTheDocument()
  act(() => vi.advanceTimersByTime(999))
  expect(screen.getByText('b')).toBeInTheDocument()
  act(() => vi.advanceTimersByTime(1))
  expect(screen.getByText('aucune')).toBeInTheDocument()
})

test('un nouveau rendu sans changement ne relance rien', () => {
  const { rerender } = render(<Probe keys={['a']} />)
  rerender(<Probe keys={['a']} />)
  expect(screen.getByText('aucune')).toBeInTheDocument()
})

test('une deuxième arrivée ne coupe pas la première avant son délai', () => {
  const { rerender } = render(<Probe keys={[]} />)
  rerender(<Probe keys={['a']} />)
  act(() => vi.advanceTimersByTime(600))
  rerender(<Probe keys={['a', 'b']} />)
  expect(screen.getByText('a,b')).toBeInTheDocument()
  act(() => vi.advanceTimersByTime(400))
  expect(screen.getByText('b')).toBeInTheDocument()
})
```

`web/src/now/Floor.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import type { NodeState, NowSnapshot } from '@/api'
import { Floor } from './Floor'

const snap = (over: Partial<NowSnapshot> = {}): NowSnapshot => ({
  source: 'nexus.db', measured_at: new Date().toISOString(), operation: null, auxiliaries: [],
  agents: [
    { agent: 'helios', state: 'run', task: 'nx-task-31', title: 'Refonte du pont', run: 's', since: new Date(Date.now() - 42 * 60_000).toISOString() },
    { agent: 'mnema', state: 'idle', task: null, title: null, run: null, since: null },
    { agent: 'artemis', state: 'idle', task: null, title: null, run: null, since: null },
  ],
  asks: [], blocks: [], done: [], ...over,
})
const node = (id: string, status: NodeState['status']): NodeState => ({ id, kind: 'homelab', guardian_agent: 'aether', status, last_seen: null, detail: null, source: 'tailscale', measured_at: new Date().toISOString() })

test('chaque poste porte l\'état de son agent', () => {
  const { container } = render(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: 'nx-task-32', at: new Date().toISOString() }],
    blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: 'hors ligne', since: null, follow_up_at: null, lead_agent: 'artemis' }],
  })} nodes={[]} onOpenTask={() => {}} />)
  const desk = (a: string) => container.querySelector(`[data-agent="${a}"]`)!
  expect(desk('helios').getAttribute('data-run')).toBe('true')
  expect(desk('mnema').getAttribute('data-wait')).toBe('true')
  expect(desk('artemis').getAttribute('data-block')).toBe('true')
  expect(container.querySelector('[data-ticket="nx-evt-1"]')).not.toBeNull()
})

test('les étiquettes disent le nom, la tâche et la durée, sans survol', () => {
  render(<Floor snapshot={snap()} nodes={[]} onOpenTask={() => {}} />)
  expect(screen.getByText('HELIOS')).toBeInTheDocument()
  expect(screen.getByText('Refonte du pont')).toBeInTheDocument()
  expect(screen.getByText(/nx-task-31 · 42 min/)).toBeInTheDocument()
  expect(screen.getAllByText('inactif').length).toBeGreaterThan(0)
})

test('ta table dit quand aucune demande n\'est reçue', () => {
  render(<Floor snapshot={snap()} nodes={[]} onOpenTask={() => {}} />)
  expect(screen.getByText('aucune demande reçue (7 j)')).toBeInTheDocument()
})

test('les baies suivent les nœuds, jamais vertes sans preuve', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[node('helios', 'online'), node('synapse', 'unknown'), node('artemis', 'offline-by-design')]} onOpenTask={() => {}} />)
  expect(container.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('ok')
  expect(container.querySelector('[data-node="synapse"]')!.getAttribute('data-tone')).toBe('unknown')
  expect(screen.getByText('hors ligne, prévu')).toBeInTheDocument()
})

test('aucun mouvement au premier rendu', () => {
  const { container } = render(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString() }],
  })} nodes={[]} onOpenTask={() => {}} />)
  expect(container.querySelector('.is-fresh')).toBeNull()
})

test('une demande qui arrive déclenche le mouvement de son fil', () => {
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={[]} onOpenTask={() => {}} />)
  rerender(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-7', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString() }],
  })} nodes={[]} onOpenTask={() => {}} />)
  expect(container.querySelector('[data-route="mnema"].is-fresh')).not.toBeNull()
})

test('cliquer un poste qui a une tâche ouvre la tâche', () => {
  const open = vi.fn()
  render(<Floor snapshot={snap()} nodes={[]} onOpenTask={open} />)
  screen.getByRole('button', { name: /Helios.*Refonte du pont/ }).click()
  expect(open).toHaveBeenCalledWith('nx-task-31')
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm --dir web exec vitest run src/now` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

`web/src/now/useArrivals.ts`:

```ts
import { useEffect, useRef, useState } from 'react'

export const ARRIVAL_HOLD_MS = 1800

/**
 * Clés apparues depuis le rendu précédent, gardées `holdMs` le temps de leur animation.
 * Rien n'est « nouveau » au premier rendu : on n'anime que de vrais changements (#6).
 */
export function useArrivals(keys: readonly string[], holdMs = ARRIVAL_HOLD_MS): ReadonlySet<string> {
  const seen = useRef<Set<string> | null>(null)
  const timers = useRef<number[]>([])
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set())
  const signature = keys.join('\u0000')

  useEffect(() => {
    const current = new Set(signature ? signature.split('\u0000') : [])
    const before = seen.current
    seen.current = current
    if (!before) return
    const added = [...current].filter((k) => !before.has(k))
    if (added.length === 0) return
    setFresh((f) => new Set([...f, ...added]))
    timers.current.push(window.setTimeout(() => {
      setFresh((f) => { const next = new Set(f); for (const k of added) next.delete(k); return next })
    }, holdMs))
  }, [signature, holdMs])

  useEffect(() => () => { for (const t of timers.current) window.clearTimeout(t) }, [])
  return fresh
}
```

`web/src/now/floor.css` (imported by `Floor.tsx`):

```css
/* L'étage (#6). Seuls les vrais changements d'état bougent ; rien en boucle. */
.floor-top { fill: #0f1114; stroke: rgba(244, 244, 245, 0.28); stroke-width: 1 }
.floor-left { fill: #0b0c0e; stroke: rgba(244, 244, 245, 0.18) }
.floor-right { fill: #08090a; stroke: rgba(244, 244, 245, 0.14) }
.floor-grid { fill: none; stroke: rgba(244, 244, 245, 0.045) }
.f-top { fill: #1b1e24; stroke: rgba(244, 244, 245, 0.22); stroke-width: 0.8 }
.f-left { fill: #121419; stroke: rgba(244, 244, 245, 0.12); stroke-width: 0.8 }
.f-right { fill: #0d0f12; stroke: rgba(244, 244, 245, 0.1); stroke-width: 0.8 }
.desk .screen { fill: #15181d; stroke: rgba(244, 244, 245, 0.2); stroke-width: 0.6; transition: fill 450ms ease }
.desk .pool { fill: url(#now-run); opacity: 0; transition: opacity 700ms ease }
.desk .pool-att { fill: url(#now-att); opacity: 0; transition: opacity 700ms ease }
.desk[data-run='true'] .screen { fill: var(--run) }
.desk[data-run='true'] .pool { opacity: 1 }
.desk[data-wait='true'] .pool-att { opacity: 1 }
.desk .beacon { opacity: 0; transform-box: fill-box; transform-origin: 50% 100%; transform: scaleY(0); transition: transform 500ms cubic-bezier(0.2, 0.7, 0.2, 1), opacity 200ms }
.desk .beacon line { stroke: var(--attention); stroke-width: 1.4 }
.desk .beacon polygon { fill: var(--attention) }
.desk[data-wait='true'] .beacon { opacity: 1; transform: scaleY(1) }
.desk .desk-top { transition: fill 300ms }
.desk[data-block='true'] .desk-top { fill: url(#now-hatch); stroke: var(--danger); stroke-width: 1.2 }
.route .r-base { fill: none; stroke: var(--attention); stroke-width: 1.2; stroke-dasharray: 3 5; opacity: 0.85 }
.route .r-spark { fill: none; stroke: #ffd9b8; stroke-width: 2.4; stroke-linecap: round; stroke-dasharray: 0 100; opacity: 0 }
.route.is-fresh .r-spark { animation: now-travel 1100ms cubic-bezier(0.3, 0.6, 0.3, 1) 1 both }
@keyframes now-travel { 0% { stroke-dasharray: 8 100; stroke-dashoffset: 8; opacity: 1 } 90% { opacity: 1 } 100% { stroke-dasharray: 8 100; stroke-dashoffset: -92; opacity: 0 } }
.table-top { fill: #1d2026 }
.dais[data-on='true'] .table-top { stroke: var(--attention); stroke-width: 1.2 }
.ticket { fill: var(--attention); opacity: 0.9 }
.ticket.is-fresh { animation: now-land 300ms 900ms ease-out both }
@keyframes now-land { from { opacity: 0 } to { opacity: 0.9 } }
.rack .led { fill: #23262d; transition: fill 400ms, stroke 400ms }
.rack[data-tone='ok'] .led { fill: var(--ok) }
.rack[data-tone='unknown'] .led { fill: none; stroke: var(--unknown); stroke-width: 0.8; stroke-dasharray: 2 2 }
.rack[data-tone='off'] .led { fill: none; stroke: var(--unknown); stroke-width: 0.8 }
.leader { fill: none; stroke: rgba(244, 244, 245, 0.28) }
@media (prefers-reduced-motion: reduce) {
  .desk *, .route *, .ticket, .rack .led { transition: none !important; animation: none !important }
}
```

`web/src/now/Floor.tsx`:

```tsx
import clsx from 'clsx'
import type { NodeState, NowSnapshot } from '@/api'
import { age } from '@/format'
import { useNow } from '@/useNow'
import { DESK, RACK, box, layoutFloor, toPercent, type Box, type Layout } from './iso'
import { AGE_TICK_MS, rackLabel, rackTone, seatModels, type SeatModel } from './model'
import { useArrivals } from './useArrivals'
import './floor.css'

const NAME: Record<string, string> = { helios: 'Helios', mnema: 'Mnema', aether: 'Aether', artemis: 'Artemis', claude: 'Claude', codex: 'Codex', orca: 'Orca', hermes: 'Hermes' }
const MAX_TICKETS = 3

function Faces({ b, topClass }: { b: Box; topClass?: string }) {
  return (<><polygon className={clsx('f-top', topClass)} points={b.top} /><polygon className="f-left" points={b.left} /><polygon className="f-right" points={b.right} /></>)
}

function routePath(l: Layout, s: { x: number; y: number; back: boolean }): string {
  const sx = s.x + DESK.w / 2, sy = s.back ? s.y + DESK.d : s.y
  const ty = s.back ? l.table.y : l.table.y + l.table.d
  const tx = Math.min(Math.max(sx, l.table.x + 0.6), l.table.x + l.table.w - 0.6)
  const my = (sy + ty) / 2
  return 'M' + [l.project(sx, sy), l.project(sx, my), l.project(tx, my), l.project(tx, ty)].map((p) => p.join(' ')).join(' L ')
}

function Desk({ l, seat, m }: { l: Layout; seat: Layout['seats'][number]; m: SeatModel }) {
  const { x, y } = seat, p = l.project
  const pool = p(x + DESK.w / 2, y + 2.3)
  const [bx, by0] = p(x + 2.62, y + 0.27, 1.66), [, by1] = p(x + 2.62, y + 0.27, 2.75)
  const screenPts = [p(x + 0.45, y + 0.28, 1.63), p(x + 2.55, y + 0.28, 1.63), p(x + 2.55, y + 0.28, 0.86), p(x + 0.45, y + 0.28, 0.86)].map((q) => q.join(',')).join(' ')
  return (
    <g className="desk" data-agent={m.agent} data-run={String(m.run)} data-wait={String(m.wait)} data-block={String(m.block)}>
      <ellipse className="pool" cx={pool[0]} cy={pool[1]} rx={2.4 * 22.5} ry={2.4 * 13} />
      <ellipse className="pool-att" cx={pool[0]} cy={pool[1]} rx={1.9 * 22.5} ry={1.9 * 13} />
      <Faces b={box(p, x, y, 0, DESK.w, DESK.d, DESK.h)} topClass="desk-top" />
      <Faces b={box(p, x + 0.35, y + 0.15, DESK.h, 2.3, 0.12, 0.95)} />
      <polygon className="screen" points={screenPts} />
      <g className="beacon"><line x1={bx} y1={by0} x2={bx} y2={by1} /><polygon points={`${bx},${by1 - 7} ${bx + 6},${by1} ${bx},${by1 + 7} ${bx - 6},${by1}`} /></g>
    </g>
  )
}

export function Floor({ snapshot, nodes, onOpenTask }: { snapshot: NowSnapshot; nodes: NodeState[] | undefined; onOpenTask: (ref: string) => void }) {
  const now = useNow(AGE_TICK_MS)
  const seats = seatModels(snapshot)
  const racks = nodes ?? []
  const l = layoutFloor(seats.length, racks.length)
  const freshAsks = useArrivals(snapshot.asks.map((q) => q.event))
  const freshRoutes = new Set(snapshot.asks.filter((q) => freshAsks.has(q.event)).map((q) => q.agent))
  const p = l.project
  const floor = box(p, 0, 0, -0.35, l.width, l.depth, 0.35)
  let grid = ''
  for (let i = 1; i < l.width; i++) grid += `M${p(i, 0)} L${p(i, l.depth)} `
  for (let j = 1; j < l.depth; j++) grid += `M${p(0, j)} L${p(l.width, j)} `
  const tickets = snapshot.asks.slice(0, MAX_TICKETS)
  const extra = snapshot.asks.length - tickets.length
  const tableLabel = toPercent(l, p(l.table.x + l.table.w + 0.3, l.table.y + 1, 0.4))
  const label = (ask: number) => ask === 0 ? 'aucune demande reçue (7 j)' : `${ask} demande${ask > 1 ? 's' : ''}`

  return (
    <div className="relative mx-auto w-full" style={{ aspectRatio: `${l.viewBox.w} / ${l.viewBox.h}`, maxHeight: '100%' }}>
      <svg viewBox={`${l.viewBox.x} ${l.viewBox.y} ${l.viewBox.w} ${l.viewBox.h}`} className="absolute inset-0 size-full" role="img"
        aria-label="Étage de Nexus : un poste par agent, ta table au centre, la salle des serveurs">
        <defs>
          <radialGradient id="now-run"><stop offset="0" stopColor="#5eead4" stopOpacity=".30" /><stop offset="1" stopColor="#5eead4" stopOpacity="0" /></radialGradient>
          <radialGradient id="now-att"><stop offset="0" stopColor="#fb923c" stopOpacity=".26" /><stop offset="1" stopColor="#fb923c" stopOpacity="0" /></radialGradient>
          <pattern id="now-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#f87171" strokeOpacity=".55" strokeWidth="1.4" /></pattern>
        </defs>
        <polygon className="floor-top" points={floor.top} /><polygon className="floor-left" points={floor.left} /><polygon className="floor-right" points={floor.right} />
        <path className="floor-grid" d={grid.trim()} />
        {seats.map((m, i) => m.wait && (
          <g key={m.agent} className={clsx('route', freshRoutes.has(m.agent) && 'is-fresh')} data-route={m.agent}>
            <path className="r-base" d={routePath(l, l.seats[i])} />
            <path className="r-spark" d={routePath(l, l.seats[i])} pathLength={100} />
          </g>
        ))}
        <g className="dais" data-on={String(snapshot.asks.length > 0)}>
          <Faces b={box(p, l.table.x, l.table.y, 0, l.table.w, l.table.d, 0.18)} />
          <Faces b={box(p, l.table.x + 0.9, l.table.y + 0.7, 0.18, l.table.w - 1.8, l.table.d - 1.4, 0.5)} topClass="table-top" />
          {tickets.map((q, i) => {
            const tx = l.table.x + 1.3 + i * 0.95
            const pts = [p(tx, l.table.y + 1.15, 0.69), p(tx + 0.7, l.table.y + 1.15, 0.69), p(tx + 0.7, l.table.y + 1.95, 0.69), p(tx, l.table.y + 1.95, 0.69)].map((q2) => q2.join(',')).join(' ')
            return <polygon key={q.event} data-ticket={q.event} className={clsx('ticket', freshAsks.has(q.event) && 'is-fresh')} points={pts} />
          })}
        </g>
        {racks.map((n, i) => {
          const r = l.racks[i], tone = rackTone(n)
          return (
            <g key={n.id} className="rack" data-node={n.id} data-tone={tone}>
              <Faces b={box(p, r.x, r.y, 0, RACK.w, RACK.d, RACK.h)} />
              {[0, 1, 2, 3, 4].map((j) => {
                const z = 2.1 - j * 0.38, xr = r.x + RACK.w
                const pts = [p(xr, r.y + 0.25, z), p(xr, r.y + 1.15, z), p(xr, r.y + 1.15, z - 0.16), p(xr, r.y + 0.25, z - 0.16)].map((q) => q.join(',')).join(' ')
                return <polygon key={j} className="led" points={pts} />
              })}
            </g>
          )
        })}
        {seats.map((m, i) => <Desk key={m.agent} l={l} seat={l.seats[i]} m={m} />)}
        {seats.map((m, i) => {
          const s = l.seats[i], from = s.back ? p(s.x + 1.5, s.y + 0.2, 1.8) : p(s.x + 1.5, s.y + DESK.d, 0)
          return <path key={m.agent} className="leader" d={`M${from} L${from[0]} ${from[1] + (s.back ? -30 : 26)}`} />
        })}
        {racks.map((n, i) => {
          const r = l.racks[i], led = p(r.x + RACK.w, r.y + 0.7, 1.3), lx = p(l.width, 0)[0] + 26, ly = l.project(l.width, 0)[1] + 200 + i * 40
          return <path key={n.id} className="leader" d={`M${led} L${lx - 22} ${ly} L${lx - 4} ${ly}`} />
        })}
      </svg>

      {seats.map((m, i) => {
        const s = l.seats[i], from = s.back ? p(s.x + 1.5, s.y + 0.2, 1.8) : p(s.x + 1.5, s.y + DESK.d, 0)
        const [left, top] = toPercent(l, [from[0], from[1] + (s.back ? -30 : 26)])
        const meta = m.task ? `${m.task} · ${m.since ? age(m.since, now).replace(/^il y a /, '') : 'durée unknown'}` : m.block ? 'tâche bloquée' : 'inactif'
        const name = <><span className="block font-orbital-display text-[13px] font-semibold tracking-[0.14em]">{NAME[m.agent].toUpperCase()}</span>
          {m.title && <span className="block font-data text-[11px] text-ink">{m.title}</span>}
          <span className="block font-data text-[11px] text-muted">{meta}</span></>
        const cls = clsx('absolute whitespace-nowrap text-center', s.back ? '-translate-x-1/2 -translate-y-full pb-1' : '-translate-x-1/2 pt-1',
          m.wait ? '[&>span:first-child]:text-attention' : m.block ? '[&>span:first-child]:text-danger' : m.run ? '' : '[&>span:first-child]:text-unknown')
        const style = { left: `${left}%`, top: `${top}%` }
        return m.task
          ? <button key={m.agent} type="button" className={clsx(cls, 'cursor-pointer bg-transparent')} style={style} onClick={() => onOpenTask(m.task!)} aria-label={`${NAME[m.agent]}, ${m.title ?? m.task} : ouvrir la tâche`}>{name}</button>
          : <div key={m.agent} className={cls} style={style}>{name}</div>
      })}

      <div className="absolute -translate-y-1/2 whitespace-nowrap pl-2" style={{ left: `${tableLabel[0]}%`, top: `${tableLabel[1]}%` }}>
        <span className={clsx('block font-orbital-display text-[13px] font-semibold tracking-[0.14em]', snapshot.asks.length ? 'text-attention' : 'text-muted')}>TA TABLE</span>
        <span className="block font-data text-[11px] text-muted">{label(snapshot.asks.length)}{extra > 0 && ` · +${extra} sur la table`}</span>
      </div>

      {racks.map((n, i) => {
        const [left, top] = toPercent(l, [p(l.width, 0)[0] + 26, l.project(l.width, 0)[1] + 200 + i * 40])
        return (
          <div key={n.id} className="absolute -translate-y-1/2 whitespace-nowrap" style={{ left: `${left}%`, top: `${top}%` }}>
            <span className={clsx('block font-orbital-display text-[13px] font-semibold tracking-[0.14em]', rackTone(n) === 'ok' ? 'text-ink' : 'text-muted')}>{n.id.toUpperCase()}</span>
            <span className="block font-data text-[11px] text-muted">{rackLabel(n)}</span>
          </div>
        )
      })}
    </div>
  )
}
```

Notes for the implementer: keep the DOM contract (data attributes, button label shape). `age()` in `web/src/format.ts` returns a French relative string (read it: if it does not start with « il y a », adapt the `.replace` to produce « 42 min »). The rack legend y-positions are a first placement: check them visually in Task 7 and adjust the constants, not the contract.

- [ ] **Step 4: Run tests**

Run: `pnpm --dir web exec vitest run src/now`, `pnpm typecheck`, `pnpm --dir web exec oxlint src`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/now/useArrivals.ts web/src/now/useArrivals.test.tsx web/src/now/Floor.tsx web/src/now/floor.css web/src/now/Floor.test.tsx
git commit -m "feat: l'étage isométrique de Maintenant et son mouvement (#6)"
```

---

### Task 6: La vue Maintenant — panneau Système, listes, états, navigation

**Files:**
- Create: `web/src/now/AgentList.tsx`, `web/src/now/NowView.tsx`
- Modify: `web/src/App.tsx` (vue Maintenant ; `#/travail/<ref>` ouvre une tâche), `web/src/tasks/WorkView.tsx` (prop `openTask?: string | null`)
- Test: `web/src/now/NowView.test.tsx`

**Interfaces:**
- Consumes: `useNowSnapshot`, `useNodes` (Task 2); `Floor` (Task 5); `seatModels` (Task 4); `Provenance` (`web/src/Provenance.tsx`, `kind="now"`); `age` (`web/src/format.ts`).
- Produces: `<NowView />`; `<AgentList snapshot={NowSnapshot} onOpenTask={(ref) => void} className? />`; App route: hash `#/travail/nx-task-31` shows Travail with that task's pane open; opening from Maintenant sets `window.location.hash = '#/travail/' + ref`.

- [ ] **Step 1: Write the failing tests** (`web/src/now/NowView.test.tsx`)

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { NowSnapshot } from '@/api'
import { NowView } from './NowView'

const empty: NowSnapshot = {
  source: 'nexus.db', measured_at: new Date().toISOString(), operation: null, auxiliaries: [],
  agents: [{ agent: 'helios', state: 'idle', task: null, title: null, run: null, since: null }],
  asks: [], blocks: [], done: [],
}

function serve(now: NowSnapshot | 'fail') {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/api/nodes') return Response.json([])
    if (now === 'fail') return new Response('', { status: 500 })
    return Response.json(now)
  }))
}

function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><NowView /></QueryClientProvider>)
}

afterEach(() => vi.unstubAllGlobals())

test('sans données, chaque section dit ce qu\'elle ne contient pas', async () => {
  serve(empty); show()
  expect(await screen.findByText('Pas d\'opération principale en cours.')).toBeInTheDocument()
  expect(screen.getByText('Aucune demande reçue ces 7 derniers jours.')).toBeInTheDocument()
  expect(screen.getByText('Aucun blocage actif.')).toBeInTheDocument()
  expect(screen.getByText('Rien de terminé ces 7 derniers jours.')).toBeInTheDocument()
  expect(screen.getByText('Aucun agent ne travaille en ce moment.')).toBeInTheDocument()
  expect(screen.queryByText(/tout va bien/i)).toBeNull()
})

test('les tuiles ne sont que des comptes mesurés', async () => {
  serve({ ...empty,
    agents: [{ agent: 'helios', state: 'run', task: 'nx-task-1', title: 'T', run: 's', since: new Date().toISOString() }],
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString() }],
  }); show()
  expect(await screen.findByRole('group', { name: 'Agents actifs' })).toHaveTextContent('1')
  expect(screen.getByRole('group', { name: 'Demandes reçues' })).toHaveTextContent('1')
  expect(screen.getByRole('group', { name: 'Blocages' })).toHaveTextContent('0')
})

test('une demande reçue ne se dit jamais « en attente »', async () => {
  serve({ ...empty, asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: 'nx-task-32', at: new Date().toISOString() }] }); show()
  expect(await screen.findByText('Python ?')).toBeInTheDocument()
  expect(screen.getByText('Question de Mnema sur nx-task-32.')).toBeInTheDocument()
  expect(screen.queryByText(/en attente/i)).toBeNull()
})

test('serveur injoignable : on le dit, sans étage vide présenté comme calme', async () => {
  serve('fail'); show()
  expect(await screen.findByText(/Maintenant n'a pas pu être lu/)).toBeInTheDocument()
  expect(screen.queryByText('Aucun agent ne travaille en ce moment.')).toBeNull()
})

test('la liste des agents existe toujours pour les lecteurs d\'écran', async () => {
  serve(empty); show()
  expect(await screen.findByRole('list', { name: 'Agents' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm --dir web exec vitest run src/now/NowView.test.tsx` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

`web/src/now/AgentList.tsx`:

```tsx
import clsx from 'clsx'
import type { NowSnapshot } from '@/api'
import { age } from '@/format'
import { useNow } from '@/useNow'
import { AGE_TICK_MS, seatModels } from './model'

const NAME: Record<string, string> = { helios: 'Helios', mnema: 'Mnema', aether: 'Aether', artemis: 'Artemis', claude: 'Claude', codex: 'Codex', orca: 'Orca', hermes: 'Hermes' }

/** Même information que l'étage, en lignes : fenêtre étroite et lecteurs d'écran. */
export function AgentList({ snapshot, onOpenTask, className }: { snapshot: NowSnapshot; onOpenTask: (ref: string) => void; className?: string }) {
  const now = useNow(AGE_TICK_MS)
  const seats = seatModels(snapshot)
  const working = seats.filter((s) => s.run).length
  return (
    <div className={className}>
      {working === 0 && <p className="text-muted">Aucun agent ne travaille en ce moment.</p>}
      <ul aria-label="Agents" className="flex flex-col">
        {seats.map((s) => (
          <li key={s.agent} className="flex items-baseline gap-3 border-b border-line py-1.5">
            <span className={clsx('w-20 font-orbital-display font-semibold tracking-[0.12em]', s.wait ? 'text-attention' : s.block ? 'text-danger' : s.run ? 'text-run' : 'text-unknown')}>{NAME[s.agent].toUpperCase()}</span>
            {s.task
              ? <a href={`#/travail/${s.task}`} onClick={(e) => { e.preventDefault(); onOpenTask(s.task!) }} className="min-w-0 flex-1 truncate">{s.title ?? s.task}</a>
              : <span className="flex-1 text-muted">inactif</span>}
            <span className="font-data text-[11px] text-muted">
              {s.run && s.since ? age(s.since, now) : ''}{s.wait ? ` · ${s.asks} demande${s.asks > 1 ? 's' : ''}` : ''}{s.block ? ' · tâche bloquée' : ''}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
```

`web/src/now/NowView.tsx`:

```tsx
import clsx from 'clsx'
import type { ReactNode } from 'react'
import { age } from '@/format'
import { Provenance } from '@/Provenance'
import { useNow } from '@/useNow'
import { AgentList } from './AgentList'
import { Floor } from './Floor'
import { AGE_TICK_MS } from './model'
import { useArrivals } from './useArrivals'
import { useNodes, useNowSnapshot } from './queries'

const NAME: Record<string, string> = { helios: 'Helios', mnema: 'Mnema', aether: 'Aether', artemis: 'Artemis', claude: 'Claude', codex: 'Codex', orca: 'Orca', hermes: 'Hermes', loic: 'Loïc' }
const openTask = (ref: string) => { window.location.hash = `#/travail/${ref}` }

// Classes écrites en entier : Tailwind ne génère pas une classe construite (`text-${tone}`).
const TONE = { muted: 'text-muted', attention: 'text-attention', danger: 'text-danger', run: 'text-run' } as const

function Heading({ children, tone = 'muted' }: { children: ReactNode; tone?: keyof typeof TONE }) {
  return <h2 className={clsx('m-0 mb-1.5 font-orbital-display text-xs font-semibold uppercase tracking-[0.22em]', TONE[tone])}>{children}</h2>
}

function Tile({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div role="group" aria-label={label} className="border border-line bg-sunken px-3 py-2">
      <div className="font-orbital-display text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">{label}</div>
      <div className={clsx('font-data text-2xl', tone)}>{value}</div>
    </div>
  )
}

export function NowView() {
  const now = useNow(AGE_TICK_MS)
  const snap = useNowSnapshot()
  const nodes = useNodes()
  const s = snap.data
  const freshAsks = useArrivals(s?.asks.map((q) => q.event) ?? [])

  if (!s) {
    return (
      <div className="orbital flex h-full items-center justify-center bg-paper font-orbital text-muted">
        {snap.isError ? 'Maintenant n\'a pas pu être lu : le serveur Nexus ne répond pas.' : 'Lecture de Maintenant…'}
      </div>
    )
  }
  const active = s.agents.filter((a) => a.state === 'run').length
  const online = nodes.data?.filter((n) => n.status === 'online').length

  return (
    <div className="orbital grid h-full min-h-0 grid-cols-[minmax(0,1fr)_336px] bg-paper font-orbital text-[13px] max-[1100px]:grid-cols-1 max-[1100px]:overflow-auto"
      style={{ backgroundImage: 'radial-gradient(rgba(244,244,245,.06) 1px, transparent 1px)', backgroundSize: '14px 14px' }}>
      <section className="flex min-h-0 min-w-0 flex-col gap-2 px-7 pt-5 pb-4">
        <header className="flex items-baseline gap-4">
          <h1 className="m-0 font-orbital-display text-2xl font-semibold uppercase tracking-[0.12em]">Maintenant</h1>
          <Provenance source={s.source} measuredAt={s.measured_at} kind="now" className="font-data" />
          {snap.isError && <span className="font-data text-[11px] text-attention">dernière lecture réussie affichée</span>}
        </header>
        <div className="flex min-h-0 flex-1 items-center justify-center max-[760px]:hidden">
          <Floor snapshot={s} nodes={nodes.data} onOpenTask={openTask} />
        </div>
        <AgentList snapshot={s} onOpenTask={openTask} className="min-[761px]:sr-only" />
        <div className="grid grid-cols-2 gap-7 max-[760px]:grid-cols-1">
          <section>
            <Heading tone={s.blocks.length ? 'danger' : 'muted'}>Blocages {s.blocks.length || ''}</Heading>
            {s.blocks.length === 0 ? <p className="text-muted">Aucun blocage actif.</p> : s.blocks.map((b) => (
              <a key={b.task} href={`#/travail/${b.task}`} className="mb-1.5 flex flex-col gap-0.5 border-l-2 border-danger bg-[rgba(248,113,113,.05)] px-3 py-2 no-underline">
                <span className="flex justify-between gap-3"><strong className="font-semibold">{b.title}</strong><span className="font-data text-[11px] text-muted">{b.since ? age(b.since, now) : 'depuis unknown'}</span></span>
                <span className="text-xs text-muted">{b.cause ?? 'Cause non renseignée.'}{b.follow_up_at ? ` Relance prévue le ${new Date(b.follow_up_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}.` : ''}</span>
              </a>
            ))}
          </section>
          <section>
            <Heading>Derniers done</Heading>
            {s.done.length === 0 ? <p className="text-muted">Rien de terminé ces 7 derniers jours.</p> : s.done.map((d) => (
              <a key={d.task} href={`#/travail/${d.task}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-b border-line py-1.5 no-underline">
                <strong className="font-semibold">{d.title}</strong><span className="font-data text-[11px] text-muted">{age(d.at, now)}</span>
                <span className="col-span-2 text-xs text-muted">Terminée{d.agent ? ` par ${NAME[d.agent] ?? d.agent}` : ''}. {d.evidence.length ? `Preuve : ${d.evidence.join(', ')}.` : 'Aucune preuve jointe.'}</span>
              </a>
            ))}
          </section>
        </div>
      </section>
      <aside aria-label="Système" className="flex min-h-0 flex-col gap-4 overflow-auto border-l border-line bg-surface px-4.5 py-5 max-[1100px]:border-l-0 max-[1100px]:border-t">
        <Heading>Système</Heading>
        <div className="grid grid-cols-2 gap-2">
          <Tile label="Agents actifs" value={active} tone="text-run" />
          <Tile label="Demandes reçues" value={s.asks.length} tone={s.asks.length ? 'text-attention' : undefined} />
          <Tile label="Blocages" value={s.blocks.length} tone={s.blocks.length ? 'text-danger' : undefined} />
          <Tile label="Nœuds en ligne" value={online === undefined ? 'unknown' : `${online} / ${nodes.data!.length}`} />
        </div>
        <section>
          <Heading tone="attention">Demandes reçues</Heading>
          {s.asks.length === 0 ? <p className="text-muted">Aucune demande reçue ces 7 derniers jours.</p> : s.asks.map((q) => (
            <div key={q.event} className={clsx('mb-1.5 border-l-2 border-attention px-3 py-2', freshAsks.has(q.event) ? 'now-fresh' : 'bg-[rgba(251,146,60,.05)]')}>
              <div className="flex justify-between gap-3"><strong className="font-semibold">{q.subject}</strong><span className="font-data text-[11px] text-muted">{age(q.received_at, now)}</span></div>
              <div className="text-xs text-muted">{q.kind === 'question' ? 'Question' : 'Demande de validation'} de {NAME[q.agent] ?? q.agent} {q.task ? `sur ${q.task}` : 'sur aucune tâche'}.</div>
            </div>
          ))}
        </section>
        <section className="border-t border-line pt-3.5">
          <Heading tone="run">Opération principale</Heading>
          {s.operation === null ? <p className="text-muted">Pas d'opération principale en cours.</p> : (
            <a href={`#/travail/${s.operation.task}`} className="flex flex-col gap-1 no-underline">
              <strong className="text-base font-semibold">{s.operation.title}</strong>
              <span className="font-data text-[11px] leading-relaxed text-muted">
                {s.operation.lead_agent ? `menée par ${NAME[s.operation.lead_agent] ?? s.operation.lead_agent}` : 'sans agent principal'}{s.operation.since ? `, ${age(s.operation.since, now)}` : ''}<br />
                prochaine action : {s.operation.next_action ?? 'non renseignée'}<br />
                {s.operation.due_at ? `échéance : ${new Date(s.operation.due_at).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })}` : 'sans échéance'}
              </span>
            </a>
          )}
          {s.auxiliaries.length > 0 && <p className="mt-2 text-xs text-muted">Auxiliaires : {s.auxiliaries.map((a) => a.title).join(', ')}</p>}
        </section>
      </aside>
    </div>
  )
}
```

Add to `web/src/now/floor.css`: `.now-fresh { animation: now-fresh 1800ms ease-out both } @keyframes now-fresh { from { background: rgba(251, 146, 60, 0.16) } to { background: rgba(251, 146, 60, 0.05) } }` and include `.now-fresh` in the reduced-motion rule.

`web/src/App.tsx`: `currentView()` returns `'travail'` for any hash starting with `#/travail`; parse `const open = /^#\/travail\/(nx-task-\d+)$/.exec(window.location.hash)?.[1] ?? null` into state alongside the view (update it in the `hashchange` handler); render `<NowView />` instead of the placeholder for `maintenant`, and `<WorkView openTask={open} />`. Keep the `<main>` wrapper.

`web/src/tasks/WorkView.tsx`: accept `{ openTask }: { openTask?: string | null } = {}` and add `useEffect(() => { if (openTask) setOpenId(openTask) }, [openTask])`.

- [ ] **Step 4: Run tests + e2e sanity**

Run: `pnpm --dir web exec vitest run`, `pnpm typecheck`, `pnpm --dir web exec oxlint src`, `pnpm e2e` (existing journeys must stay green: they open Travail by default).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/now/AgentList.tsx web/src/now/NowView.tsx web/src/now/NowView.test.tsx web/src/now/floor.css web/src/App.tsx web/src/tasks/WorkView.tsx
git commit -m "feat: vue Maintenant — panneau Système, listes et états honnêtes (#6)"
```

---

### Task 7: Parcours de bout en bout, contrôle visuel, docs

**Files:**
- Create: `web/e2e/now.spec.ts`
- Modify: `docs/agents/review-checklist.md` (UI : une scène animée ne s'anime que sur changement ; placement des étiquettes vérifié à l'œil)

**Interfaces:**
- Consumes: the DOM contract of Task 5 (`[data-agent=…][data-run]`, `[data-ticket]`), the API on `http://127.0.0.1:8799` (Playwright config), `list` « Agents ».

- [ ] **Step 1: Write the tests** (`web/e2e/now.spec.ts`)

```ts
import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8799'
const AT = new Date().toISOString()

test('un agent qui commence un run allume son poste en moins d\'une seconde', async ({ page, request }) => {
  await page.goto('/#/maintenant')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  const task = await (await request.post(`${API}/api/tasks`, { data: { title: 'Pont e2e', objective: 'Tester Maintenant', status: 'todo', next_action: 'x' } })).json()
  for (const [kind, extra] of [['claimed', {}], ['working', { payload: { run_ref: 'session:e2e' } }]] as const) {
    const res = await request.post(`${API}/api/events`, { data: { id: `evt_e2e_${kind}_${Date.now()}`, at: AT, actor: 'codex', kind, subject: 's', task: task.id, ...extra } })
    expect(res.ok()).toBeTruthy()
  }
  await expect(page.locator('[data-agent="codex"]')).toHaveAttribute('data-run', 'true', { timeout: 1000 })
})

test('une question pour Loïc arrive sur sa table et dans les demandes reçues', async ({ page, request }) => {
  await page.goto('/#/maintenant')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  const res = await request.post(`${API}/api/events`, { data: { id: `evt_e2e_q_${Date.now()}`, at: AT, actor: 'mnema', kind: 'question', subject: 'Quelle version de Python cibler ?', needs: ['loic'] } })
  expect(res.ok()).toBeTruthy()
  const ref = (await res.json()).id as string
  await expect(page.locator(`[data-ticket="${ref}"]`)).toBeAttached({ timeout: 1000 })
  await expect(page.getByRole('complementary', { name: 'Système' }).getByText('Quelle version de Python cibler ?')).toBeVisible()
})

test('fenêtre étroite : la liste des agents remplace l\'étage', async ({ page }) => {
  await page.setViewportSize({ width: 720, height: 900 })
  await page.goto('/#/maintenant')
  await expect(page.getByRole('list', { name: 'Agents' })).toBeVisible()
  await expect(page.getByRole('img', { name: /Étage de Nexus/ })).toBeHidden()
})
```

- [ ] **Step 2: Run** `pnpm e2e` — all green (existing + 3 new). Prove the first two bite: temporarily stop invalidating `['now']` in `liveUpdates.ts` → both fail on their 1 s timeout (the 10 s polling is slower); restore (`git diff -- web/src` empty).

- [ ] **Step 3: Look at it** (Loïc's standing rule: regularly look at what you build). With a throwaway database seeded through the API (never the real `nexus.db`: start the servers with `NEXUS_DATA_DIR` in the scratchpad), open `#/maintenant` at 1440×900, 1100 px and 760 px, take screenshots, and check: no label overlaps another label or a desk; the table label and the rack legend sit clear of the scene; the reduced-motion setting shows final states. Fix placement constants in `Floor.tsx` if needed (keep the DOM contract). Record what you checked and adjusted in the report.

- [ ] **Step 4: Checklist** — in `docs/agents/review-checklist.md` §6 add:

```markdown
- [ ] An animated scene only animates on a real state change (never on first render, never in a loop), keeps working in a background tab, and honours `prefers-reduced-motion`; its labels were checked by eye at wide, medium and narrow widths (#6).
```

- [ ] **Step 5: Commit**

```bash
git add web/e2e/now.spec.ts docs/agents/review-checklist.md web/src/now/Floor.tsx
git commit -m "test: parcours Maintenant de bout en bout et contrôle visuel (#6)"
```

- [ ] **Step 6: Pre-PR gate** (controller): walk the checklist; `pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm --dir web build`, `pnpm e2e`; push; PR `Closes #6`; Antigravity (Gemini 3.8 Flash High) until clean; `@codex review` (merge at no P1, P2s to an issue); open the follow-up issues named in the spec (approbations et réponses ; thème sombre pour Travail).
