import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Task } from '@/api'
import { clearToken, markLocked, markUnlocked } from '@/auth'
import type { ExecutorInfo, Run } from '@/runsApi'
import { RunsSection } from './RunsSection'

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }))

const TASK = { id: 'nx-task-1', title: 'Pont lecture', status: 'todo' } as Task
const T = '2026-11-05T10:00:00+01:00'

const RUN: Run = {
  id: 'nx-run-1', task: 'nx-task-1', executor: 'codex', agent: 'codex', dispatched_by: 'loic',
  client_key: 'k', brief: 'b', workdir: null, external_ref: 'nexus/nx-run-1', status: 'running',
  native_status: 'exited', created_at: T, ended_at: null, cancel_requested_at: null, version: 1,
  source: 'nexus.db', measured_at: T,
}
const CODEX: ExecutorInfo = { executor: 'codex', agents: ['codex'], workdirs: ['F:/depot'], source: 'nexus.db', measured_at: T }
const HERMES: ExecutorInfo = { executor: 'hermes', agents: ['helios', 'mnema'], workdirs: [], source: 'nexus.db', measured_at: T }

type Routes = { runs?: Run[] | 'error'; executors?: ExecutorInfo[]; events?: unknown[]; post?: Response }

function serve(routes: Routes) {
  const calls: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, '')
      const method = init?.method ?? 'GET'
      calls.push({ url: path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (method === 'POST') return routes.post ?? new Response(JSON.stringify(RUN), { status: 201 })
      if (path.startsWith('/api/executors')) return new Response(JSON.stringify(routes.executors ?? []))
      if (path.startsWith('/api/events')) return new Response(JSON.stringify(routes.events ?? []))
      if (routes.runs === 'error') return new Response('boom', { status: 500 })
      return new Response(JSON.stringify(routes.runs ?? []))
    }),
  )
  return calls
}

function mount(task: Task = TASK) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree = (t: Task) => (
    <QueryClientProvider client={client}>
      <RunsSection task={t} />
    </QueryClientProvider>
  )
  const view = render(tree(task))
  return { client, setTask: (t: Task) => view.rerender(tree(t)) }
}

beforeEach(() => {
  clearToken()
  markUnlocked()
})
afterEach(() => vi.unstubAllGlobals())

test('sans run : l’état vide le dit', async () => {
  serve({ runs: [] })
  mount()
  expect(await screen.findByText(/Aucun run : rien n’a été confié/)).toBeInTheDocument()
})

test('chargement puis erreur de lecture lisibles', async () => {
  serve({ runs: 'error' })
  mount()
  expect(screen.getByText('Chargement des runs…')).toBeInTheDocument()
  expect(await screen.findByRole('alert')).toHaveTextContent('Impossible de lire les runs')
})

test('un run montre statut, couple, branche, statut brut de l’exécutant et preuve', async () => {
  serve({
    runs: [{ ...RUN, status: 'done', ended_at: T }],
    events: [{ run: 'nx-run-1', evidence: ['commit:abc123'] }, { run: 'nx-run-1', evidence: ['commit:abc123'] }],
  })
  mount()
  const row = (await screen.findByText('Terminé')).closest('li') as HTMLElement
  expect(row).toHaveTextContent('Codex → Codex')
  expect(row).toHaveTextContent('Branche : nexus/nx-run-1')
  expect(row).toHaveTextContent('Statut de l’exécutant : exited')
  await waitFor(() => expect(within(row).getAllByText('commit:abc123')).toHaveLength(1))
})

test('annuler demande confirmation puis appelle la route', async () => {
  const calls = serve({ runs: [RUN] })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Annuler le run nx-run-1' }))
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('Annuler le run nx-run-1 ?')
  expect(calls.some((c) => c.url.endsWith('/cancel'))).toBe(false) // rien avant la confirmation
  fireEvent.click(within(dialog).getByRole('button', { name: 'Annuler le run' }))
  await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/runs/nx-run-1/cancel')).toBe(true))
})

test('annulation demandée : le dit et n’offre plus d’annuler', async () => {
  serve({ runs: [{ ...RUN, cancel_requested_at: T }] })
  mount()
  expect(await screen.findByText(/Annulation demandée le/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Annuler le run/ })).not.toBeInTheDocument()
})

test('un run terminé ne s’annule pas', async () => {
  serve({ runs: [{ ...RUN, status: 'failed', ended_at: T }] })
  mount()
  await screen.findByText('Échoué')
  expect(screen.queryByRole('button', { name: /Annuler le run/ })).not.toBeInTheDocument()
})

