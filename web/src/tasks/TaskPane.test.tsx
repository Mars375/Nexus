import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { Task } from '@/api'
import { TaskPane } from './TaskPane'

const TASK: Task = {
  id: 'nx-task-1',
  title: 'Pont lecture',
  objective: 'Lire les runs',
  status: 'todo',
  human_owner: 'loic',
  lead_agent: null,
  collaborators: [],
  next_action: 'relever les tables',
  due_at: null,
  follow_up_at: null,
  block_cause: null,
  block_plan: null,
  drop_reason: null,
  expected_evidence: null,
  evidence: [],
  priority: 'normal',
  operation_role: null,
  origin: null,
  context: [],
  depends_on: [],
  created_by: 'loic',
  created_at: '2026-09-28T10:00:00+02:00',
  updated_at: '2026-09-28T10:00:00+02:00',
  source: 'nexus.db',
  measured_at: '2026-09-28T10:00:00+02:00',
}

function renderPane(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  render(
    <QueryClientProvider client={client}>
      <TaskPane task={TASK} tasks={[TASK]} onClose={() => {}} />
    </QueryClientProvider>,
  )
  return client
}

afterEach(() => vi.unstubAllGlobals())

test('un premier chargement raté des détails le dit, au lieu d’une section vide', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('boom', { status: 500 })))

  renderPane()

  expect(await screen.findByText(/Impossible de lire les commentaires/)).toBeInTheDocument()
  expect(await screen.findByText(/Impossible de lire l’historique/)).toBeInTheDocument()
})

test('un rafraîchissement raté garde les détails connus, signalés comme non à jour', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const comment = { id: 'c1', author: 'loic', at: TASK.created_at, body: 'Premier jet' }
  const entry = { id: 1, actor: 'loic', at: TASK.created_at, action: 'created', changes: {} }
  client.setQueryData(['tasks', TASK.id, 'comments'], [comment])
  client.setQueryData(['tasks', TASK.id, 'history'], [entry])
  vi.stubGlobal('fetch', vi.fn(async () => new Response('boom', { status: 500 })))

  renderPane(client)
  await client.invalidateQueries()

  expect(await screen.findByText('Premier jet')).toBeInTheDocument()
  expect(await screen.findByText(/Commentaires non à jour/)).toBeInTheDocument()
  expect(await screen.findByText(/Historique non à jour/)).toBeInTheDocument()
})
