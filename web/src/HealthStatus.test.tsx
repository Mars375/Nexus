import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { HealthStatus as App } from './HealthStatus'

function renderApp() {
  // Aucun réglage par défaut ici : on teste les options réellement portées par App.
  const client = new QueryClient()
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
  return client
}

function healthy() {
  const measured = new Date().toISOString()
  return Response.json({
    version: '0.1.0',
    db: { status: 'ok', source: 'nexus.db', measured_at: measured },
    backup: { last_at: measured, count: 1, source: 'nexus.db/backups' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  onlineManager.setOnline(true)
})

test('affiche la base OK avec sa provenance', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => healthy()))

  renderApp()

  expect(await screen.findByText('Base OK')).toBeInTheDocument()
  expect(screen.getByText(/^source : nexus\.db · mesuré il y a/)).toBeInTheDocument()
})

test('dit unknown quand le serveur est injoignable', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 502 })))

  renderApp()

  expect(await screen.findByText('Serveur injoignable — état unknown')).toBeInTheDocument()
  expect(screen.getByText('aucun contrôle réussi pour le moment')).toBeInTheDocument()
})

test('garde la date du dernier contrôle réussi après une panne', async () => {
  const fetchMock = vi.fn(async () => healthy())
  vi.stubGlobal('fetch', fetchMock)
  const client = renderApp()
  await screen.findByText('Base OK')

  fetchMock.mockImplementation(async () => new Response(null, { status: 502 }))
  await client.refetchQueries({ queryKey: ['health'] })

  expect(await screen.findByText('Serveur injoignable — état unknown')).toBeInTheDocument()
  expect(screen.queryByText('Base OK')).not.toBeInTheDocument()
  expect(screen.getByText(/^dernier contrôle réussi — source : nexus\.db/)).toBeInTheDocument()
})

test('contrôle quand même si le navigateur se croit hors ligne', async () => {
  const fetchMock = vi.fn(async () => healthy())
  vi.stubGlobal('fetch', fetchMock)
  const client = renderApp()
  await screen.findByText('Base OK')

  onlineManager.setOnline(false)
  fetchMock.mockImplementation(async () => new Response(null, { status: 502 }))
  await client.refetchQueries({ queryKey: ['health'] })

  expect(await screen.findByText('Serveur injoignable — état unknown')).toBeInTheDocument()
})