test('sur une tâche terminée, pas de « Confier à »', async () => {
  serve({ runs: [] })
  mount({ ...TASK, status: 'done' })
  await screen.findByText(/Aucun run/)
  expect(screen.queryByRole('button', { name: 'Confier à…' })).not.toBeInTheDocument()
})

async function openDialog(routes: Routes) {
  const calls = serve(routes)
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Confier à…' }))
  return { calls, dialog: await screen.findByRole('dialog') }
}

test('le dialogue dit que cela lance un LLM, avant toute confirmation', async () => {
  const { dialog } = await openDialog({ executors: [CODEX] })
  expect(await within(dialog).findByText(/Lance un LLM/)).toBeInTheDocument()
})

test('sans exécutant configuré : message clair, rien à envoyer', async () => {
  const { dialog } = await openDialog({ executors: [] })
  expect(await within(dialog).findByText(/Aucun exécutant n’est configuré/)).toBeInTheDocument()
  expect(within(dialog).getByRole('button', { name: 'Lancer l’agent' })).toBeDisabled()
})

test('les agents proposés suivent l’exécutant choisi, le brief est obligatoire', async () => {
  const { dialog } = await openDialog({ executors: [CODEX, HERMES] })
  const submit = await within(dialog).findByRole('button', { name: 'Lancer l’agent' })
  expect(submit).toBeDisabled() // pas de brief
  const agent = within(dialog).getByLabelText(/^Agent/) as HTMLSelectElement
  expect([...agent.options].map((o) => o.value)).toEqual(['codex'])
  fireEvent.change(within(dialog).getByLabelText(/^Exécutant/), { target: { value: 'hermes' } })
  expect([...(within(dialog).getByLabelText(/^Agent/) as HTMLSelectElement).options].map((o) => o.value)).toEqual(['helios', 'mnema'])
  expect(within(dialog).queryByLabelText(/^Dossier de travail/)).not.toBeInTheDocument() // Hermes : aucun dépôt
  fireEvent.change(within(dialog).getByLabelText(/^Brief/), { target: { value: '   ' } })
  expect(submit).toBeDisabled()
})

test('envoie exécutant, agent, dossier, brief et une clé ; un second clic reste une seule demande', async () => {
  const { calls, dialog } = await openDialog({ executors: [CODEX] })
  fireEvent.change(await within(dialog).findByLabelText(/^Brief/), { target: { value: ' Fais le travail ' } })
  const submit = within(dialog).getByRole('button', { name: 'Lancer l’agent' })
  fireEvent.click(submit)
  fireEvent.click(submit)
  await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBeGreaterThan(0))
  const posts = calls.filter((c) => c.method === 'POST')
  expect(posts[0].url).toBe('/api/tasks/nx-task-1/runs')
  expect(posts[0].body).toMatchObject({ executor: 'codex', agent: 'codex', workdir: 'F:/depot', brief: 'Fais le travail' })
  expect(new Set(posts.map((p) => (p.body as { client_key: string }).client_key)).size).toBe(1)
})

