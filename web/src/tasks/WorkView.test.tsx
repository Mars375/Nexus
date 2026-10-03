import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { Task } from '@/api'
import { WorkView } from './WorkView'

const TASK: Task = {
  id: 'nx-task-1', title: 'Pont lecture', objective: 'Lire les runs', status: 'todo',
  human_owner: 'loic', lead_agent: null, collaborators: [], next_action: 'relever les tables',
  due_at: null, follow_up_at: null, block_cause: null, block_plan: null, drop_reason: null,
  expected_evidence: null, evidence: [], priority: 'normal', operation_role: null, origin: null,
  context: [], depends_on: [], created_by: 'loic', created_at: '2026-09-28T10:00:00+02:00',
  updated_at: '2026-09-28T10:00:00+02:00', source: 'nexus.db', measured_at: '2026-09-28T10:00:00+02:00',
}

afterEach(() => vi.unstubAllGlobals())

function view(openTask: string | null) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(String(url).endsWith('/api/tasks') ? [TASK] : []), { status: 200, headers: { 'content-type': 'application/json' } })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (t: string | null) => <QueryClientProvider client={client}><WorkView openTask={t} /></QueryClientProvider>
  const r = render(ui(openTask))
  return (t: string | null) => r.rerender(ui(t))
}

test('revenir à Travail (hash sans tâche) ferme le volet', async () => {
  const rerender = view('nx-task-1')
  expect(await screen.findByRole('complementary', { name: /Détail de Pont lecture/ })).toBeInTheDocument()
  rerender(null)
  expect(screen.queryByRole('complementary', { name: /Détail de Pont lecture/ })).not.toBeInTheDocument()
})

test('ouvrir une carte dans Travail (prop inchangée) ouvre le volet', async () => {
  view(null)
  fireEvent.click(await screen.findByRole('button', { name: /Pont lecture — ouvrir ou déplacer/ }))
  expect(await screen.findByRole('complementary', { name: /Détail de Pont lecture/ })).toBeInTheDocument()
})
