import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { Task } from '@/api'
import { MoveDialog } from './MoveDialog'

const TASK: Task = {
  id: 'nx-task-1', title: 'Pont lecture', objective: 'Lire les runs', status: 'in_progress',
  human_owner: 'loic', lead_agent: null, collaborators: [], next_action: 'relever les tables',
  due_at: null, follow_up_at: null, block_cause: null, block_plan: null, drop_reason: null,
  expected_evidence: null, evidence: [], priority: 'normal', operation_role: null, origin: null,
  context: [], depends_on: [], follows: null, created_by: 'loic', created_at: '2026-09-28T10:00:00+02:00',
  updated_at: '2026-09-28T10:00:00+02:00', source: 'nexus.db', measured_at: '2026-09-28T10:00:00+02:00',
}

afterEach(() => vi.unstubAllGlobals())

function dialog(task: Task, to: 'done' | 'blocked', all: Task[], onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <MoveDialog task={task} to={to} all={all} onClose={onClose} />
    </QueryClientProvider>
  )
}

test('le passage reste possible tant que la tâche courante le permet', () => {
  render(dialog(TASK, 'done', [TASK]))
  expect(screen.getByRole('button', { name: 'Déplacer en terminé' })).toBeEnabled()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

/** `useMoveTask` attend `cancelQueries` avant `fetch` : on laisse passer ce délai avant de conclure « rien envoyé ». */
const settle = () => new Promise((resolve) => setTimeout(resolve, 30))

test('la tâche est terminée pendant que la boîte est ouverte : message, envoi désactivé, rien n’est envoyé', async () => {
  const fetchMock = vi.fn(async () => Response.json({}))
  vi.stubGlobal('fetch', fetchMock)
  // La boîte garde la copie reçue à l'ouverture (glisser) ; `all` porte la tâche à jour.
  const closed = { ...TASK, status: 'done' as const }
  const { container } = render(dialog(TASK, 'blocked', [closed]))

  expect(screen.getByRole('alert')).toHaveTextContent(
    'Cette tâche vient d’être terminée : ce passage n’est plus possible.',
  )
  const send = screen.getByRole('button', { name: 'Déplacer en bloqué' })
  expect(send).toBeDisabled()
  fireEvent.submit(container.ownerDocument.querySelector('form')!)
  await settle()
  expect(fetchMock).not.toHaveBeenCalled()
})

test('les preuves se séparent par ligne : une virgule appartient à la preuve', async () => {
  const fetchMock = vi.fn(async () => Response.json(TASK))
  vi.stubGlobal('fetch', fetchMock)
  render(dialog(TASK, 'done', [TASK]))
  fireEvent.change(screen.getByPlaceholderText('commit:a1b2c3d'), { target: { value: 'commit:a1\nhttps://example.test/a,b\n\n' } })
  fireEvent.click(screen.getByRole('button', { name: 'Déplacer en terminé' }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][]
  const move = calls.find(([, init]) => init?.body)!
  expect(JSON.parse(String(move[1].body)).evidence).toEqual(['commit:a1', 'https://example.test/a,b'])
})

test('la boîte se met à jour avec la tâche : terminée pendant la saisie, elle se désactive', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (all: Task[]) => (
    <QueryClientProvider client={client}>
      <MoveDialog task={TASK} to="done" all={all} onClose={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(ui([TASK]))
  expect(screen.getByRole('button', { name: 'Déplacer en terminé' })).toBeEnabled()

  rerender(ui([{ ...TASK, status: 'done' }]))
  expect(screen.getByRole('button', { name: 'Déplacer en terminé' })).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('vient d’être terminée')
})

test('un autre changement de statut est dit sans prétendre que la tâche est terminée', () => {
  render(dialog(TASK, 'blocked', [{ ...TASK, status: 'blocked' }]))
  expect(screen.getByRole('alert')).toHaveTextContent('Cette tâche a changé de statut : ce passage n’est plus possible.')
  expect(screen.getByRole('alert')).not.toHaveTextContent('terminée')
})