test('un 409 reste lisible dans le dialogue, le brief saisi est gardé, une modification change la clé', async () => {
  const refusal = new Response(JSON.stringify({ detail: { code: 'executor_busy', message: 'serveur' } }), { status: 409 })
  const { calls, dialog } = await openDialog({ executors: [CODEX], post: refusal })
  const brief = await within(dialog).findByLabelText(/^Brief/)
  fireEvent.change(brief, { target: { value: 'Premier brief' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Lancer l’agent' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Cet exécutant a déjà un run actif')
  expect((brief as HTMLTextAreaElement).value).toBe('Premier brief')

  fireEvent.change(brief, { target: { value: 'Brief corrigé' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Lancer l’agent' }))
  await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(2))
  const keys = calls.filter((c) => c.method === 'POST').map((c) => (c.body as { client_key: string }).client_key)
  expect(keys[0]).not.toBe(keys[1])
})

test.each([
  ['executor_unavailable', /n’est pas configuré sur ce serveur/],
  ['run_already_active', /Cet agent a déjà un run actif sur cette tâche/],
  ['agent_not_for_executor', /ne travaille pas pour cet agent/],
  ['task_done', /Cette tâche est terminée/],
  ['transition_refused', /Cette tâche a été abandonnée/],
  ['concurrent_update', /vient d’être modifiée ailleurs/],
])('le refus %s est expliqué', async (code, expected) => {
  const refusal = new Response(JSON.stringify({ detail: { code, message: 'serveur' } }), { status: 409 })
  const { dialog } = await openDialog({ executors: [CODEX], post: refusal })
  fireEvent.change(await within(dialog).findByLabelText(/^Brief/), { target: { value: 'b' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Lancer l’agent' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(expected)
})


test('un 401 à l’envoi ne laisse pas son refus affiché une fois le jeton ressaisi', async () => {
  const refusal = new Response(JSON.stringify({ detail: { code: 'invalid_token', message: 'jeton refusé' } }), { status: 401 })
  const { dialog } = await openDialog({ executors: [CODEX], post: refusal })
  fireEvent.change(await within(dialog).findByLabelText(/^Brief/), { target: { value: 'Mon brief' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Lancer l’agent' }))
  act(() => markLocked('invalid_token'))
  act(() => markUnlocked())
  const field = (await screen.findByLabelText(/^Brief/)) as HTMLTextAreaElement
  expect(field.value).toBe('Mon brief') // le brouillon survit
  await waitFor(() => expect(screen.queryByText(/jeton/i)).toBeNull())
})

test('modifier un champ efface le refus précédent', async () => {
  const refusal = new Response(JSON.stringify({ detail: { code: 'executor_busy', message: 'serveur' } }), { status: 409 })
  const { dialog } = await openDialog({ executors: [CODEX], post: refusal })
  const brief = await within(dialog).findByLabelText(/^Brief/)
  fireEvent.change(brief, { target: { value: 'b' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Lancer l’agent' }))
  await within(dialog).findByRole('alert')
  fireEvent.change(brief, { target: { value: 'b2' } })
  expect(within(dialog).queryByRole('alert')).toBeNull()
})

test('la tâche terminée pendant que le dialogue est ouvert : il le dit et n’envoie plus', async () => {
  serve({ runs: [], executors: [CODEX] })
  const { setTask } = mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Confier à…' }))
  const dialog = await screen.findByRole('dialog')
  fireEvent.change(await within(dialog).findByLabelText(/^Brief/), { target: { value: 'b' } })
  setTask({ ...TASK, status: 'done' })
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('vient d’être terminée')
  expect(within(dialog).getByRole('button', { name: 'Lancer l’agent' })).toBeDisabled()
})

test('un choix que le serveur ne propose plus reste visible, marqué, et bloque l’envoi', async () => {
  const state = { executors: [CODEX, HERMES] }
  const calls = serve({ runs: [] })
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '')
    calls.push({ url: path, method: init?.method ?? 'GET', body: undefined })
    if (path.startsWith('/api/executors')) return new Response(JSON.stringify(state.executors))
    return new Response('[]')
  })
  const { client } = mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Confier à…' }))
  const dialog = await screen.findByRole('dialog')
  fireEvent.change(await within(dialog).findByLabelText(/^Exécutant/), { target: { value: 'hermes' } })
  fireEvent.change(within(dialog).getByLabelText(/^Brief/), { target: { value: 'Pour Mnēma' } })

  state.executors = [CODEX] // Hermes disparaît pendant la saisie
  await act(() => client.invalidateQueries({ queryKey: ['executors'] }))

  expect(await within(dialog).findByText(/Hermes — plus disponible/)).toBeInTheDocument()
  expect(within(dialog).getByRole('alert')).toHaveTextContent('Ce choix n’est plus proposé')
  expect((within(dialog).getByLabelText(/^Brief/) as HTMLTextAreaElement).value).toBe('Pour Mnēma')
  expect(within(dialog).getByRole('button', { name: 'Lancer l’agent' })).toBeDisabled()
  fireEvent.change(within(dialog).getByLabelText(/^Exécutant/), { target: { value: 'codex' } })
  expect(within(dialog).getByRole('button', { name: 'Lancer l’agent' })).not.toBeDisabled()
})

test('le run terminé pendant la confirmation d’annulation : le dialogue le dit, la confirmation est bloquée', async () => {
  serve({ runs: [RUN] })
  const { client } = mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Annuler le run nx-run-1' }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByRole('button', { name: 'Annuler le run' })).not.toBeDisabled()
  vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify([{ ...RUN, status: 'done', ended_at: T }])))
  await act(() => client.invalidateQueries({ queryKey: ['tasks', 'nx-task-1', 'runs'] }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Ce run a changé depuis')
  expect(within(dialog).getByRole('button', { name: 'Annuler le run' })).toBeDisabled()
})

test('l’échec de lecture des preuves est dit, et la provenance reste affichée', async () => {
  serve({ runs: [{ ...RUN, status: 'done', ended_at: T }] })
  vi.mocked(fetch).mockImplementation(async (url) =>
    String(url).includes('/api/events') ? new Response('boom', { status: 500 }) : new Response(JSON.stringify([{ ...RUN, status: 'done', ended_at: T }])),
  )
  mount()
  expect(await screen.findByText(/Les preuves des runs n’ont pas pu être lues/)).toBeInTheDocument()
  expect(screen.getByText(/source : nexus\.db/)).toBeInTheDocument()
})
