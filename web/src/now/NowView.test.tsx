import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { NodeState, NowSnapshot } from '@/api'
import { approval, ask } from './fixtures'
import { NowView } from './NowView'

const empty: NowSnapshot = {
  source: 'nexus.db', measured_at: new Date().toISOString(), operation: null, auxiliaries: [],
  agents: [{ agent: 'helios', state: 'idle', task: null, title: null, run: null, since: null }],
  asks: [], blocks: [], done: [],
}

const node = (id: string, status: NodeState['status'], measuredAt = new Date().toISOString()): NodeState => ({ id, kind: 'homelab', guardian_agent: 'aether', status, last_seen: null, detail: null, source: 'tailscale', measured_at: measuredAt })

function serve(now: NowSnapshot | 'fail', nodes: NodeState[] | 'fail' | 'pending' = []) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/api/nodes') {
      if (nodes === 'pending') return new Promise<Response>(() => {})
      return nodes === 'fail' ? new Response('', { status: 500 }) : Response.json(nodes)
    }
    if (now === 'fail') return new Response('', { status: 500 })
    return Response.json(now)
  }))
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><NowView /></QueryClientProvider>)
  return client
}

afterEach(() => vi.unstubAllGlobals())

test('sans données, chaque section dit ce qu\'elle ne contient pas', async () => {
  serve(empty); show()
  expect(await screen.findByText('Pas d\'opération principale en cours.')).toBeInTheDocument()
  expect(screen.getByText('Aucune demande en attente ni traitée récemment.')).toBeInTheDocument()
  expect(screen.getByText('Aucun blocage actif.')).toBeInTheDocument()
  expect(screen.getByText('Rien de terminé ces 7 derniers jours.')).toBeInTheDocument()
  expect(screen.getByText('Aucun agent ne travaille en ce moment.')).toBeInTheDocument()
  expect(screen.queryByText(/tout va bien/i)).toBeNull()
})

test('les tuiles ne sont que des comptes mesurés', async () => {
  serve({ ...empty,
    agents: [{ agent: 'helios', state: 'run', task: 'nx-task-1', title: 'T', run: 's', since: new Date().toISOString() }],
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString(), received_at: new Date().toISOString(), body: null, options: [], consequence: null, approval: approval() }],
  }); show()
  expect(await screen.findByRole('group', { name: 'Agents actifs' })).toHaveTextContent('1')
  expect(screen.getByRole('group', { name: 'Demandes reçues' })).toHaveTextContent('1')
  expect(screen.getByRole('group', { name: 'Blocages' })).toHaveTextContent('0')
})

test('une demande sans approbation ne se dit jamais « en attente »', async () => {
  serve({ ...empty, asks: [ask({ task: 'nx-task-32', approval: null })] }); show()
  expect(await screen.findByText('Python ?')).toBeInTheDocument()
  expect(screen.getByText(/Question de Mnema/)).toBeInTheDocument()
  expect(screen.getByText('suivi indisponible (demande antérieure)')).toBeInTheDocument()
  expect(document.querySelector('[data-chip="pending"]')).toBeNull()
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

test('sans agent au travail, la phrase n\'est pas réservée aux lecteurs d\'écran', async () => {
  serve(empty); show()
  const line = await screen.findByText('Aucun agent ne travaille en ce moment.')
  expect(line.closest('[class*="sr-only"]')).toBeNull()
})

test('une demande reçue liée à une tâche ouvre cette tâche', async () => {
  serve({ ...empty, asks: [ask({ task: 'nx-task-32' })] }); show()
  const link = await screen.findByRole('link', { name: 'nx-task-32' })
  expect(link).toHaveAttribute('href', '#/travail/nx-task-32')
})

test('une demande sans tâche n\'est pas un lien', async () => {
  serve({ ...empty, asks: [ask()] }); show()
  await screen.findByText('Python ?')
  expect(screen.queryByRole('link', { name: /nx-task/ })).toBeNull()
})

test('le lien d\'un agent vers sa tâche laisse le navigateur faire (ctrl-clic, clic molette)', async () => {
  serve({ ...empty, agents: [{ agent: 'helios', state: 'run', task: 'nx-task-1', title: 'Pont', run: 's', since: new Date().toISOString() }] }); show()
  const link = (await screen.findAllByRole('link', { name: 'Pont' }))[0]
  expect(link).toHaveAttribute('href', '#/travail/nx-task-1')
  expect(fireEvent.click(link, { ctrlKey: true })).toBe(true)
})

test('au premier chargement, les demandes déjà là ne passent pas pour des arrivées', async () => {
  serve({ ...empty, asks: [ask()] }); show()
  await screen.findByText('Python ?')
  expect(document.querySelector('.now-fresh')).toBeNull()
})

test('une demande qui arrive après le chargement est signalée', async () => {
  serve(empty); const client = show()
  await screen.findByText('Aucune demande en attente ni traitée récemment.')
  serve({ ...empty, asks: [ask()] })
  await act(() => client.refetchQueries({ queryKey: ['now'] }))
  await screen.findByText('Python ?')
  expect(document.querySelector('.now-fresh')).not.toBeNull()
})

test('après une relecture en échec, les dernières données restent et on le dit', async () => {
  serve({ ...empty, asks: [ask()] }); const client = show()
  await screen.findByText('Python ?')
  expect(screen.queryByText('dernière lecture réussie affichée')).toBeNull()
  serve('fail')
  await act(() => client.refetchQueries({ queryKey: ['now'] }))
  expect(await screen.findByText('dernière lecture réussie affichée')).toBeInTheDocument()
  expect(screen.getByText('Python ?')).toBeInTheDocument()
})

test('une durée de blocage inconnue se dit en français', async () => {
  serve({ ...empty, blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: null, since: null, follow_up_at: null, lead_agent: null }] }); show()
  expect(await screen.findByText('début inconnu')).toBeInTheDocument()
  expect(screen.queryByText(/depuis unknown/)).toBeNull()
})

test('la tuile « Agents actifs » n\'est turquoise que si un agent travaille', async () => {
  serve(empty); show()
  const tile = await screen.findByRole('group', { name: 'Agents actifs' })
  expect(tile.innerHTML).not.toContain('text-run')
})

test('tant que les nœuds ne sont pas lus, la salle des serveurs ne se présente pas calme', async () => {
  serve(empty, 'pending'); show()
  await screen.findByText('Pas d\'opération principale en cours.')
  expect(screen.getByText('lecture des nœuds…')).toBeInTheDocument()
  expect(document.querySelector('[data-node]')).toBeNull()
})

test('nœuds illisibles : on le dit, les baies connues passent en inconnu et « périmée »', async () => {
  serve(empty, [node('helios', 'online')]); const client = show()
  await waitFor(() => expect(document.querySelector('[data-node="helios"]')).not.toBeNull())
  expect(document.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('ok')
  serve(empty, 'fail')
  await act(() => client.refetchQueries({ queryKey: ['nodes'] }))
  await waitFor(() => expect(document.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('unknown'))
  expect(screen.getAllByText(/périmée/).length).toBeGreaterThan(0)
  expect(screen.getByRole('group', { name: 'Nœuds en ligne' })).toHaveTextContent('périmée')
})

test('une mesure de nœud trop ancienne n\'est jamais verte', async () => {
  const old = new Date(Date.now() - 10 * 60_000).toISOString()
  serve(empty, [node('helios', 'online', old)]); show()
  await waitFor(() => expect(document.querySelector('[data-node="helios"]')).not.toBeNull())
  expect(document.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('unknown')
  expect(screen.getByRole('group', { name: 'Nœuds en ligne' })).toHaveTextContent('périmée')
})
