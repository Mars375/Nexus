import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { NowSnapshot } from '@/api'
import { NowView } from './NowView'

const empty: NowSnapshot = {
  source: 'nexus.db', measured_at: new Date().toISOString(), operation: null, auxiliaries: [],
  agents: [{ agent: 'helios', state: 'idle', task: null, title: null, run: null, since: null }],
  asks: [], blocks: [], done: [],
}

function serve(now: NowSnapshot | 'fail') {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/api/nodes') return Response.json([])
    if (now === 'fail') return new Response('', { status: 500 })
    return Response.json(now)
  }))
}

function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><NowView /></QueryClientProvider>)
}

afterEach(() => vi.unstubAllGlobals())

test('sans données, chaque section dit ce qu\'elle ne contient pas', async () => {
  serve(empty); show()
  expect(await screen.findByText('Pas d\'opération principale en cours.')).toBeInTheDocument()
  expect(screen.getByText('Aucune demande reçue ces 7 derniers jours.')).toBeInTheDocument()
  expect(screen.getByText('Aucun blocage actif.')).toBeInTheDocument()
  expect(screen.getByText('Rien de terminé ces 7 derniers jours.')).toBeInTheDocument()
  expect(screen.getByText('Aucun agent ne travaille en ce moment.')).toBeInTheDocument()
  expect(screen.queryByText(/tout va bien/i)).toBeNull()
})

test('les tuiles ne sont que des comptes mesurés', async () => {
  serve({ ...empty,
    agents: [{ agent: 'helios', state: 'run', task: 'nx-task-1', title: 'T', run: 's', since: new Date().toISOString() }],
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString() }],
  }); show()
  expect(await screen.findByRole('group', { name: 'Agents actifs' })).toHaveTextContent('1')
  expect(screen.getByRole('group', { name: 'Demandes reçues' })).toHaveTextContent('1')
  expect(screen.getByRole('group', { name: 'Blocages' })).toHaveTextContent('0')
})

test('une demande reçue ne se dit jamais « en attente »', async () => {
  serve({ ...empty, asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: 'nx-task-32', at: new Date().toISOString() }] }); show()
  expect(await screen.findByText('Python ?')).toBeInTheDocument()
  expect(screen.getByText('Question de Mnema sur nx-task-32.')).toBeInTheDocument()
  expect(screen.queryByText(/en attente/i)).toBeNull()
})

test('serveur injoignable : on le dit, sans étage vide présenté comme calme', async () => {
  serve('fail'); show()
  expect(await screen.findByText(/Maintenant n'a pas pu être lu/)).toBeInTheDocument()
  expect(screen.queryByText('Aucun agent ne travaille en ce moment.')).toBeNull()
})

test('la liste des agents existe toujours pour les lecteurs d\'écran', async () => {
  serve(empty); show()
  expect(await screen.findByRole('list', { name: 'Agents' })).toBeInTheDocument()
})
