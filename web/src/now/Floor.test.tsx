import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { Floor } from './Floor'
import { approval } from './fixtures'
import { node, setupFloorTest, snap } from './floorSupport'

setupFloorTest()

test('chaque poste porte l\'état de son agent', () => {
  const { container } = render(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: 'nx-task-32', at: new Date().toISOString(), received_at: new Date().toISOString(), body: null, options: [], consequence: null, approval: approval() }],
    blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: 'hors ligne', since: null, follow_up_at: null, lead_agent: 'artemis' }],
  })} nodes={[]} />)
  const desk = (a: string) => container.querySelector(`[data-agent="${a}"]`)!
  expect(desk('helios').getAttribute('data-run')).toBe('true')
  expect(desk('mnema').getAttribute('data-wait')).toBe('true')
  expect(desk('artemis').getAttribute('data-block')).toBe('true')
  expect(container.querySelector('[data-ticket="nx-evt-1"]')).not.toBeNull()
})

test('les étiquettes disent le nom, la tâche et la durée, sans survol', () => {
  render(<Floor snapshot={snap()} nodes={[]} />)
  expect(screen.getByText('HELIOS')).toBeInTheDocument()
  expect(screen.getByText('Refonte du pont')).toBeInTheDocument()
  expect(screen.getByText(/nx-task-31 · 42 min/)).toBeInTheDocument()
  expect(screen.getAllByText('inactif').length).toBeGreaterThan(0)
})

test('la tâche est dans l\'étiquette à toutes les largeurs : une ligne tronquée sous 800 px, avec la durée au-delà', () => {
  render(<Floor snapshot={snap()} nodes={[]} />)
  const short = screen.getByText('nx-task-31')
  expect(short).toHaveClass('truncate')
  expect(short.className).toContain('@min-[800px]:hidden') // sous 800 px seulement
  const long = screen.getByText(/nx-task-31 · 42 min/)
  expect(long.className).toContain('hidden') // la durée reste réservée à 800 px et plus
  expect(long.className).toContain('@min-[800px]:block')
  expect(short.closest('[data-label]')).toBe(long.closest('[data-label]'))
})

test('ta table dit quand aucune demande n\'est reçue', () => {
  render(<Floor snapshot={snap()} nodes={[]} />)
  expect(screen.getByText('aucune demande en attente')).toBeInTheDocument()
})

test('les baies suivent les nœuds, jamais vertes sans preuve', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[node('helios', 'online'), node('synapse', 'unknown'), node('artemis', 'offline-by-design')]} />)
  expect(container.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('ok')
  expect(container.querySelector('[data-node="synapse"]')!.getAttribute('data-tone')).toBe('unknown')
  expect(screen.getByText('ARTEMIS · hors ligne, prévu')).toBeInTheDocument()
})

test('l\'étiquette d\'un poste est un vrai lien vers la tâche', () => {
  render(<Floor snapshot={snap()} nodes={[]} />)
  const a = screen.getByRole('link', { name: 'Helios, Refonte du pont : ouvrir la tâche' })
  expect(a.getAttribute('href')).toBe('#/travail/nx-task-31')
  expect(a.getAttribute('data-label')).toBe('helios')
})

test('un titre trop long est tronqué dans l\'étiquette, le nom et la durée restent entiers', () => {
  const title = 'Refonte complète du pont entre Nexus et les agents de la salle des serveurs'
  render(<Floor snapshot={snap({ agents: [{ agent: 'helios', state: 'run', task: 'nx-task-31', title, run: 's', since: new Date(Date.now() - 42 * 60_000).toISOString() }] })} nodes={[]} />)
  expect(screen.getByText(title).className).toContain('truncate')
  expect(screen.getByText('HELIOS').className).not.toContain('truncate')
  expect(screen.getByText(/nx-task-31 · 42 min/).className).not.toContain('truncate')
})

test('l\'étiquette d\'un agent bloqué donne la tâche bloquée quand on la connaît', () => {
  render(<Floor snapshot={snap({
    blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: null, since: null, follow_up_at: null, lead_agent: 'artemis' }],
  })} nodes={[]} />)
  expect(screen.getByText('nx-task-29 · bloquée')).toBeInTheDocument()
})

test('un poste dont l\'agent est seulement bloqué mène à la tâche bloquée', () => {
  render(<Floor snapshot={snap({
    blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: null, since: null, follow_up_at: null, lead_agent: 'artemis' }],
  })} nodes={[]} />)
  expect(screen.getByRole('link', { name: /Artemis.*Sauvegarde/ }).getAttribute('href')).toBe('#/travail/nx-task-29')
})

