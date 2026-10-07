import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import { clearToken, getToken, markUnlocked, setToken } from './auth'

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
