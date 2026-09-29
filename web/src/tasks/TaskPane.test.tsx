import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
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

test('un choix de dépendance devenu invalide reste affiché, avec sa raison, et bloque l’ajout', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json([])))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const current = { ...TASK, status: 'in_progress' as const }
  const prereq = { ...TASK, id: 'nx-task-2', title: 'Prérequis', status: 'done' as const }
  const other = { ...TASK, id: 'nx-task-3', title: 'Autre', status: 'dropped' as const }
  const pane = (tasks: Task[]) => (
    <QueryClientProvider client={client}>
      <TaskPane task={current} tasks={tasks} onClose={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(pane([current, prereq, other]))
  const picker = screen.getByLabelText('Tâche dont celle-ci dépend') as HTMLSelectElement
  const add = screen.getByRole('button', { name: 'Ajouter' })

  fireEvent.change(picker, { target: { value: 'nx-task-2' } })
  expect(add).toBeEnabled()

  // Un agent rouvre le prérequis pendant que Loïc hésite.
  rerender(pane([current, { ...prereq, status: 'todo' }, other]))

  expect(picker.value).toBe('nx-task-2')
  expect(screen.getByRole('alert')).toHaveTextContent(/pas encore traitée/)
  expect(add).toBeDisabled()

  fireEvent.change(picker, { target: { value: 'nx-task-3' } })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(add).toBeEnabled()
})

test('un cycle apparu pendant la sélection est expliqué et bloque l’ajout', () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json([])))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const current = { ...TASK, status: 'todo' as const }
  const other = { ...TASK, id: 'nx-task-2', title: 'Autre', status: 'todo' as const }
  const pane = (tasks: Task[]) => (
    <QueryClientProvider client={client}>
      <TaskPane task={current} tasks={tasks} onClose={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(pane([current, other]))
  fireEvent.change(screen.getByLabelText('Tâche dont celle-ci dépend'), { target: { value: 'nx-task-2' } })

  // Un agent fait dépendre « Autre » de cette tâche : l'ajout créerait un cycle.
  rerender(pane([current, { ...other, depends_on: [current.id] }]))

  expect(screen.getByRole('alert')).toHaveTextContent(/cycle/)
  expect(screen.getByRole('button', { name: 'Ajouter' })).toBeDisabled()
})