test('chaque étiquette de poste porte data-label', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  expect([...container.querySelectorAll('[data-label]')].map((e) => e.getAttribute('data-label'))).toEqual(['helios', 'mnema', 'artemis'])
})

test('la légende des baies tient sur une ligne par nœud', () => {
  render(<Floor snapshot={snap()} nodes={[node('helios', 'online'), node('artemis', 'offline-by-design')]} />)
  expect(screen.getByText('HELIOS · en ligne')).toBeInTheDocument()
  expect(screen.getByText('ARTEMIS · hors ligne, prévu')).toBeInTheDocument()
})

test('nœuds pas encore lus : « lecture des nœuds… » et aucune baie', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={undefined} />)
  expect(screen.getByText('lecture des nœuds…')).toBeInTheDocument()
  expect(container.querySelector('[data-node]')).toBeNull()
})

test('nœuds illisibles dès la première lecture : « nœuds illisibles », pas une attente sans fin', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={undefined} nodesFailed />)
  expect(screen.getByText('nœuds illisibles')).toBeInTheDocument()
  expect(screen.queryByText('lecture des nœuds…')).toBeNull()
  expect(container.querySelector('[data-node]')).toBeNull()
})

test('nœuds périmés : baies inconnues et légende « périmée », jamais verte', () => {
  const old = new Date(Date.now() - 10 * 60_000).toISOString()
  const { container } = render(<Floor snapshot={snap()} nodes={[{ ...node('helios', 'online'), measured_at: old }, node('synapse', 'online')]} />)
  expect(container.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('unknown')
  expect(screen.getByText('HELIOS · périmée')).toBeInTheDocument()
  expect(container.querySelector('[data-node="synapse"]')!.getAttribute('data-tone')).toBe('ok')
})

test('relecture des nœuds en échec : toutes les baies sont inconnues et périmées', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[node('helios', 'online')]} nodesFailed />)
  expect(container.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('unknown')
  expect(screen.getByText('HELIOS · périmée')).toBeInTheDocument()
})

test('aucun texte de l\'étage sous 11 px', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[node('helios', 'online')]} />)
  expect(container.innerHTML).not.toMatch(/text-\[(\d|10)px\]/)
})

test('« TA TABLE » et son compteur sont dans un coin HTML fixe, bas-gauche, hors du plan', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  const corner = container.querySelector('[data-table-corner]') as HTMLElement
  expect(corner.closest('svg')).toBeNull()
  expect(corner.className).toContain('bottom-0'); expect(corner.className).toContain('left-0')
  expect(corner.textContent).toContain('TA TABLE'); expect(corner.textContent).toContain('aucune demande en attente')
  expect(corner.querySelector('span')!.className).toContain('text-muted')
})

test('le coin de la table garde l\'ambre et le « +N sur la table » quand il y a des demandes', () => {
  const ask = (n: number) => ({ event: `nx-evt-${n}`, agent: 'mnema' as const, kind: 'question' as const, subject: 'Q', task: null, at: new Date().toISOString(), received_at: new Date().toISOString(), body: null, options: [], consequence: null, approval: approval() })
  const { container } = render(<Floor snapshot={snap({ asks: [ask(1), ask(2), ask(3), ask(4), ask(5)] })} nodes={[]} />)
  const corner = container.querySelector('[data-table-corner]') as HTMLElement
  expect(corner.querySelector('span')!.className).toContain('text-attention')
  expect(corner.textContent).toContain('5 demandes · +2 sur la table')
})

test('ta table et les postes ne comptent que les demandes en attente', () => {
  const treated = approval({ ref: 'nx-appr-2', status: 'approved', decided_by: 'loic', decided_at: new Date().toISOString() })
  const base = { body: null, options: [], consequence: null, kind: 'question' as const, subject: 'Q', task: null, at: new Date().toISOString(), received_at: new Date().toISOString() }
  const { container } = render(<Floor snapshot={snap({ asks: [
    { ...base, event: 'nx-evt-1', agent: 'mnema', approval: approval() },
    { ...base, event: 'nx-evt-2', agent: 'artemis', approval: treated },
    { ...base, event: 'nx-evt-3', agent: 'artemis', approval: null },
  ] })} nodes={[]} />)
  expect(container.querySelector('[data-ticket="nx-evt-1"]')).not.toBeNull()
  expect(container.querySelector('[data-ticket="nx-evt-2"]')).toBeNull()
  expect(container.querySelector('[data-ticket="nx-evt-3"]')).toBeNull()
  expect(container.querySelector('[data-agent="artemis"]')!.getAttribute('data-wait')).toBe('false')
  expect(container.querySelector('[data-route="artemis"]')).toBeNull()
  expect(container.querySelector('[data-table-corner]')!.textContent).toContain('1 demande')
})
