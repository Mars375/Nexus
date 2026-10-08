import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import type { Task } from '@/api'
import { clearToken, getToken, markLocked, markUnlocked, setToken } from './auth'

afterEach(() => {
  vi.unstubAllGlobals()
  window.location.hash = ''
})

function renderApp(hash: string) {
  window.location.hash = hash
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
  vi.stubGlobal('fetch',vi.fn(async () => new Response('[]', { status: 200, headers: { 'content-type': 'application/json' } })))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><App /></QueryClientProvider>)
}

const current = () => screen.getByRole('link', { current: 'page' }).textContent

test('sans hash, la page d\'accueil est Maintenant', () => {
  renderApp('')
  expect(current()).toBe('Maintenant')
})

test('un hash inconnu mène aussi à Maintenant', () => {
  renderApp('#/nimporte-quoi')
  expect(current()).toBe('Maintenant')
})

test('#/travail et #/travail/<tâche> ouvrent Travail', () => {
  renderApp('#/travail/nx-task-31')
  expect(current()).toBe('Travail')
})

// --- Jeton d'acteur (ADR-020) ----------------------------------------------------------------

const TOKEN = 'nxt_' + 'A'.repeat(43)

const jsonResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

const HEALTH = {
  version: 'test',
  db: { status: 'ok', source: 'nexus.db', measured_at: new Date().toISOString() },
  backup: { last_at: null, count: 0, source: 'backups', measured_at: new Date().toISOString() },
}

/** An API that wants the right token: 401 without it, `[]` with it. */
function stubGuardedApi() {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/health') return jsonResponse(200, HEALTH)
    const auth = new Headers(init?.headers).get('Authorization')
    if (auth === `Bearer ${TOKEN}`) return jsonResponse(200, [])
    return jsonResponse(401, { detail: { code: auth ? 'invalid_token' : 'auth_required', message: 'refus' } })
  }))
}

function renderGuarded() {
  window.location.hash = '#/travail'
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><App /></QueryClientProvider>)
}

beforeEach(() => {
  clearToken()
  markUnlocked()
})

test("sans jeton et sans 401, l'application marche comme avant : ni écran verrouillé ni bouton d'oubli", async () => {
  renderApp('#/travail')
  expect(await screen.findByRole('heading', { name: 'Travail' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Nexus verrouillé' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Oublier le jeton' })).toBeNull()
})

