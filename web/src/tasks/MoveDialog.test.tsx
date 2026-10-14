import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
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

test('la tâche est terminée pendant que la boîte est ouverte : message, envoi désactivé, rien n’est envoyé', () => {
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
  expect(fetchMock).not.toHaveBeenCalled()
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
