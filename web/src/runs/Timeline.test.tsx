import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { clearToken, markUnlocked } from '@/auth'
import type { TimelineEntry, TimelinePage } from '@/timelineApi'
import { Timeline } from './Timeline'

const T = '2026-11-10T09:00:00+00:00'
let n = 0

function event(kind: string, extra: Partial<TimelineEntry> = {}): TimelineEntry {
  n += 1
  return {
    id: `event-${n}`, kind: 'event', at: T, actor: 'codex', event: `evt_${n}`, event_kind: kind,
    subject: `sujet ${n}`, body: null, origin: 'fake', effects: [], evidence: [], needs: [], run: 'nx-run-1',
    source: 'nexus.db', measured_at: T, ...extra,
  }
}

const page = (entries: TimelineEntry[], next: string | null = null): TimelinePage => ({
  entries, next_cursor: next, source: 'nexus.db', measured_at: T,
})

function serve(pages: (before: string | null) => TimelinePage | 'error') {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, '')
      urls.push(path)
      const out = pages(new URL(path, 'http://x').searchParams.get('before'))
      return out === 'error' ? new Response('boom', { status: 500 }) : new Response(JSON.stringify(out))
    }),
  )
  return urls
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Timeline id="nx-task-1" />
    </QueryClientProvider>,
  )
  return client
}

beforeEach(() => {
  clearToken()
  markUnlocked()
})
afterEach(() => vi.unstubAllGlobals())

test('chargement, puis état vide', async () => {
  serve(() => page([]))
  mount()
  expect(screen.getByText('Chargement de la chronologie…')).toBeInTheDocument()
  expect(await screen.findByText(/Rien ne s’est encore passé/)).toBeInTheDocument()
})

test('erreur sans donnée : le dit', async () => {
  serve(() => 'error')
  mount()
  expect(await screen.findByText(/Impossible de lire la chronologie/)).toBeInTheDocument()
})

test('un événement d’agent dit qui, quoi, le run et la preuve', async () => {
  serve(() => page([event('done', { evidence: ['commit:abc123'] })]))
  mount()
  expect(await screen.findByText('Codex a terminé')).toBeInTheDocument()
  expect(screen.getByText('nx-run-1')).toBeInTheDocument()
  expect(screen.getByText('commit:abc123')).toBeInTheDocument()
  expect(screen.getByText(/nexus\.db/)).toBeInTheDocument()
})

test('un effet non appliqué est rendu avec sa raison', async () => {
  serve(() => page([event('handoff', { effects: [{ action: 'handoff', applied: false, reason: 'tâche déjà terminée' }] })]))
  mount()
  expect(await screen.findByText(/Sans effet sur la tâche/)).toHaveTextContent('tâche déjà terminée')
})

test('les progress d’un run se replient et se déplient au clavier', async () => {
  serve(() => page([event('progress', { subject: 'étape C' }), event('progress', { subject: 'étape B' }), event('progress', { subject: 'étape A' })]))
  mount()
  const toggle = await screen.findByRole('button', { name: /3 avancées de nx-run-1/ })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByText('étape B')).not.toBeInTheDocument()
  toggle.focus()
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByText('étape B')).toBeInTheDocument()
})

test('un groupe déplié le reste quand la chronologie est relue', async () => {
  let entries = [event('progress', { id: 'event-a2' }), event('progress', { id: 'event-a1', subject: 'ancienne étape' })]
  serve(() => page(entries))
  const client = mount()
  fireEvent.click(await screen.findByRole('button', { name: /2 avancées/ }))
  expect(screen.getByText('ancienne étape')).toBeInTheDocument()

  entries = [event('progress', { id: 'event-a3' }), ...entries]
  await client.invalidateQueries({ queryKey: ['tasks', 'nx-task-1'] })

  expect(await screen.findByRole('button', { name: /3 avancées/ })).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByText('ancienne étape')).toBeInTheDocument()
})

test('« Charger plus ancien » lit la page suivante avec son curseur, sans doublon', async () => {
  const first = event('claimed', { subject: 'récent' })
  const old = event('working', { subject: 'ancien' })
  const urls = serve((before) => (before === 'v1.cursor' ? page([old]) : page([first], 'v1.cursor')))
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Charger plus ancien' }))
  expect(await screen.findByText('Codex travaille dessus')).toBeInTheDocument()
  expect(screen.getAllByText('Codex a pris la tâche')).toHaveLength(1)
  expect(urls.some((u) => u.includes('before=v1.cursor'))).toBe(true)
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Charger plus ancien' })).not.toBeInTheDocument())
})

test('l’historique des modifications reste lisible dans la chronologie', async () => {
  serve(() => page([{
    id: 'history-1', kind: 'history', at: T, actor: 'loic', action: 'status', changes: { status: ['todo', 'in_progress'] },
    source: 'nexus.db', measured_at: T,
  }]))
  mount()
  expect(await screen.findByText(/Loïc l'a passée de à faire à en cours/)).toBeInTheDocument()
})
