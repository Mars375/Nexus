import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { Task } from '@/api'
import { WorkView } from './WorkView'

const TASK: Task = {
  id: 'nx-task-1', title: 'Pont lecture', objective: 'Lire les runs', status: 'todo',
  human_owner: 'loic', lead_agent: null, collaborators: [], next_action: 'relever les tables',
  due_at: null, follow_up_at: null, block_cause: null, block_plan: null, drop_reason: null,
  expected_evidence: null, evidence: [], priority: 'normal', operation_role: null, origin: null,
  context: [], depends_on: [], follows: null, created_by: 'loic', created_at: '2026-09-28T10:00:00+02:00',
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

const CLOSED: Task = { ...TASK, id: 'nx-task-2', title: 'Livraison', status: 'done', next_action: null }
const FOLLOW_UP: Task = { ...TASK, id: 'nx-task-3', title: 'Correctif', follows: 'nx-task-2' }

function viewWith(tasks: Task[]) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) =>
    Response.json(String(url).endsWith('/api/tasks') ? tasks : []),
  ))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><WorkView /></QueryClientProvider>)
}

const paneOf = (title: string) => screen.findByRole('complementary', { name: `Détail de ${title}` })

test('une carte terminée s’ouvre d’un clic, sans « déplacer » dans son nom', async () => {
  viewWith([CLOSED])
  fireEvent.click(await screen.findByRole('button', { name: 'Livraison — ouvrir' }))
  expect(await paneOf('Livraison')).toBeInTheDocument()
})

test('« Ouvrir une tâche de suite » ouvre la création pour cette tâche ; « Nouvelle tâche » reste simple', async () => {
  viewWith([CLOSED])
  fireEvent.click(await screen.findByRole('button', { name: 'Livraison — ouvrir' }))
  const pane = await paneOf('Livraison')
  fireEvent.click(within(pane).getByRole('button', { name: 'Ouvrir une tâche de suite' }))

  let dialog = await screen.findByRole('dialog', { name: 'Nouvelle tâche' })
  expect(within(dialog).getByText('Suite de nx-task-2 — Livraison')).toBeInTheDocument()
  fireEvent.change(within(dialog).getByLabelText('Titre'), { target: { value: 'Brouillon de suite' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Annuler' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

  fireEvent.click(screen.getAllByRole('button', { name: 'Nouvelle tâche' })[0])
  dialog = await screen.findByRole('dialog', { name: 'Nouvelle tâche' })
  expect(within(dialog).queryByText(/Suite de/)).not.toBeInTheDocument()
  expect(within(dialog).getByLabelText('Titre')).toHaveValue('')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Annuler' }))

  fireEvent.click(within(pane).getByRole('button', { name: 'Ouvrir une tâche de suite' }))
  dialog = await screen.findByRole('dialog', { name: 'Nouvelle tâche' })
  expect(within(dialog).getByLabelText('Titre')).toHaveValue('Brouillon de suite')
})

test('suivre « Suite de » ou « Suivie par » quitte le panneau et son brouillon, comme un clic sur une carte', async () => {
  viewWith([CLOSED, FOLLOW_UP])
  fireEvent.click(await screen.findByRole('button', { name: /^Correctif — ouvrir/ }))
  let pane = await paneOf('Correctif')
  fireEvent.change(within(pane).getByLabelText('Titre'), { target: { value: 'Brouillon perdu' } })

  fireEvent.click(within(pane).getByRole('button', { name: /Suite de nx-task-2 — Livraison/ }))
  pane = await paneOf('Livraison')
  fireEvent.click(within(pane).getByRole('button', { name: /Correctif/ }))

  pane = await paneOf('Correctif')
  expect(within(pane).getByLabelText('Titre')).toHaveValue('Correctif')
})
