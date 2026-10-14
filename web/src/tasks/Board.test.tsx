import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { act } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import type { Task } from '@/api'

type DndProps = {
  onDragStart: (e: { active: { id: string } }) => void
  onDragEnd: (e: { active: { id: string }; over: { id: string } | null }) => void
}
const captured: { props: DndProps | null } = { props: null }

vi.mock('@dnd-kit/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@dnd-kit/core')>()
  return {
    ...actual,
    DndContext: (props: DndProps & { children: React.ReactNode }) => {
      captured.props = props
      return <>{props.children}</>
    },
  }
})

const { Board } = await import('./Board')

const TASK: Task = {
  id: 'nx-task-1', title: 'Pont lecture', objective: 'Lire les runs', status: 'todo',
  human_owner: 'loic', lead_agent: null, collaborators: [], next_action: 'relever les tables',
  due_at: null, follow_up_at: null, block_cause: null, block_plan: null, drop_reason: null,
  expected_evidence: null, evidence: [], priority: 'normal', operation_role: null, origin: null,
  context: [], depends_on: [], follows: null, created_by: 'loic', created_at: '2026-09-28T10:00:00+02:00',
  updated_at: '2026-09-28T10:00:00+02:00', source: 'nexus.db', measured_at: '2026-09-28T10:00:00+02:00',
}

afterEach(() => vi.unstubAllGlobals())

const settle = () => new Promise((resolve) => setTimeout(resolve, 30))

function board(client: QueryClient, tasks: Task[]) {
  return (
    <QueryClientProvider client={client}>
      <Board tasks={tasks} allTasks={tasks} statuses={['todo', 'in_progress', 'done']} onOpen={() => {}} />
    </QueryClientProvider>
  )
}

test('déposer une carte devenue terminée pendant le glisser ne l’envoie pas', async () => {
  const fetchMock = vi.fn(async () => Response.json(TASK))
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const { rerender } = render(board(client, [TASK]))

  act(() => captured.props!.onDragStart({ active: { id: 'nx-task-1' } }))
  rerender(board(client, [{ ...TASK, status: 'done' }]))
  act(() => captured.props!.onDragEnd({ active: { id: 'nx-task-1' }, over: { id: 'in_progress' } }))

  await act(settle)
  expect(fetchMock).not.toHaveBeenCalled()
})

test('déposer une carte toujours déplaçable l’envoie', async () => {
  const fetchMock = vi.fn(async () => Response.json(TASK))
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(board(client, [TASK]))

  act(() => captured.props!.onDragStart({ active: { id: 'nx-task-1' } }))
  act(() => captured.props!.onDragEnd({ active: { id: 'nx-task-1' }, over: { id: 'in_progress' } }))

  await act(settle)
  expect(fetchMock).toHaveBeenCalled()
})
