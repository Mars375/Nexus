# Provenance et fraîcheur partout — plan d'implémentation (#8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** chaque donnée affichée dit sa source et son âge, une donnée trop vieille est marquée « périmée », et aucune route `GET /api/…` ne peut renvoyer une entité sans provenance sans faire échouer les tests.

**Architecture:** côté serveur, un test générique parcourt les routes `GET /api/…` et vérifie le contrat de provenance sur chaque entité. Côté web, un registre `freshness.ts` (cadences, sources, règle de péremption) alimente un composant `Provenance` qui suit lui-même l'horloge ; les vues l'utilisent (en-tête Travail, panneau d'une tâche, commentaires, historique, barre de santé).

**Tech Stack:** FastAPI + pytest (`uv run --directory server pytest`), React 19 + TypeScript + TanStack Query, Vitest + Testing Library (`pnpm --dir web test`), Playwright (`pnpm e2e`).

**Spec:** `docs/superpowers/specs/2026-09-29-provenance-fraicheur-design.md`

## Global Constraints

- Branche `feat/8-provenance` (à jour avec master). Chaque `git commit` passe par le hook pre-commit : gitleaks, ruff/oxlint, `tsc`, **tous** les tests serveur et web. On ne commite donc jamais un test rouge : l'étape RED se vérifie en local, le commit vient après le GREEN.
- Textes d'interface en français ; identifiants en anglais (ADR-009).
- Format affiché : `source : nexus.db · mesuré il y a 32 s` (formulation déjà utilisée par la barre de santé, VIEWS §9) ; « périmée » en toutes lettres, pas seulement en couleur.
- Péremption : `now - measured_at > 3 × cadence` (strictement) ; cadences : tâches 10 s, santé 10 s, nœuds 60 s.
- `source_url` : facultatif ; lien « ouvrir » seulement si l'URL commence par `https://` (nouvel onglet, `rel="noreferrer"`).
- Aucune animation ajoutée ; seul le passage à « périmée » change l'apparence.
- Ne pas recopier de valeur reçue dans un message d'erreur (checklist §1).

---

### Task 1: Contrat de provenance de l'API (test générique) et `measured_at` de la sauvegarde

**Files:**
- Create: `server/tests/test_provenance_contract.py`
- Modify: `server/src/nexus/app.py` (route `/api/health`, vers la ligne 130)

**Interfaces:**
- Produces: `GET /api/health` → `backup` porte `measured_at` (ISO-8601 avec fuseau). Côté web, le type `Health.backup` gagne `measured_at: string` (Task 2).

- [ ] **Step 1: Write the failing test**

```python
"""Contrat ADR-005 : toute entité renvoyée par une route GET /api/… porte sa provenance.

Le test parcourt les routes déclarées : une nouvelle route est vérifiée sans qu'il faille
l'ajouter ici, et un paramètre de chemin inconnu fait échouer le test au lieu d'être ignoré.
"""

from datetime import datetime

import pytest
from fastapi.routing import APIRoute

AT = "2026-09-29T09:05:00+02:00"


def fill_path(path: str, values: dict[str, str]) -> str:
    names = [part[1:-1] for part in path.split("/") if part.startswith("{")]
    missing = [name for name in names if name not in values]
    if missing:
        raise AssertionError(
            f"paramètre de chemin sans valeur de test : {missing} dans {path} — "
            "ajoute-le à PATH_VALUES dans test_provenance_contract.py"
        )
    return path.format(**values)


def entities(body) -> list:
    """Entités affichables d'une réponse, selon la règle de la spec."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and "source" in body:
        return [body]
    if isinstance(body, dict):
        children = [v for v in body.values() if isinstance(v, dict)]
        return children or [body]
    return [body]


def check_entity(entity) -> None:
    assert isinstance(entity, dict), f"entité non objet : {entity!r}"
    assert isinstance(entity.get("source"), str) and entity["source"].strip(), entity
    measured = entity.get("measured_at")
    assert isinstance(measured, str), f"measured_at manquant : {entity}"
    assert datetime.fromisoformat(measured).tzinfo is not None, f"sans fuseau : {measured}"
    if "source_url" in entity and entity["source_url"] is not None:
        assert str(entity["source_url"]).startswith("https://"), entity["source_url"]


def seed(client) -> dict[str, str]:
    task = client.post("/api/tasks", json={"title": "Pont", "objective": "Lire"}).json()["id"]
    client.post(f"/api/tasks/{task}/comments", json={"body": "noté"})
    event = client.post("/api/events", json={
        "id": "evt_contract", "at": AT, "actor": "helios", "kind": "claimed",
        "subject": "je prends", "task": task,
    }).json()["id"]
    return {"task_ref": task, "event_ref": event}


def api_get_routes(app) -> list[str]:
    return sorted(
        route.path for route in app.routes
        if isinstance(route, APIRoute) and "GET" in route.methods
        and route.path.startswith("/api/")
    )


def test_every_api_get_route_returns_entities_with_provenance(client):
    values = seed(client)
    routes = api_get_routes(client.app)
    assert routes, "aucune route GET /api/ trouvée"
    for path in routes:
        res = client.get(fill_path(path, values))
        assert res.status_code == 200, f"{path} → {res.status_code} {res.text}"
        found = entities(res.json())
        for entity in found:
            check_entity(entity)


def test_the_checker_catches_a_missing_measured_at():
    with pytest.raises(AssertionError):
        for entity in entities({"version": "1", "backup": {"source": "x"}}):
            check_entity(entity)


def test_the_checker_ignores_nested_data_of_an_entity():
    event = {"source": "nexus.db", "measured_at": AT, "payload": {"x": 1}, "effects": [{"a": 1}]}
    for entity in entities(event):
        check_entity(entity)


def test_an_unknown_path_parameter_fails_loudly():
    with pytest.raises(AssertionError, match="PATH_VALUES"):
        fill_path("/api/things/{thing_ref}", {"task_ref": "nx-task-1"})


def test_source_url_must_be_https():
    with pytest.raises(AssertionError):
        check_entity({"source": "telegram", "measured_at": AT, "source_url": "javascript:x"})
```

- [ ] **Step 2: Run test to verify it fails for the right reason**

Run: `uv run --directory server pytest tests/test_provenance_contract.py -v`
Expected: the four checker tests PASS; `test_every_api_get_route_returns_entities_with_provenance` FAILS with `measured_at manquant : {'last_at': …, 'count': 0, 'source': 'nexus.db/backups'}` (route `/api/health`).

- [ ] **Step 3: Minimal implementation — `backup.measured_at`**

In `server/src/nexus/app.py`, route `health()`, replace the `return {...}` block with:

```python
        measured_at = now().isoformat()
        return {
            "version": app.version,
            "db": {"status": db_status, "source": "nexus.db", "measured_at": measured_at},
            "backup": {"last_at": last, "count": len(backups), "source": "nexus.db/backups",
                       "measured_at": measured_at},
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory server pytest -q`
Expected: all PASS (≥ 417 + 5).

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_provenance_contract.py server/src/nexus/app.py
git commit -m "feat: contrat de provenance vérifié sur toutes les routes GET /api (#8)"
```

---

### Task 2: Registre de fraîcheur (`freshness.ts`) et types API

**Files:**
- Create: `web/src/freshness.ts`, `web/src/freshness.test.ts`
- Modify: `web/src/api.ts` (types `Health`, `Comment`, `HistoryEntry`), `web/src/tasks/queries.ts` (`TASKS_REFRESH_MS`), `web/src/HealthStatus.tsx` (`refetchInterval`)

**Interfaces:**
- Produces:
  - `type FreshnessKind = 'tasks' | 'health' | 'nodes'`
  - `REFRESH_MS: Record<FreshnessKind, number>` — `{ tasks: 10_000, health: 10_000, nodes: 60_000 }`
  - `STALE_FACTOR = 3`
  - `SOURCE_OF: Record<FreshnessKind, string>` — `{ tasks: 'nexus.db', health: 'nexus.db', nodes: 'tailscale' }`
  - `isStale(measuredAt: string, kind: FreshnessKind, now: number): boolean`
  - `type Provenanced = { source: string; measured_at: string; source_url?: string | null }`
  - `listProvenance(items: Provenanced[], kind: FreshnessKind, dataUpdatedAt: number): { source: string; measuredAt: string } | null`
  - Types: `Comment` and `HistoryEntry` gain `source: string; measured_at: string`; `Health.backup` gains `measured_at: string`.

- [ ] **Step 1: Write the failing test** (`web/src/freshness.test.ts`)

```ts
import { describe, expect, test } from 'vitest'
import { isStale, listProvenance, REFRESH_MS, SOURCE_OF, STALE_FACTOR } from './freshness'

const T0 = Date.parse('2026-09-29T10:00:00+02:00')
const at = (ms: number) => new Date(T0 + ms).toISOString()

describe('isStale', () => {
  test('juste à 3 × la cadence, la donnée est encore fraîche', () => {
    expect(isStale(at(0), 'tasks', T0 + STALE_FACTOR * REFRESH_MS.tasks)).toBe(false)
  })
  test('au-delà de 3 × la cadence, elle est périmée', () => {
    expect(isStale(at(0), 'tasks', T0 + 30_001)).toBe(true)
  })
  test('la cadence dépend du type : un nœud reste frais 3 min', () => {
    expect(isStale(at(0), 'nodes', T0 + 179_000)).toBe(false)
    expect(isStale(at(0), 'nodes', T0 + 181_000)).toBe(true)
  })
  test('une date illisible compte comme périmée', () => {
    expect(isStale('pas une date', 'tasks', T0)).toBe(true)
  })
  test('une date dans le futur n’est jamais périmée', () => {
    expect(isStale(at(60_000), 'tasks', T0)).toBe(false)
  })
})

describe('listProvenance', () => {
  test('une liste est aussi fraîche que son élément le plus ancien', () => {
    const items = [
      { source: 'nexus.db', measured_at: at(5_000) },
      { source: 'nexus.db', measured_at: at(0) },
    ]
    expect(listProvenance(items, 'tasks', T0 + 6_000)).toEqual({ source: 'nexus.db', measuredAt: at(0) })
  })
  test('liste vide : source du type et instant de la dernière lecture réussie', () => {
    expect(listProvenance([], 'tasks', T0)).toEqual({
      source: SOURCE_OF.tasks,
      measuredAt: new Date(T0).toISOString(),
    })
  })
  test('liste vide jamais lue : rien à afficher', () => {
    expect(listProvenance([], 'tasks', 0)).toBeNull()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir web exec vitest run src/freshness.test.ts`
Expected: FAIL — `Failed to resolve import "./freshness"`.

- [ ] **Step 3: Implement `web/src/freshness.ts`**

```ts
/*
 * Fraîcheur des données (ADR-005) : cadence de relecture par type, et règle de péremption.
 * Une donnée est périmée quand elle a plus de STALE_FACTOR relectures de retard.
 */
export type FreshnessKind = 'tasks' | 'health' | 'nodes'

export const REFRESH_MS: Record<FreshnessKind, number> = {
  tasks: 10_000,
  health: 10_000,
  nodes: 60_000,
}

export const STALE_FACTOR = 3

/** Source déclarée d'un type, pour une liste vide qui n'a aucun élément à citer. */
export const SOURCE_OF: Record<FreshnessKind, string> = {
  tasks: 'nexus.db',
  health: 'nexus.db',
  nodes: 'tailscale',
}

export type Provenanced = { source: string; measured_at: string; source_url?: string | null }

export function isStale(measuredAt: string, kind: FreshnessKind, now: number): boolean {
  const measured = Date.parse(measuredAt)
  if (Number.isNaN(measured)) return true // illisible : on ne prétend pas qu'elle est fraîche
  return now - measured > STALE_FACTOR * REFRESH_MS[kind]
}

/** Provenance d'une liste : son élément le plus ancien ; vide, la dernière lecture réussie. */
export function listProvenance(
  items: Provenanced[],
  kind: FreshnessKind,
  dataUpdatedAt: number,
): { source: string; measuredAt: string } | null {
  if (items.length === 0) {
    return dataUpdatedAt > 0
      ? { source: SOURCE_OF[kind], measuredAt: new Date(dataUpdatedAt).toISOString() }
      : null
  }
  const oldest = items.reduce((a, b) => {
    const ta = Date.parse(a.measured_at)
    const tb = Date.parse(b.measured_at)
    if (Number.isNaN(tb)) return b
    if (Number.isNaN(ta)) return a
    return tb < ta ? b : a
  })
  return { source: oldest.source, measuredAt: oldest.measured_at }
}
```

- [ ] **Step 4: Wire the registry and update the types**

`web/src/tasks/queries.ts` — replace the constant, keep its name (used elsewhere):

```ts
import { REFRESH_MS } from '@/freshness'
// …
/** En attendant le temps réel (#5), relecture régulière : un agent peut modifier une tâche. */
export const TASKS_REFRESH_MS = REFRESH_MS.tasks
```

`web/src/HealthStatus.tsx` — `refetchInterval: 10_000,` becomes `refetchInterval: REFRESH_MS.health,` with `import { REFRESH_MS } from './freshness'`.

`web/src/api.ts`:

```ts
export type Health = {
  version: string
  db: { status: 'ok' | 'unknown'; source: string; measured_at: string }
  backup: { last_at: string | null; count: number; source: string; measured_at: string }
}
// …
export type Comment = {
  id: number
  task: string
  author: Actor
  body: string
  at: string
  source: string
  measured_at: string
}

export type HistoryEntry = {
  id: number
  task: string
  actor: Actor
  at: string
  action: string
  changes: Record<string, unknown>
  source: string
  measured_at: string
}
```

(Keep the existing `version` field exactly as it is in the current `Health` type.) Then fix every test fixture that builds a `Comment`, `HistoryEntry` or `Health` object so `pnpm typecheck` passes: add `source: 'nexus.db', measured_at: <same instant as the fixture>`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pnpm --dir web exec vitest run` and `pnpm typecheck`
Expected: all PASS, no type error.

- [ ] **Step 6: Commit**

```bash
git add web/src/freshness.ts web/src/freshness.test.ts web/src/api.ts web/src/tasks/queries.ts web/src/HealthStatus.tsx web/src
git commit -m "feat: registre de fraîcheur et types de provenance côté web (#8)"
```

---

### Task 3: Composant `Provenance`

**Files:**
- Create: `web/src/Provenance.tsx`, `web/src/Provenance.test.tsx`

**Interfaces:**
- Consumes: `isStale`, `FreshnessKind` (Task 2); `useNow` (`web/src/useNow.ts`, `useNow(intervalMs = 1000): number`); `age(iso, now)` and `formatDateTime(iso)` (`web/src/format.ts`).
- Produces: `Provenance(props: { source: string; measuredAt: string; kind: FreshnessKind; url?: string | null; className?: string }): JSX.Element` — renders an inline `<span>`.

- [ ] **Step 1: Write the failing test** (`web/src/Provenance.test.tsx`)

```tsx
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { Provenance } from './Provenance'

const T0 = Date.parse('2026-09-29T10:00:00+02:00')

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(T0)
})
afterEach(() => vi.useRealTimers())

test('affiche la source et l’âge, sans mention périmée tant que la donnée est fraîche', () => {
  render(<Provenance source="nexus.db" measuredAt={new Date(T0 - 5_000).toISOString()} kind="tasks" />)
  expect(screen.getByText(/^source : nexus\.db · mesuré il y a 5 s/)).toBeInTheDocument()
  expect(screen.queryByText('périmée')).not.toBeInTheDocument()
})

test('passe à « périmée » quand l’horloge dépasse 3 × la cadence, sans nouvelle lecture', () => {
  render(<Provenance source="nexus.db" measuredAt={new Date(T0 - 29_000).toISOString()} kind="tasks" />)
  expect(screen.queryByText('périmée')).not.toBeInTheDocument()
  act(() => vi.advanceTimersByTime(2_000))
  expect(screen.getByText('périmée')).toBeInTheDocument()
})

test('une date illisible est dite illisible et périmée', () => {
  render(<Provenance source="nexus.db" measuredAt="pas une date" kind="tasks" />)
  expect(screen.getByText(/date de mesure illisible/)).toBeInTheDocument()
  expect(screen.getByText('périmée')).toBeInTheDocument()
})

test('le lien « ouvrir » n’apparaît que pour une adresse https', () => {
  const { rerender } = render(
    <Provenance source="telegram" measuredAt={new Date(T0).toISOString()} kind="tasks" url="https://t.me/c/1/2" />,
  )
  const link = screen.getByRole('link', { name: 'ouvrir' })
  expect(link).toHaveAttribute('href', 'https://t.me/c/1/2')
  expect(link).toHaveAttribute('rel', 'noreferrer')
  rerender(<Provenance source="telegram" measuredAt={new Date(T0).toISOString()} kind="tasks" url="javascript:alert(1)" />)
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir web exec vitest run src/Provenance.test.tsx`
Expected: FAIL — `Failed to resolve import "./Provenance"`.

- [ ] **Step 3: Implement `web/src/Provenance.tsx`**

```tsx
import clsx from 'clsx'
import { isStale, type FreshnessKind } from './freshness'
import { age, formatDateTime } from './format'
import { useNow } from './useNow'

type Props = {
  source: string
  measuredAt: string
  kind: FreshnessKind
  url?: string | null
  className?: string
}

/**
 * « source : nexus.db · mesuré il y a 32 s » (VIEWS §9, ADR-005). Le composant suit seul
 * l'horloge : l'âge avance sans nouvelle lecture et la donnée passe « périmée » d'elle-même,
 * sans redessiner la vue qui l'affiche.
 */
export function Provenance({ source, measuredAt, kind, url, className }: Props) {
  const now = useNow()
  const readable = !Number.isNaN(Date.parse(measuredAt))
  const stale = isStale(measuredAt, kind, now)
  const link = url?.startsWith('https://') ? url : null
  return (
    <span
      className={clsx('text-2xs', stale ? 'text-attention' : 'text-muted', className)}
      title={readable ? `mesuré le ${formatDateTime(measuredAt)}` : undefined}
    >
      source : {source} · {readable ? `mesuré ${age(measuredAt, now)}` : 'date de mesure illisible'}
      {stale && (
        <>
          {' · '}
          <strong className="font-medium">périmée</strong>
        </>
      )}
      {link && (
        <>
          {' · '}
          <a href={link} target="_blank" rel="noreferrer" className="underline">
            ouvrir
          </a>
        </>
      )}
    </span>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir web exec vitest run` and `pnpm typecheck` and `pnpm --dir web exec oxlint src`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/Provenance.tsx web/src/Provenance.test.tsx
git commit -m "feat: composant Provenance, périmée en toutes lettres (#8)"
```

---

### Task 4: Brancher la provenance dans Travail et la barre de santé

**Files:**
- Modify: `web/src/tasks/WorkView.tsx` (après le `</header>` du tableau, vers la ligne 80), `web/src/tasks/TaskPane.tsx` (en-tête vers la ligne 59 ; sections `Commentaires` vers la ligne 420 et `Historique` vers la ligne 480), `web/src/HealthStatus.tsx`
- Test: `web/src/tasks/TaskPane.test.tsx`, `web/src/HealthStatus.test.tsx`

**Interfaces:**
- Consumes: `Provenance` (Task 3); `listProvenance` (Task 2); `useTasks()` / `useComments(id)` / `useHistory(id)` (TanStack results expose `data` and `dataUpdatedAt`).

- [ ] **Step 1: Write the failing tests**

Append to `web/src/tasks/TaskPane.test.tsx` (the file already defines `TASK` with `source` and `measured_at`, and imports `render`, `screen`, `QueryClient`, `QueryClientProvider`, `vi`):

```tsx
test('le panneau dit d’où viennent la tâche, ses commentaires et son historique', async () => {
  const now = new Date().toISOString()
  const comment = { id: 1, task: TASK.id, author: 'loic', body: 'noté', at: now, source: 'nexus.db', measured_at: now }
  const entry = { id: 1, task: TASK.id, actor: 'loic', at: now, action: 'created', changes: {}, source: 'nexus.db', measured_at: now }
  vi.stubGlobal('fetch', vi.fn(async (url: string) =>
    Response.json(String(url).endsWith('/comments') ? [comment] : [entry]),
  ))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TaskPane task={{ ...TASK, measured_at: now }} tasks={[TASK]} onClose={() => {}} />
    </QueryClientProvider>,
  )
  expect(await screen.findAllByText(/^source : nexus\.db · mesuré il y a/)).toHaveLength(3)
})
```

In `web/src/HealthStatus.test.tsx`, the existing test `affiche la base OK avec sa provenance` keeps asserting `/^source : nexus\.db · mesuré il y a/`; update its `healthy()` fixture so `backup` carries `measured_at: measured`, and add:

```tsx
test('une santé trop ancienne est dite périmée', async () => {
  const old = new Date(Date.now() - 60_000).toISOString()
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({
    version: '0.1.0',
    db: { status: 'ok', source: 'nexus.db', measured_at: old },
    backup: { last_at: null, count: 0, source: 'nexus.db/backups', measured_at: old },
  })))
  renderApp()
  expect(await screen.findByText('périmée')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --dir web exec vitest run src/tasks/TaskPane.test.tsx src/HealthStatus.test.tsx`
Expected: the two new tests FAIL (no provenance in the pane; no « périmée » in the health bar).

- [ ] **Step 3: Implement**

`web/src/tasks/TaskPane.tsx` — imports: `import { listProvenance } from '@/freshness'` and `import { Provenance } from '@/Provenance'`.

Under the title `<h2 …>{task.title}</h2>` in the header:

```tsx
          <Provenance source={task.source} measuredAt={task.measured_at} kind="tasks" className="mt-1 block" />
```

In `Comments`, right after `<LoadState query={comments} … />`:

```tsx
      <ListProvenance items={comments.data} updatedAt={comments.dataUpdatedAt} />
```

In `History`, right after `<LoadState query={history} … />`:

```tsx
      <ListProvenance items={history.data} updatedAt={history.dataUpdatedAt} />
```

And add, next to `LoadState`:

```tsx
/** Provenance d'une sous-liste (commentaires, historique) : son élément le plus ancien. */
function ListProvenance({ items, updatedAt }: { items: Provenanced[] | undefined; updatedAt: number }) {
  const provenance = items ? listProvenance(items, 'tasks', updatedAt) : null
  return provenance ? (
    <p className="mb-2">
      <Provenance source={provenance.source} measuredAt={provenance.measuredAt} kind="tasks" />
    </p>
  ) : null
}
```

(with `type Provenanced` imported from `@/freshness`).

`web/src/tasks/WorkView.tsx` — imports `listProvenance` and `Provenance`; right after the board `</header>`:

```tsx
        {(() => {
          const provenance = tasks.data ? listProvenance(tasks.data, 'tasks', tasks.dataUpdatedAt) : null
          return provenance ? (
            <p className="px-5 pb-2">
              <Provenance source={provenance.source} measuredAt={provenance.measuredAt} kind="tasks" />
            </p>
          ) : null
        })()}
```

`web/src/HealthStatus.tsx` — replace the string helper `provenance()` and the `detail` string by elements: `detail` becomes a `ReactNode`:

```tsx
function Detail({ data }: { data: Health }) {
  const now = useNow()
  return (
    <>
      <Provenance source={data.db.source} measuredAt={data.db.measured_at} kind="health" />
      {data.backup.last_at && <> · dernière sauvegarde {age(data.backup.last_at, now)}</>}
    </>
  )
}
```

In the error branch keep the prefix: `detail = health.data ? <>dernier contrôle réussi — <Detail data={health.data} /></> : 'aucun contrôle réussi pour le moment'`; in the success branch `detail = <Detail data={health.data} />`. Remove the top-level `const now = useNow()` if nothing else uses it. Render `{detail && <span className="truncate">{detail}</span>}` unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir web exec vitest run`, `pnpm typecheck`, `pnpm --dir web exec oxlint src`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/tasks/WorkView.tsx web/src/tasks/TaskPane.tsx web/src/tasks/TaskPane.test.tsx web/src/HealthStatus.tsx web/src/HealthStatus.test.tsx
git commit -m "feat: provenance affichée dans Travail et la barre de santé (#8)"
```

---

### Task 5: Parcours Playwright

**Files:**
- Modify: `web/e2e/work.spec.ts`

**Interfaces:**
- Consumes: helpers `createTask(page, title, opts)`, `card(page, title)` already in the file.

- [ ] **Step 1: Write the test**

```ts
test('le tableau et le détail disent d’où viennent les données', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText(/^source : nexus\.db · mesuré il y a/).first()).toBeVisible()
  await createTask(page, 'Tracer la provenance')
  await card(page, 'Tracer la provenance').click()
  const pane = page.getByRole('complementary', { name: 'Détail de Tracer la provenance' })
  await expect(pane.getByText(/^source : nexus\.db · mesuré il y a/).first()).toBeVisible()
})
```

- [ ] **Step 2: Run it**

Run: `pnpm e2e`
Expected: all scenarios PASS (the new one included). If the new test fails because the empty-board header is missing, check Task 4's `listProvenance` call receives `tasks.dataUpdatedAt`.

- [ ] **Step 3: Commit**

```bash
git add web/e2e/work.spec.ts
git commit -m "test: parcours Playwright de la provenance (#8)"
```

---

### Task 6: Leçons de #13 dans la checklist, puis PR

**Files:**
- Modify: `docs/agents/review-checklist.md`

- [ ] **Step 1: Add the lessons from the last review rounds of #13**

In §2 Validation, after the `InputModel` item, add:

```markdown
- [ ] A service that other code may call directly (future adapters, ADR-015) re-checks what the HTTP models guarantee: strict JSON only (no set, bytes, datetime, non-str keys), timezone-aware instants, known enums, a plain adapter name for `origin` — refused with a `RuleViolation`, never a crash during `flush()`.
```

In §3 Concurrency, add:

```markdown
- [ ] A decision about the current state ("already in this status", "already lead agent") is taken on a fresh read (`session.refresh`) inside the write transaction, never on the copy loaded before it; an effect that changes nothing is recorded as not applied, never as a success.
```

In §5 Provenance, add:

```markdown
- [ ] `server/tests/test_provenance_contract.py` walks every `GET /api/…` route: a new route with a new path parameter must add it to `PATH_VALUES`, and its entities must carry `source` + `measured_at`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/agents/review-checklist.md
git commit -m "docs: checklist — leçons des derniers tours de #13, contrat de provenance"
```

- [ ] **Step 3: Pre-PR gate** — walk `docs/agents/review-checklist.md`, run `pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm --dir web build`, `pnpm e2e`; push; open the PR (`Closes #8`) with the checklist notes; run the `antigravity` skill review until clean; then `@codex review` (final gate; merge when a round has no P1, P2s go to an issue).
