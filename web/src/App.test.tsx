import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

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
