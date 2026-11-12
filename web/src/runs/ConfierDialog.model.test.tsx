import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Task } from '@/api'
import { clearToken, markUnlocked } from '@/auth'
import type { ExecutorInfo, Run } from '@/runsApi'
import { RunsSection } from './RunsSection'

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }))

const TASK = { id: 'nx-task-1', title: 'Pont lecture', status: 'todo' } as Task
const T = '2026-11-11T10:00:00+01:00'
const RUN = {
  id: 'nx-run-1', task: 'nx-task-1', executor: 'claude', agent: 'claude', dispatched_by: 'loic',
  client_key: 'k', brief: 'b', workdir: null, model: 'sonnet', external_ref: null, status: 'dispatched',
  native_status: null, created_at: T, ended_at: null, cancel_requested_at: null, version: 1,
  source: 'nexus.db', measured_at: T,
} as Run
const base = { workdirs: ['F:/depot'], source: 'nexus.db', measured_at: T }
const CODEX: ExecutorInfo = { executor: 'codex', agents: ['codex'], models: [], ...base }
const CLAUDE: ExecutorInfo = { executor: 'claude', agents: ['claude'], models: ['haiku', 'sonnet', 'opus'], ...base }

type Call = { url: string; method: string; body: Record<string, unknown> | undefined }
type State = { executors: unknown[]; post?: () => Response }

/** A fake adapter behind `/api/executors`: the field only exists when an executor serves models. */
function serve(state: State) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, '')
      const method = init?.method ?? 'GET'
      calls.push({ url: path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (method === 'POST') return state.post?.() ?? new Response(JSON.stringify(RUN), { status: 201 })
      if (path.startsWith('/api/executors')) return new Response(JSON.stringify(state.executors))
      return new Response('[]')
    }),
  )
  return calls
}

async function open(state: State) {
  const calls = serve(state)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RunsSection task={TASK} />
    </QueryClientProvider>,
  )
  fireEvent.click(await screen.findByRole('button', { name: 'Confier à…' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByLabelText(/^Exécutant/)
  return { calls, dialog, client }
}

const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST')
const send = (dialog: HTMLElement) => fireEvent.click(within(dialog).getByRole('button', { name: 'Lancer l’agent' }))
const brief = (dialog: HTMLElement, text = 'Fais le travail') =>
  fireEvent.change(within(dialog).getByLabelText(/^Brief/), { target: { value: text } })
const options = (select: HTMLElement) => [...(select as HTMLSelectElement).options].map((o) => o.value)

beforeEach(() => {
  clearToken()
  markUnlocked()
})
afterEach(() => vi.unstubAllGlobals())

test('le champ Modèle apparaît pour Claude avec Sonnet présélectionné, et pas pour Codex', async () => {
  const { dialog } = await open({ executors: [CODEX, CLAUDE] })
  expect(within(dialog).queryByLabelText(/^Modèle/)).not.toBeInTheDocument() // Codex est le premier
  fireEvent.change(within(dialog).getByLabelText(/^Exécutant/), { target: { value: 'claude' } })
  const model = within(dialog).getByLabelText(/^Modèle/) as HTMLSelectElement
  expect(options(model)).toEqual(['haiku', 'sonnet', 'opus'])
  expect(model.value).toBe('sonnet')
  expect(model).toHaveTextContent('Haiku — rapide, le plus économe')
  expect(model).toHaveTextContent('Opus — le plus capable, consomme le plus')
  expect(within(dialog).getByText(/consomme l’abonnement Claude de Loïc/)).toBeInTheDocument()
})

test('changer d’exécutant masque le champ et oublie le choix', async () => {
  const { dialog } = await open({ executors: [CLAUDE, CODEX] })
  fireEvent.change(within(dialog).getByLabelText(/^Modèle/), { target: { value: 'opus' } })
  fireEvent.change(within(dialog).getByLabelText(/^Exécutant/), { target: { value: 'codex' } })
  expect(within(dialog).queryByLabelText(/^Modèle/)).not.toBeInTheDocument()
  expect(within(dialog).queryByText(/abonnement Claude/)).not.toBeInTheDocument()
  fireEvent.change(within(dialog).getByLabelText(/^Exécutant/), { target: { value: 'claude' } })
  expect((within(dialog).getByLabelText(/^Modèle/) as HTMLSelectElement).value).toBe('sonnet')
})

test('l’envoi porte le modèle choisi pour Claude', async () => {
  const { calls, dialog } = await open({ executors: [CLAUDE] })
  brief(dialog)
  fireEvent.change(within(dialog).getByLabelText(/^Modèle/), { target: { value: 'opus' } })
  send(dialog)
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0].body).toMatchObject({ executor: 'claude', agent: 'claude', model: 'opus' })
})

