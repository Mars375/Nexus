import { fireEvent, render } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { NodeState } from '@/api'
import { Floor } from './Floor'
import { down, node, setupFloorTest, snap, twelve, up } from './floorSupport'

setupFloorTest()

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString()
const roomNodes = (): NodeState[] => [
  { ...node('cortex', 'online'), guardian_agent: 'mnema' },
  { ...node('synapse', 'offline'), guardian_agent: 'aether', last_seen: hoursAgo(3) },
  { ...node('artemis', 'offline-by-design'), guardian_agent: 'artemis', last_seen: hoursAgo(30) },
  { ...node('helios', 'unknown'), guardian_agent: 'helios', last_seen: hoursAgo(2) },
  { ...node('n5', 'online'), guardian_agent: 'claude' }, { ...node('n6', 'online'), guardian_agent: 'codex' }, { ...node('n7', 'unknown'), guardian_agent: 'orca', last_seen: null }, { ...node('n8', 'online'), guardian_agent: 'hermes' },
]
const rackLabelOf = (c: HTMLElement, id: string) => c.querySelector(`[data-rack-label="${id}"]`) as HTMLElement
const lines = (el: HTMLElement) => [...el.querySelectorAll('[data-line]')].map((e) => e.textContent)

test('salle des serveurs : un décor statique et sobre, quelques éléments SVG, rien d\'animé ni qui ressemble à une mesure', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up())
  const room = container.querySelector('svg[aria-label^="Étage 2"]')!
  const decor = [...room.querySelectorAll('*')].filter((e) => !e.closest('.rack'))
  expect(decor.length).toBeLessThanOrEqual(40)
  expect(room.querySelectorAll('.cooling')).toHaveLength(2) // one cooling unit at each end of the row
  expect(room.querySelector('.floor-marking')).not.toBeNull()
  expect(room.querySelectorAll('animate, animateTransform, circle, ellipse, [class*="led"]:not(.rack *)')).toHaveLength(0)
  expect(room.querySelectorAll('.cooling .led, .cooling .led-on, .cooling .led-ring')).toHaveLength(0)
})

test('étage 1 : pas d\'étiquettes de baies, la légende reste comme avant', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={roomNodes()} />)
  expect(container.querySelectorAll('[data-rack-label]')).toHaveLength(0)
  expect(container.querySelector('[data-legend]')!.className).not.toContain('sr-only')
  expect(container.querySelector('[data-legend-summary]')).toBeNull()
})

test('salle : chaque baie a son étiquette, nom, état français, « vu il y a » pour hors ligne et inconnu, gardien', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={roomNodes()} />)
  fireEvent.click(up())
  expect(lines(rackLabelOf(container, 'n5'))).toEqual(['N5', 'en ligne', 'gardien : Claude'])
  expect(lines(rackLabelOf(container, 'n6'))).toEqual(['N6', 'en ligne', 'gardien : Codex'])
  expect(lines(rackLabelOf(container, 'n7'))).toEqual(['N7', 'inconnu', 'gardien : Orca']) // unknown without last_seen: nothing invented
  expect(lines(rackLabelOf(container, 'n8')).slice(0, 2)).toEqual(['N8', 'en ligne'])
  fireEvent.click(down())
  expect(container.querySelectorAll('[data-rack-label]')).toHaveLength(0)
})

test('salle : hors ligne et inconnu avec last_seen, hors ligne prévu sans « vu »', () => {
  const nodes = roomNodes().map((n, i) => i < 4 ? { ...n, id: `m${i}` } : n)
  const { container } = render(<Floor snapshot={snap()} nodes={[...nodes.slice(4), ...nodes.slice(0, 4)]} />)
  fireEvent.click(up())
  expect(lines(rackLabelOf(container, 'm1'))).toEqual(['M1', 'hors ligne · vu il y a 3 h', 'gardien : Aether'])
  expect(lines(rackLabelOf(container, 'm3'))).toEqual(['M3', 'inconnu · vu il y a 2 h', 'gardien : Helios'])
  expect(lines(rackLabelOf(container, 'm2'))).toEqual(['M2', 'hors ligne, prévu', 'gardien : Artemis'])
})