test("un 401 de l'API affiche l'écran verrouillé, puis le bon jeton rend l'application", async () => {
  stubGuardedApi()
  renderGuarded()

  expect(await screen.findByRole('heading', { name: 'Nexus verrouillé' })).toBeInTheDocument()
  expect(screen.queryByRole('navigation', { name: 'Vues' })).toBeNull()

  fireEvent.change(screen.getByLabelText('Jeton d’accès'), { target: { value: TOKEN } })
  fireEvent.click(screen.getByRole('button', { name: 'Déverrouiller' }))

  expect(await screen.findByRole('navigation', { name: 'Vues' })).toBeInTheDocument()
  expect(await screen.findByRole('heading', { name: 'Travail' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Nexus verrouillé' })).toBeNull()
  expect(document.body.textContent).not.toContain(TOKEN)
})

test('un jeton refusé par le serveur est oublié et ramène à l\'écran verrouillé', async () => {
  stubGuardedApi()
  setToken('nxt_' + 'B'.repeat(43))
  renderGuarded()

  expect(await screen.findByRole('heading', { name: 'Nexus verrouillé' })).toBeInTheDocument()
  expect(await screen.findByRole('status')).toHaveTextContent(/refusé le jeton/)
  expect(getToken()).toBeNull()
})

test('« Oublier le jeton » efface le jeton depuis l\'application', async () => {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
  vi.stubGlobal('fetch', vi.fn(async (url: string) => jsonResponse(200, url === '/api/health' ? HEALTH : [])))
  setToken(TOKEN)
  renderGuarded()

  fireEvent.click(await screen.findByRole('button', { name: 'Oublier le jeton' }))

  expect(getToken()).toBeNull()
  expect(screen.queryByRole('button', { name: 'Oublier le jeton' })).toBeNull()
  expect(screen.getByRole('navigation', { name: 'Vues' })).toBeInTheDocument()
})

test('un 401 pendant une modification garde l’application montée : le brouillon survit au déverrouillage', async () => {
  const task: Task = {
    id: 'nx-task-1', title: 'Pont lecture', objective: 'Lire les runs', status: 'todo', human_owner: 'loic',
    lead_agent: null, collaborators: [], next_action: 'relever les tables', due_at: null, follow_up_at: null,
    block_cause: null, block_plan: null, drop_reason: null, expected_evidence: null, evidence: [],
    priority: 'normal', operation_role: null, origin: null, context: [], depends_on: [], created_by: 'loic',
    created_at: '2026-09-28T10:00:00+02:00', updated_at: '2026-09-28T10:00:00+02:00',
    source: 'nexus.db', measured_at: '2026-09-28T10:00:00+02:00',
  }
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/health') return jsonResponse(200, HEALTH)
    if (init?.method === 'PATCH') return jsonResponse(401, { detail: { code: 'invalid_token', message: 'refus' } })
    if (url === '/api/tasks') return jsonResponse(200, [task])
    return jsonResponse(200, [])
  }))
  setToken(TOKEN)
  window.location.hash = '#/travail/nx-task-1'
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><App /></QueryClientProvider>)

  const title = await screen.findByLabelText('Titre')
  fireEvent.change(title, { target: { value: 'Pont lecture — brouillon' } })
  fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }))

  const lock = await screen.findByRole('heading', { name: 'Nexus verrouillé' })
  expect(lock).toBeInTheDocument()
  const nav = screen.getByRole('navigation', { name: 'Vues', hidden: true })
  const app = nav.closest('[inert]')
  expect(app).not.toBeNull()
  expect(app).toHaveAttribute('aria-hidden', 'true')
  expect(screen.queryByRole('navigation', { name: 'Vues' })).toBeNull() // hidden from the accessibility tree
  await waitFor(() => expect(screen.getByLabelText('Jeton d’accès')).toHaveFocus())

  fireEvent.change(screen.getByLabelText('Jeton d’accès'), { target: { value: TOKEN } })
  fireEvent.click(screen.getByRole('button', { name: 'Déverrouiller' }))

  expect(screen.queryByRole('heading', { name: 'Nexus verrouillé' })).toBeNull()
  expect(document.querySelector('[inert]')).toBeNull()
  expect(screen.getByLabelText('Titre')).toHaveValue('Pont lecture — brouillon')
})

test('un jeton stocké par un autre onglet déverrouille et fait relire les données', async () => {
  stubGuardedApi()
  renderGuarded()
  expect(await screen.findByRole('heading', { name: 'Nexus verrouillé' })).toBeInTheDocument()

  act(() => {
    window.localStorage.setItem('nexus.token', TOKEN)
    window.dispatchEvent(new StorageEvent('storage', { key: 'nexus.token', newValue: TOKEN }))
  })

  expect(await screen.findByRole('heading', { name: 'Travail' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Nexus verrouillé' })).toBeNull()
})

test('après le déverrouillage, le focus revient où il était avant le verrouillage', async () => {
  stubGuardedApi()
  setToken(TOKEN)
  renderGuarded()
  await screen.findByRole('heading', { name: 'Travail' })
  const link = screen.getByRole('link', { name: 'Travail' })
  link.focus()

  act(() => markLocked('invalid_token'))
  expect(await screen.findByLabelText('Jeton d’accès')).toHaveFocus()
  act(() => markUnlocked())

  await waitFor(() => expect(link).toHaveFocus())
})