test('un exécutant sans modèles n’envoie pas de champ model', async () => {
  const { calls, dialog } = await open({ executors: [CODEX] })
  brief(dialog)
  send(dialog)
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0].body).not.toHaveProperty('model')
})

test('un mock d’exécutant sans `models` se lit comme une liste vide', async () => {
  const legacy: Record<string, unknown> = { ...CODEX }
  delete legacy.models
  const { calls, dialog } = await open({ executors: [legacy] })
  expect(within(dialog).queryByLabelText(/^Modèle/)).not.toBeInTheDocument()
  brief(dialog)
  send(dialog)
  await waitFor(() => expect(posts(calls)).toHaveLength(1))
  expect(posts(calls)[0].body).not.toHaveProperty('model')
})

test('changer de modèle après un refus change la clé, renvoyer tel quel la garde', async () => {
  const refusal = () =>
    new Response(JSON.stringify({ detail: { code: 'executor_busy', message: 's' } }), { status: 409 })
  const { calls, dialog } = await open({ executors: [CLAUDE], post: refusal })
  brief(dialog)
  send(dialog)
  await within(dialog).findByRole('alert')
  send(dialog)
  await waitFor(() => expect(posts(calls)).toHaveLength(2))
  fireEvent.change(within(dialog).getByLabelText(/^Modèle/), { target: { value: 'haiku' } })
  send(dialog)
  await waitFor(() => expect(posts(calls)).toHaveLength(3))
  const keys = posts(calls).map((c) => c.body?.client_key)
  expect(keys[0]).toBe(keys[1])
  expect(keys[2]).not.toBe(keys[1])
  expect(posts(calls).map((c) => c.body?.model)).toEqual(['sonnet', 'sonnet', 'haiku'])
})

test('un modèle retiré par le serveur reste visible, marqué, bloque l’envoi et garde le brief', async () => {
  const state = { executors: [CLAUDE] as ExecutorInfo[] }
  const { dialog, client } = await open(state)
  fireEvent.change(within(dialog).getByLabelText(/^Modèle/), { target: { value: 'opus' } })
  brief(dialog, 'Mon brief')

  state.executors = [{ ...CLAUDE, models: ['haiku', 'sonnet'] }]
  await act(() => client.invalidateQueries({ queryKey: ['executors'] }))

  expect(await within(dialog).findByText(/Opus — plus disponible/)).toBeInTheDocument()
  expect(within(dialog).getByRole('alert')).toHaveTextContent('Ce choix n’est plus proposé')
  expect((within(dialog).getByLabelText(/^Brief/) as HTMLTextAreaElement).value).toBe('Mon brief')
  expect(within(dialog).getByRole('button', { name: 'Lancer l’agent' })).toBeDisabled()
  fireEvent.change(within(dialog).getByLabelText(/^Modèle/), { target: { value: 'sonnet' } })
  expect(within(dialog).getByRole('button', { name: 'Lancer l’agent' })).not.toBeDisabled()
})

test.each([
  ['model_required', /Choisis un modèle/],
  ['model_unavailable', /n’est plus proposé par cet exécutant/],
  ['model_not_for_executor', /ne propose pas de choix de modèle/],
])('le refus %s est expliqué', async (code, expected) => {
  const refusal = () => new Response(JSON.stringify({ detail: { code, message: 's' } }), { status: 409 })
  const { dialog } = await open({ executors: [CLAUDE], post: refusal })
  brief(dialog)
  send(dialog)
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(expected)
})

test('le modèle affiché par défaut ne change pas en silence quand la liste se réduit', async () => {
  const state = { executors: [CLAUDE] as ExecutorInfo[] }
  const { dialog, client } = await open(state)
  expect((within(dialog).getByLabelText(/^Modèle/) as HTMLSelectElement).value).toBe('sonnet')
  brief(dialog, 'Mon brief')

  state.executors = [{ ...CLAUDE, models: ['opus'] }]
  await act(() => client.invalidateQueries({ queryKey: ['executors'] }))

  expect(await within(dialog).findByText(/Sonnet — plus disponible/)).toBeInTheDocument()
  expect((within(dialog).getByLabelText(/^Modèle/) as HTMLSelectElement).value).toBe('sonnet')
  expect(within(dialog).getByRole('button', { name: 'Lancer l’agent' })).toBeDisabled()
  expect((within(dialog).getByLabelText(/^Brief/) as HTMLTextAreaElement).value).toBe('Mon brief')
})