test('salle : mesure périmée ou relecture en échec disent « périmée », jamais verts', () => {
  const old = new Date(Date.now() - 10 * 60_000).toISOString()
  const a = render(<Floor snapshot={snap()} nodes={roomNodes().map((n) => n.id === 'n5' ? { ...n, measured_at: old } : n)} />)
  fireEvent.click(up())
  expect(lines(rackLabelOf(a.container, 'n5'))).toEqual(['N5', 'périmée', 'gardien : Claude'])
  a.unmount()
  const b = render(<Floor snapshot={snap()} nodes={roomNodes()} nodesFailed />)
  fireEvent.click(up())
  for (const id of ['n5', 'n6', 'n7', 'n8']) expect(lines(rackLabelOf(b.container, id))[1]).toMatch(/^périmée/)
})

test('salle : les étiquettes visuelles sont aria-hidden, la légende complète reste pour les lecteurs d\'écran, un résumé « n / m en ligne » est visible', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={roomNodes()} />)
  fireEvent.click(up())
  for (const el of container.querySelectorAll('[data-rack-label]')) expect(el.closest('[aria-hidden="true"]')).not.toBeNull()
  const legend = container.querySelector('[data-legend]')!
  expect(legend.className).toContain('sr-only')
  expect([...legend.querySelectorAll('li')].map((li) => li.textContent)).toEqual(['N5 · en ligne · gardien : Claude', 'N6 · en ligne · gardien : Codex', 'N7 · inconnu · gardien : Orca', 'N8 · en ligne · gardien : Hermes'])
  const summary = container.querySelector('[data-legend-summary]') as HTMLElement
  expect(summary.textContent).toBe('3 / 4 en ligne')
  expect(summary.closest('[aria-hidden="true"]')).not.toBeNull()
})

test('salle : le résumé ne compte pas en ligne une baie périmée', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={roomNodes()} nodesFailed />)
  fireEvent.click(up())
  expect(container.querySelector('[data-legend-summary]')!.textContent).toBe('0 / 4 en ligne')
})

test('salle : sous 800 px seules les lignes 1 et 2 s\'affichent, la ligne 2 est tronquée', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={roomNodes()} />)
  fireEvent.click(up())
  const l = rackLabelOf(container, 'n5')
  const [name, state, guardian] = [...l.querySelectorAll('[data-line]')]
  expect(name.className).not.toContain('hidden')
  expect(state.className).toContain('truncate'); expect(state.className).not.toContain('hidden')
  expect(guardian.className).toContain('hidden'); expect(guardian.className).toContain('@min-[800px]:block')
})

test('salle : le nom prend la couleur du ton de la baie', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[...roomNodes().slice(4), ...roomNodes().slice(0, 4)]} />)
  fireEvent.click(up())
  const name = (id: string) => rackLabelOf(container, id).querySelector('[data-line]')!.className
  expect(name('synapse')).toContain('text-danger') // offline
  expect(name('helios')).toContain('text-attention') // unknown
  expect(name('artemis')).toContain('text-unknown') // offline by design: not a failure
  expect(name('cortex')).not.toMatch(/text-(danger|attention|unknown)/)
})

test('salle : la légende lue par les lecteurs d\'écran porte les mêmes lignes que l\'étiquette (« vu il y a », gardien)', () => {
  const nodes = [...roomNodes().slice(4), ...roomNodes().slice(0, 4)]
  const { container } = render(<Floor snapshot={snap()} nodes={nodes} />)
  fireEvent.click(up())
  const legend = [...container.querySelectorAll('[data-legend] li')].map((li) => li.textContent)
  expect(legend).toEqual([
    'CORTEX · en ligne · gardien : Mnema',
    'SYNAPSE · hors ligne · vu il y a 3 h · gardien : Aether',
    'ARTEMIS · hors ligne, prévu · gardien : Artemis',
    'HELIOS · inconnu · vu il y a 2 h · gardien : Helios',
  ])
  // same words as the visual label, line by line
  for (const id of ['synapse', 'helios']) {
    const label = lines(rackLabelOf(container, id))
    expect(legend.find((t) => t!.startsWith(id.toUpperCase()))).toBe(`${label[0]} · ${label[1]} · ${label[2]}`)
  }
})

test('salle : une dernière vue dans le futur (horloge décalée) n\'affiche pas « vu il y a »', () => {
  const skewed = [...roomNodes().slice(4), { ...roomNodes()[1], last_seen: new Date(Date.now() + 3_600_000).toISOString() }, ...roomNodes().slice(2, 4), roomNodes()[0]]
  const { container } = render(<Floor snapshot={snap()} nodes={skewed} />)
  fireEvent.click(up())
  expect(lines(rackLabelOf(container, 'synapse'))[1]).toBe('hors ligne')
  expect(container.querySelector('[data-legend]')!.textContent).not.toContain('vu il y a 0 s')
})
