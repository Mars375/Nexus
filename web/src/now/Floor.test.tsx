import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import type { NodeState, NowSnapshot } from '@/api'
import { Floor } from './Floor'

const snap = (over: Partial<NowSnapshot> = {}): NowSnapshot => ({
  source: 'nexus.db', measured_at: new Date().toISOString(), operation: null, auxiliaries: [],
  agents: [
    { agent: 'helios', state: 'run', task: 'nx-task-31', title: 'Refonte du pont', run: 's', since: new Date(Date.now() - 42 * 60_000).toISOString() },
    { agent: 'mnema', state: 'idle', task: null, title: null, run: null, since: null },
    { agent: 'artemis', state: 'idle', task: null, title: null, run: null, since: null },
  ],
  asks: [], blocks: [], done: [], ...over,
})
const node = (id: string, status: NodeState['status']): NodeState => ({ id, kind: 'homelab', guardian_agent: 'aether', status, last_seen: null, detail: null, source: 'tailscale', measured_at: new Date().toISOString() })

test('chaque poste porte l\'état de son agent', () => {
  const { container } = render(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: 'nx-task-32', at: new Date().toISOString(), received_at: new Date().toISOString() }],
    blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: 'hors ligne', since: null, follow_up_at: null, lead_agent: 'artemis' }],
  })} nodes={[]} onOpenTask={() => {}} />)
  const desk = (a: string) => container.querySelector(`[data-agent="${a}"]`)!
  expect(desk('helios').getAttribute('data-run')).toBe('true')
  expect(desk('mnema').getAttribute('data-wait')).toBe('true')
  expect(desk('artemis').getAttribute('data-block')).toBe('true')
  expect(container.querySelector('[data-ticket="nx-evt-1"]')).not.toBeNull()
})

test('les étiquettes disent le nom, la tâche et la durée, sans survol', () => {
  render(<Floor snapshot={snap()} nodes={[]} onOpenTask={() => {}} />)
  expect(screen.getByText('HELIOS')).toBeInTheDocument()
  expect(screen.getByText('Refonte du pont')).toBeInTheDocument()
  expect(screen.getByText(/nx-task-31 · 42 min/)).toBeInTheDocument()
  expect(screen.getAllByText('inactif').length).toBeGreaterThan(0)
})

test('ta table dit quand aucune demande n\'est reçue', () => {
  render(<Floor snapshot={snap()} nodes={[]} onOpenTask={() => {}} />)
  expect(screen.getByText('aucune demande reçue (7 j)')).toBeInTheDocument()
})

test('les baies suivent les nœuds, jamais vertes sans preuve', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[node('helios', 'online'), node('synapse', 'unknown'), node('artemis', 'offline-by-design')]} onOpenTask={() => {}} />)
  expect(container.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('ok')
  expect(container.querySelector('[data-node="synapse"]')!.getAttribute('data-tone')).toBe('unknown')
  expect(screen.getByText('ARTEMIS · hors ligne, prévu')).toBeInTheDocument()
})

test('aucun mouvement au premier rendu', () => {
  const { container } = render(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString(), received_at: new Date().toISOString() }],
  })} nodes={[]} onOpenTask={() => {}} />)
  expect(container.querySelector('.is-fresh')).toBeNull()
})

test('une demande qui arrive déclenche le mouvement de son fil', () => {
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={[]} onOpenTask={() => {}} />)
  rerender(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-7', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString(), received_at: new Date().toISOString() }],
  })} nodes={[]} onOpenTask={() => {}} />)
  expect(container.querySelector('[data-route="mnema"].is-fresh')).not.toBeNull()
})

test('cliquer un poste qui a une tâche ouvre la tâche', () => {
  const open = vi.fn()
  render(<Floor snapshot={snap()} nodes={[]} onOpenTask={open} />)
  screen.getByRole('button', { name: /Helios.*Refonte du pont/ }).click()
  expect(open).toHaveBeenCalledWith('nx-task-31')
})

test('un titre trop long est tronqué dans l\'étiquette, le nom et la durée restent entiers', () => {
  const title = 'Refonte complète du pont entre Nexus et les agents de la salle des serveurs'
  render(<Floor snapshot={snap({ agents: [{ agent: 'helios', state: 'run', task: 'nx-task-31', title, run: 's', since: new Date(Date.now() - 42 * 60_000).toISOString() }] })} nodes={[]} onOpenTask={() => {}} />)
  expect(screen.getByText(title).className).toContain('truncate')
  expect(screen.getByText('HELIOS').className).not.toContain('truncate')
  expect(screen.getByText(/nx-task-31 · 42 min/).className).not.toContain('truncate')
})

test('l\'étiquette d\'un agent bloqué donne la tâche bloquée quand on la connaît', () => {
  render(<Floor snapshot={snap({
    blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: null, since: null, follow_up_at: null, lead_agent: 'artemis' }],
  })} nodes={[]} onOpenTask={() => {}} />)
  expect(screen.getByText('nx-task-29 · bloquée')).toBeInTheDocument()
})

test('un poste dont l\'agent est seulement bloqué ouvre la tâche bloquée', () => {
  const open = vi.fn()
  render(<Floor snapshot={snap({
    blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: null, since: null, follow_up_at: null, lead_agent: 'artemis' }],
  })} nodes={[]} onOpenTask={open} />)
  screen.getByRole('button', { name: /Artemis.*Sauvegarde/ }).click()
  expect(open).toHaveBeenCalledWith('nx-task-29')
})

test('chaque étiquette de poste porte data-label', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} onOpenTask={() => {}} />)
  expect([...container.querySelectorAll('[data-label]')].map((e) => e.getAttribute('data-label'))).toEqual(['helios', 'mnema', 'artemis'])
})

test('la légende des baies tient sur une ligne par nœud', () => {
  render(<Floor snapshot={snap()} nodes={[node('helios', 'online'), node('artemis', 'offline-by-design')]} onOpenTask={() => {}} />)
  expect(screen.getByText('HELIOS · en ligne')).toBeInTheDocument()
  expect(screen.getByText('ARTEMIS · hors ligne, prévu')).toBeInTheDocument()
})

test('nœuds pas encore lus : « lecture des nœuds… » et aucune baie', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={undefined} onOpenTask={() => {}} />)
  expect(screen.getByText('lecture des nœuds…')).toBeInTheDocument()
  expect(container.querySelector('[data-node]')).toBeNull()
})

test('nœuds périmés : baies inconnues et légende « périmée », jamais verte', () => {
  const old = new Date(Date.now() - 10 * 60_000).toISOString()
  const { container } = render(<Floor snapshot={snap()} nodes={[{ ...node('helios', 'online'), measured_at: old }, node('synapse', 'online')]} onOpenTask={() => {}} />)
  expect(container.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('unknown')
  expect(screen.getByText('HELIOS · périmée')).toBeInTheDocument()
  expect(container.querySelector('[data-node="synapse"]')!.getAttribute('data-tone')).toBe('ok')
})

test('relecture des nœuds en échec : toutes les baies sont inconnues et périmées', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[node('helios', 'online')]} nodesFailed onOpenTask={() => {}} />)
  expect(container.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('unknown')
  expect(screen.getByText('HELIOS · périmée')).toBeInTheDocument()
})

test('aucun texte de l\'étage sous 11 px', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[node('helios', 'online')]} onOpenTask={() => {}} />)
  expect(container.innerHTML).not.toMatch(/text-\[(\d|10)px\]/)
})
