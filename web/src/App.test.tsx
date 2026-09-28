import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

test('affiche la base OK avec sa provenance', async () => {
  const measured = new Date().toISOString()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json({
        version: '0.1.0',
        db: { status: 'ok', source: 'nexus.db', measured_at: measured },
        backup: { last_at: measured, count: 1, source: 'nexus.db/backups' },
      }),
    ),
  )

  renderApp()

  expect(await screen.findByText('Base OK')).toBeInTheDocument()
  expect(screen.getByText(/source : nexus\.db · mesuré il y a/)).toBeInTheDocument()
})

test('dit unknown quand le serveur est injoignable', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 502 })))

  renderApp()

  expect(await screen.findByText('Serveur injoignable — état unknown')).toBeInTheDocument()
})
