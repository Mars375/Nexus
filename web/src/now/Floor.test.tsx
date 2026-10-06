import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { NodeState, NowSnapshot } from '@/api'
import { Floor, FloorScene } from './Floor'
import { resetFloorRotation } from './useFloorRotation'
import { resetFloorLevel } from './useFloorLevel'
import { drawOrder, layoutFloor, toPercent } from './iso'

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
  expect(screen.getByText('aucune demande reçue (7 j)')).toBeInTheDocument()
})

test('les baies suivent les nœuds, jamais vertes sans preuve', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[node('helios', 'online'), node('synapse', 'unknown'), node('artemis', 'offline-by-design')]} />)
  expect(container.querySelector('[data-node="helios"]')!.getAttribute('data-tone')).toBe('ok')
  expect(container.querySelector('[data-node="synapse"]')!.getAttribute('data-tone')).toBe('unknown')
  expect(screen.getByText('ARTEMIS · hors ligne, prévu')).toBeInTheDocument()
})

test('aucun mouvement au premier rendu', () => {
  const { container } = render(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString(), received_at: new Date().toISOString() }],
  })} nodes={[]} />)
  expect(container.querySelector('.is-fresh')).toBeNull()
})

test('une demande qui arrive déclenche le mouvement de son fil', () => {
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={[]} />)
  rerender(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-7', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString(), received_at: new Date().toISOString() }],
  })} nodes={[]} />)
  expect(container.querySelector('[data-route="mnema"].is-fresh')).not.toBeNull()
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

const QUARTERS = [0, 90, 180, 270]
const scene = (angle: number, nodes: NodeState[] = [node('helios', 'online'), node('synapse', 'unknown'), node('artemis', 'offline-by-design')]) =>
  render(<FloorScene snapshot={snap()} nodes={nodes} angle={angle} />).container

test('l\'écran d\'un poste n\'est dessiné que s\'il fait face au spectateur', () => {
  const screens = (a: number) => scene(a).querySelectorAll('.desk .screen').length
  expect(screens(0)).toBe(3)
  expect(screens(90)).toBe(0)
  expect(screens(180)).toBe(0)
  expect(screens(270)).toBe(3)
})

test('le dos du moniteur reste dessiné quand l\'écran est caché', () => {
  const c = scene(180)
  expect(c.querySelector('.desk .screen')).toBeNull()
  for (const desk of c.querySelectorAll('.desk')) expect(desk.querySelectorAll('.f-left, .f-right').length).toBeGreaterThanOrEqual(4) // bureau + moniteur
})

test('les LED d\'une baie sont sur une face visible, la face +x de préférence', () => {
  const face = { 0: '+x', 90: '+x', 180: '-x', 270: '-x' } as const
  for (const a of QUARTERS) {
    const c = scene(a)
    const l = layoutFloor(3, 3, a)
    for (const rack of c.querySelectorAll('.rack')) {
      const leds = [...rack.querySelectorAll('.led')]
      expect(leds).toHaveLength(5)
      for (const led of leds) {
        const dir = led.getAttribute('data-face') as '+x'
        expect(dir, `à ${a}°`).toBe(face[a as keyof typeof face])
        const [nx, ny] = { '+x': [1, 0], '-x': [-1, 0], '+y': [0, 1], '-y': [0, -1] }[dir]
        expect(l.sees(nx, ny)).toBe(true)
      }
    }
  }
})

test('les hachures et les LED sont des calques toujours présents : seul l\'état du poste ou de la baie change', () => {
  const blocks: NowSnapshot['blocks'] = [{ task: 'nx-task-29', title: 'Sauvegarde', cause: 'hors ligne', since: null, follow_up_at: null, lead_agent: 'artemis' }]
  const { container } = render(<Floor snapshot={snap({ blocks })} nodes={[node('helios', 'online'), node('synapse', 'unknown'), node('artemis', 'offline-by-design')]} />)
  for (const desk of container.querySelectorAll('g.desk')) expect(desk.querySelectorAll('polygon.desk-hatch'), desk.getAttribute('data-agent')!).toHaveLength(1)
  expect(container.querySelector('[data-agent="artemis"]')!.getAttribute('data-block')).toBe('true')
  expect(container.querySelector('[data-agent="helios"]')!.getAttribute('data-block')).toBe('false')
  for (const rack of container.querySelectorAll('g.rack')) {
    expect(rack.querySelectorAll('.led-on'), rack.getAttribute('data-node')!).toHaveLength(5)
    expect(rack.querySelectorAll('.led-ring'), rack.getAttribute('data-node')!).toHaveLength(5)
  }
})

test('aucune LED visible n\'est cachée par une autre baie ni par le chemin de câbles, à chaque quart de tour, étage par étage (jusqu\'à 12 nœuds)', () => {
  type P = [number, number]
  const parse = (pts: string): P[] => pts.split(' ').map((q) => q.split(',').map(Number) as P)
  const inside = ([x, y]: P, poly: P[]) => { // point strictly inside a convex polygon (any winding)
    let sign = 0
    for (let i = 0; i < poly.length; i++) {
      const [ax, ay] = poly[i], [bx, by] = poly[(i + 1) % poly.length]
      const c = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
      if (Math.abs(c) < 1e-6) continue
      if (sign === 0) sign = Math.sign(c); else if (Math.sign(c) !== sign) return false
    }
    return sign !== 0
  }
  for (const count of [10, 12]) for (let floor = 1; floor <= Math.ceil(count / 4); floor++) for (const a of QUARTERS) {
    const nodes = Array.from({ length: count }, (_, i) => node(`n${i}`, 'online'))
    const c = render(<FloorScene snapshot={snap()} nodes={nodes} angle={a} floor={floor} floorCount={Math.ceil(count / 4)} />).container
    const racks = [...c.querySelectorAll('g.rack')]
    expect(racks).toHaveLength(Math.min(4, count - (floor - 1) * 4))
    // drawn after the racks it could hide: a rack's LEDs may only be covered by later racks or the tray
    const tray = [...c.querySelectorAll('.cable-tray polygon')]
    racks.forEach((rack, i) => {
      for (const led of rack.querySelectorAll('.led')) for (const pt of parse(led.getAttribute('points')!)) {
        for (const later of racks.slice(i + 1)) for (const face of later.querySelectorAll('polygon:not(.led):not(.led-on):not(.led-ring)')) {
          expect(inside(pt, parse(face.getAttribute('points')!)), `${count} nœuds, étage ${floor} à ${a}° : une LED de ${rack.getAttribute('data-node')} est cachée par ${later.getAttribute('data-node')}`).toBe(false)
        }
        for (const face of tray) expect(inside(pt, parse(face.getAttribute('points')!)), `${count} nœuds, étage ${floor} à ${a}° : une LED de ${rack.getAttribute('data-node')} est sous le chemin de câbles`).toBe(false)
      }
    })
  }
})

test('postes, baies et table sont dessinés du fond vers l\'avant, à chaque quart de tour', () => {
  for (const a of QUARTERS) {
    const { container } = render(<FloorScene snapshot={snap()} nodes={[node('helios', 'online'), node('synapse', 'unknown'), node('artemis', 'offline-by-design')]} angle={a} />)
    const dom = [...container.querySelectorAll('g.desk, g.rack, g.dais')].map((g) => g.getAttribute('data-agent') ?? g.getAttribute('data-node') ?? 'table')
    const seats = ['helios', 'mnema', 'artemis'], racks = ['helios', 'synapse', 'artemis']
    const want = drawOrder(layoutFloor(3, 3, a)).map((o) => o.kind === 'seat' ? seats[o.index] : o.kind === 'rack' ? racks[o.index] : 'table')
    // `helios` et `artemis` existent comme poste et comme baie : on compare le genre aussi
    const kinds = [...container.querySelectorAll('g.desk, g.rack, g.dais')].map((g) => g.classList[0])
    const wantKinds = drawOrder(layoutFloor(3, 3, a)).map((o) => o.kind === 'seat' ? 'desk' : o.kind === 'rack' ? 'rack' : 'dais')
    expect(dom, `à ${a}°`).toEqual(want)
    expect(kinds).toEqual(wantKinds)
  }
})

test('chaque étiquette de poste est du côté que lui donne l\'angle (au-dessus ou en dessous), avec son trait de rappel', () => {
  for (const a of QUARTERS) {
    const { container } = render(<FloorScene snapshot={snap()} nodes={[]} angle={a} />)
    const l = layoutFloor(3, 0, a)
    const agents = ['helios', 'mnema', 'artemis']
    agents.forEach((agent, i) => {
      const lab = l.labels[i], from = lab.anchor
      const [left, top] = toPercent(l, [lab.x, lab.y])
      const el = container.querySelector(`[data-label="${agent}"]`) as HTMLElement
      expect(el.className, agent).toContain(lab.below ? 'translate-y-0' : '-translate-y-full')
      expect(parseFloat(el.style.left)).toBeCloseTo(left, 3)
      expect(parseFloat(el.style.top)).toBeCloseTo(top, 3)
      const leader = container.querySelectorAll('path.leader')[i]
      expect(leader.getAttribute('d')).toBe(`M${from} L${lab.x} ${lab.y}`)
    })
  }
})

test('un trait de rappel par poste, aucun pour les baies', () => {
  expect(scene(0).querySelectorAll('path.leader')).toHaveLength(3)
})

test('la légende des baies est un coin HTML fixe : une pastille au ton de la baie et son texte', () => {
  for (const a of [0, 135]) {
    const c = scene(a)
    const legend = c.querySelector('[data-legend]') as HTMLElement
    expect(legend.closest('svg')).toBeNull()
    expect(legend.className).toContain('bottom-0'); expect(legend.className).toContain('right-0')
    const rows = [...legend.querySelectorAll('li')]
    expect(rows.map((r) => r.textContent)).toEqual(['HELIOS · en ligne', 'SYNAPSE · inconnu', 'ARTEMIS · hors ligne, prévu'])
    expect(rows.map((r) => r.querySelector('[data-tone]')?.getAttribute('data-tone'))).toEqual(['ok', 'unknown', 'off'])
    expect(rows.map((r) => r.querySelector('[data-tone]')?.getAttribute('data-tone'))).toEqual(['helios', 'synapse', 'artemis'].map((id) => c.querySelector(`[data-node="${id}"]`)!.getAttribute('data-tone')))
  }
})

test('pendant la lecture des nœuds, le message prend la place de la légende', () => {
  const { container } = render(<FloorScene snapshot={snap()} nodes={undefined} nodesFailed angle={90} />)
  expect(container.querySelector('[data-legend]')!.textContent).toBe('nœuds illisibles')
})

test('le sol garde ses trois faces visibles à chaque quart de tour', () => {
  for (const a of QUARTERS) {
    const c = scene(a)
    expect(c.querySelectorAll('.floor-top')).toHaveLength(1)
    expect(c.querySelectorAll('.floor-left, .floor-right')).toHaveLength(2)
  }
})

// --- Rotation : boutons, clavier, glisser (#30)
class TestPointerEvent extends MouseEvent {
  pointerId: number
  constructor(type: string, init: PointerEventInit = {}) { super(type, init); this.pointerId = init.pointerId ?? 1 }
}
const stageOf = (c: HTMLElement) => c.querySelector('[data-stage]') as HTMLElement
const screens = (c: HTMLElement) => c.querySelectorAll('.desk .screen').length

beforeEach(() => { resetFloorRotation(); resetFloorLevel(); vi.stubGlobal('PointerEvent', TestPointerEvent); vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q })) })
afterEach(() => { vi.unstubAllGlobals() })

test('la scène est focalisable et porte un nom accessible', () => {
  render(<Floor snapshot={snap()} nodes={[]} />)
  const stage = screen.getByRole('group', { name: /pivoter/i })
  expect(stage.getAttribute('tabindex')).toBe('0')
  expect(stage.hasAttribute('data-stage')).toBe(true)
})

test('deux vrais boutons font tourner l\'étage d\'un quart de tour', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  const left = screen.getByRole('button', { name: 'Tourner l\'étage vers la gauche' })
  const right = screen.getByRole('button', { name: 'Tourner l\'étage vers la droite' })
  expect(left.tagName).toBe('BUTTON'); expect(left.getAttribute('type')).toBe('button')
  expect(screens(container)).toBe(3) // 0°
  fireEvent.click(right) // mouvement réduit : immédiat → 90°, écrans cachés
  expect(screens(container)).toBe(0)
  fireEvent.click(left)
  expect(screens(container)).toBe(3)
})

test('flèches gauche et droite tournent l\'étage, et reviennent', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  fireEvent.keyDown(stageOf(container), { key: 'ArrowRight' })
  expect(screens(container)).toBe(0)
  fireEvent.keyDown(stageOf(container), { key: 'ArrowLeft' })
  expect(screens(container)).toBe(3)
})

test('glisser fait pivoter puis cale sur un quart de tour', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  const stage = stageOf(container)
  fireEvent.pointerDown(stage, { clientX: 0, button: 0 })
  fireEvent.pointerMove(stage, { clientX: 100 }) // 40°
  fireEvent.pointerUp(stage, { clientX: 100 })
  expect(screens(container)).toBe(3) // 40° → 0°
  fireEvent.pointerDown(stage, { clientX: 0, button: 0 })
  fireEvent.pointerMove(stage, { clientX: 200 }) // 80°
  fireEvent.pointerUp(stage, { clientX: 200 })
  expect(screens(container)).toBe(0) // → 90°
})

test('un clic sur une étiquette après un glisser n\'ouvre pas la tâche, un clic simple oui', async () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  const link = screen.getByRole('link', { name: /Helios/ })
  const stage = stageOf(container)
  const clicked = vi.fn((e: Event) => e.preventDefault())
  link.addEventListener('click', clicked)
  fireEvent.pointerDown(link, { clientX: 0, button: 0 })
  fireEvent.pointerMove(link, { clientX: 120 })
  fireEvent.pointerUp(link, { clientX: 120 })
  fireEvent.click(link)
  expect(clicked).not.toHaveBeenCalled()
  await act(async () => { await new Promise((r) => setTimeout(r, 5)) })
  fireEvent.pointerDown(stage, { clientX: 0, button: 0 })
  fireEvent.pointerUp(stage, { clientX: 0 })
  fireEvent.click(link)
  expect(clicked).toHaveBeenCalledTimes(1)
})

test('l\'angle survit au remontage de la vue', () => {
  const first = render(<Floor snapshot={snap()} nodes={[]} />)
  fireEvent.click(screen.getByRole('button', { name: /vers la droite/ }))
  first.unmount()
  const second = render(<Floor snapshot={snap()} nodes={[]} />)
  expect(screens(second.container)).toBe(0)
})

test('la scène expose son angle courant', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  expect(stageOf(container).getAttribute('data-angle')).toBe('0')
  fireEvent.click(screen.getByRole('button', { name: /vers la gauche/ }))
  expect(stageOf(container).getAttribute('data-angle')).toBe('-90')
})

test('« TA TABLE » et son compteur sont dans un coin HTML fixe, bas-gauche, hors du plan', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  const corner = container.querySelector('[data-table-corner]') as HTMLElement
  expect(corner.closest('svg')).toBeNull()
  expect(corner.className).toContain('bottom-0'); expect(corner.className).toContain('left-0')
  expect(corner.textContent).toContain('TA TABLE'); expect(corner.textContent).toContain('aucune demande reçue (7 j)')
  expect(corner.querySelector('span')!.className).toContain('text-muted')
})

test('le coin de la table garde l\'ambre et le « +N sur la table » quand il y a des demandes', () => {
  const ask = (n: number) => ({ event: `nx-evt-${n}`, agent: 'mnema' as const, kind: 'question' as const, subject: 'Q', task: null, at: new Date().toISOString(), received_at: new Date().toISOString() })
  const { container } = render(<Floor snapshot={snap({ asks: [ask(1), ask(2), ask(3), ask(4), ask(5)] })} nodes={[]} />)
  const corner = container.querySelector('[data-table-corner]') as HTMLElement
  expect(corner.querySelector('span')!.className).toContain('text-attention')
  expect(corner.textContent).toContain('5 demandes · +2 sur la table')
})

test('les liens des étiquettes ne se laissent pas glisser par le navigateur', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  for (const a of container.querySelectorAll('a[data-label]')) expect(a.getAttribute('draggable')).toBe('false')
  const notCancelled = fireEvent.dragStart(screen.getByRole('link', { name: /Helios/ }))
  expect(notCancelled).toBe(false) // dragstart annulé : le glisser reste un glisser de pointeur
})

// --- Étages de baies (#36)
const twelve = (over: Record<string, NodeState['status']> = {}) => ['cortex', 'synapse', 'artemis', 'helios', 'n5', 'n6', 'n7', 'n8', 'n9', 'n10', 'n11', 'n12'].map((id) => node(id, over[id] ?? 'online'))
const pickLabel = () => document.querySelector('[data-floor-label]')?.textContent
const up = () => screen.getByRole('button', { name: /^Monter d'un étage/ })
const down = () => screen.getByRole('button', { name: /^Descendre d'un étage/ })
const pip = (c: HTMLElement, side: 'up' | 'down') => c.querySelector(`.floor-pip[data-side="${side}"]`)

test('jusqu\'à 4 nœuds : pas de sélecteur d\'étage, l\'étage 1 est le bureau', () => {
  for (const n of [0, 1, 4]) {
    const { container, unmount } = render(<Floor snapshot={snap()} nodes={twelve().slice(0, n)} />)
    expect(screen.queryByRole('button', { name: /^Monter d'un étage/ })).toBeNull()
    expect(container.querySelector('[data-floor-count]')!.getAttribute('data-floor-count')).toBe('1')
    expect(container.querySelectorAll('.desk')).toHaveLength(3)
    unmount()
  }
})

test('à 12 nœuds : ▲ ▼ nommés, « Étage 1 / 3 », ▼ désactivé en bas', () => {
  render(<Floor snapshot={snap()} nodes={twelve()} />)
  expect(pickLabel()).toBe('Étage 1 / 3')
  expect(up()).not.toHaveAttribute('aria-disabled'); expect(down()).toHaveAttribute('aria-disabled', 'true'); expect(down()).not.toBeDisabled()
  expect(document.querySelector('[data-floor-label]')!.getAttribute('aria-live')).toBe('polite')
})

test('▲ affiche l\'étage 2 : quatre baies, aucun poste ni table, la table reste dans son coin, légende des nœuds de l\'étage', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up())
  expect(pickLabel()).toBe('Étage 2 / 3')
  expect([...container.querySelectorAll('g.rack')].map((r) => r.getAttribute('data-node'))).toEqual(expect.arrayContaining(['n5', 'n6', 'n7', 'n8']))
  expect(container.querySelectorAll('g.rack')).toHaveLength(4)
  expect(container.querySelectorAll('.desk')).toHaveLength(0)
  expect(container.querySelectorAll('g.dais')).toHaveLength(0)
  expect(container.querySelectorAll('[data-label]')).toHaveLength(0)
  expect(screen.getByText('TA TABLE')).toBeInTheDocument() // a request does not vanish because we look at the racks
  expect([...container.querySelectorAll('[data-legend] li')].map((li) => li.textContent)).toEqual(['N5 · en ligne · gardien : Aether', 'N6 · en ligne · gardien : Aether', 'N7 · en ligne · gardien : Aether', 'N8 · en ligne · gardien : Aether'])
  expect(container.querySelector('[data-stage]')!.getAttribute('data-floor')).toBe('2')
  expect(screen.getByRole('img', { name: 'Étage 2 de Nexus : salle des serveurs, 4 baies' })).toBeInTheDocument()
})

test('la dernière salle peut être incomplète : 12 nœuds donnent 4, 10 nœuds donnent 2 baies à l\'étage 3', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve().slice(0, 10)} />)
  fireEvent.click(up()); fireEvent.click(up())
  expect(pickLabel()).toBe('Étage 3 / 3')
  expect(container.querySelectorAll('g.rack')).toHaveLength(2)
  expect(screen.getByRole('img', { name: 'Étage 3 de Nexus : salle des serveurs, 2 baies' })).toBeInTheDocument()
  expect(up()).toHaveAttribute('aria-disabled', 'true')
})

test('l\'ordre reçu fixe les étages : ni l\'id ni le statut ne déplacent un nœud', () => {
  const received = ['zeta', 'alpha', 'mid', 'omega', 'beta']
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={received.map((id) => node(id, 'online'))} />)
  expect([...container.querySelectorAll('g.rack')].map((r) => r.getAttribute('data-node'))).toEqual(['zeta', 'alpha', 'mid', 'omega'])
  rerender(<Floor snapshot={snap()} nodes={received.map((id) => node(id, id === 'zeta' ? 'offline' : 'unknown'))} />)
  expect([...container.querySelectorAll('g.rack')].map((r) => r.getAttribute('data-node'))).toEqual(['zeta', 'alpha', 'mid', 'omega'])
})

test('changer d\'étage garde l\'angle de la vue', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(screen.getByRole('button', { name: /vers la droite/ }))
  expect(stageOf(container).getAttribute('data-angle')).toBe('90')
  fireEvent.click(up())
  expect(stageOf(container).getAttribute('data-angle')).toBe('90')
  fireEvent.click(down())
  expect(stageOf(container).getAttribute('data-angle')).toBe('90')
})

test('data-floor-dir est absent au premier rendu, puis up, puis down', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  expect(stageOf(container).hasAttribute('data-floor-dir')).toBe(false)
  fireEvent.click(up())
  expect(stageOf(container).getAttribute('data-floor-dir')).toBe('up')
  fireEvent.click(down())
  expect(stageOf(container).getAttribute('data-floor-dir')).toBe('down')
})

test('PageUp et PageDown changent d\'étage sur la scène, les flèches tournent toujours', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  const stage = stageOf(container)
  expect(fireEvent.keyDown(stage, { key: 'PageUp' })).toBe(false) // preventDefault: the page does not scroll
  expect(stage.getAttribute('data-floor')).toBe('2')
  fireEvent.keyDown(stage, { key: 'PageUp' }); fireEvent.keyDown(stage, { key: 'PageUp' })
  expect(stage.getAttribute('data-floor')).toBe('3')
  fireEvent.keyDown(stage, { key: 'PageDown' })
  expect(stage.getAttribute('data-floor')).toBe('2')
  fireEvent.keyDown(stage, { key: 'ArrowRight' })
  expect(stage.getAttribute('data-angle')).toBe('90')
  expect(stage.getAttribute('data-floor')).toBe('2')
  expect(fireEvent.keyDown(stage, { key: 'PageUp', shiftKey: true })).toBe(true) // modifiers left to the browser
})

test('un nœud hors ligne à l\'étage 3 : pastille rouge sur ▲, texte dans le nom du bouton et dans l\'étiquette', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />)
  expect(pip(container, 'up')!.getAttribute('data-alert')).toBe('off')
  expect(pip(container, 'down')).toBeNull()
  expect(up()).toHaveAccessibleName('Monter d\'un étage : un nœud hors ligne à l\'étage 3')
  expect(down()).toHaveAccessibleName('Descendre d\'un étage')
  expect(pickLabel()).toBe('Étage 1 / 3 · alerte : étage 3')
  expect(container.querySelector('[data-floor-marker]')).toBeNull() // the column of dots is gone
})

test('pastille sur ▼ pour un étage en dessous, la plus grave l\'emporte, aucune pour l\'étage affiché', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve({ cortex: 'unknown', n10: 'offline' })} />)
  expect(pip(container, 'up')!.getAttribute('data-alert')).toBe('off')
  fireEvent.click(up()); fireEvent.click(up()) // floor 3 holds the offline node: it is the floor shown
  expect(pip(container, 'up')).toBeNull()
  expect(pip(container, 'down')!.getAttribute('data-alert')).toBe('unknown')
  expect(down()).toHaveAccessibleName('Descendre d\'un étage : un nœud en état inconnu à l\'étage 1')
  expect(pickLabel()).toBe('Étage 3 / 3 · alerte : étage 1')
})

test('plusieurs étages en alerte : les deux textes, « alerte aux étages 1 et 3 »', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve({ n6: 'unknown', n10: 'offline' })} />)
  fireEvent.click(up())
  expect(pickLabel()).toBe('Étage 2 / 3 · alerte : étage 3') // the displayed floor 2 holds the unknown node
  fireEvent.click(down())
  expect(pickLabel()).toBe('Étage 1 / 3 · alerte : étages 2, 3')
  expect(up()).toHaveAccessibleName('Monter d\'un étage : un nœud en état inconnu à l\'étage 2, un nœud hors ligne à l\'étage 3')
  expect(pip(container, 'up')!.getAttribute('data-alert')).toBe('off')
})

test('un nœud inconnu, périmé ou une relecture en échec donne l\'ambre ; hors ligne prévu ne donne rien', () => {
  const old = new Date(Date.now() - 10 * 60_000).toISOString()
  const a = render(<Floor snapshot={snap()} nodes={twelve({ n6: 'unknown' })} />)
  expect(pip(a.container, 'up')!.getAttribute('data-alert')).toBe('unknown')
  a.unmount()
  const b = render(<Floor snapshot={snap()} nodes={twelve().map((n) => n.id === 'n11' ? { ...n, measured_at: old } : n)} />)
  expect(pip(b.container, 'up')!.getAttribute('data-alert')).toBe('unknown')
  b.unmount()
  const c = render(<Floor snapshot={snap()} nodes={twelve()} nodesFailed />)
  expect(pip(c.container, 'up')!.getAttribute('data-alert')).toBe('unknown') // amber everywhere: floors 2 and 3 are above
  expect(pickLabel()).toBe('Étage 1 / 3 · alerte : étages 2, 3')
  c.unmount()
  const d = render(<Floor snapshot={snap()} nodes={twelve({ artemis: 'offline-by-design' })} />)
  expect(pip(d.container, 'up')).toBeNull(); expect(pickLabel()).toBe('Étage 1 / 3')
  fireEvent.click(up()); fireEvent.click(down())
  expect(d.container.querySelector('[data-node="artemis"]')!.getAttribute('data-tone')).toBe('off') // its rack stays shown, off
})

test('moins de nœuds qu\'avant : l\'étage disparu laisse la place au dernier, sans erreur', () => {
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up())
  rerender(<Floor snapshot={snap()} nodes={twelve().slice(0, 6)} />)
  expect(pickLabel()).toBe('Étage 2 / 2')
  expect(container.querySelectorAll('g.rack')).toHaveLength(2)
})

// --- Mouvement (#36): une réaction ponctuelle, jamais une boucle
const motion = () => vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q }))
const animated = (c: HTMLElement) => c.querySelectorAll('[data-arriving], [data-role="leaving"], [data-from], .is-fresh, [data-roll]')

test('aucun attribut ni classe d\'animation au premier rendu, même avec 12 nœuds et une alerte', () => {
  motion()
  const { container } = render(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />)
  expect(animated(container)).toHaveLength(0)
})

test('arriver sur une salle : data-arriving sur sa couche, --i sur ses baies, la couche de départ est marquée', () => {
  motion()
  vi.useFakeTimers()
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up())
  const layers = [...container.querySelectorAll('.level')]
  expect(layers.map((e) => [e.getAttribute('data-level'), e.getAttribute('data-role')])).toEqual([['1', 'leaving'], ['2', 'current']])
  const room = container.querySelector('.level[data-level="2"]')!
  expect(room.hasAttribute('data-arriving')).toBe(true)
  expect(room.getAttribute('data-from')).toBe('above')
  expect([...room.querySelectorAll('g.rack')].map((r) => (r as unknown as SVGElement).style.getPropertyValue('--i'))).toEqual(expect.arrayContaining(['0', '1', '2', '3']))
  const leaving = container.querySelector('.level[data-level="1"]')!
  expect(leaving.hasAttribute('inert')).toBe(true); expect(leaving.getAttribute('aria-hidden')).toBe('true')
  expect(leaving.getAttribute('data-from')).toBe('above')
  act(() => { vi.advanceTimersByTime(600) })
  expect(container.querySelectorAll('.level')).toHaveLength(1)
  expect(container.querySelector('[data-arriving]')).toBeNull()
  vi.useRealTimers()
})

test('le numéro d\'étage roule une fois, dans le sens du mouvement', () => {
  motion()
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  expect(container.querySelector('[data-roll]')).toBeNull()
  fireEvent.click(up())
  expect(container.querySelector('[data-roll]')!.getAttribute('data-roll')).toBe('up')
  fireEvent.click(down())
  expect(container.querySelector('[data-roll]')!.getAttribute('data-roll')).toBe('down')
})

test('une alerte qui apparaît sur un autre étage fait pulser la pastille du côté concerné, jamais pour l\'étage affiché', () => {
  motion()
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  expect(container.querySelector('.is-fresh')).toBeNull()
  rerender(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />)
  expect(pip(container, 'up')!.classList.contains('is-fresh')).toBe(true)
  expect(container.querySelectorAll('.is-fresh')).toHaveLength(1)
})

test('une alerte NOUVELLE sur l\'étage affiché n\'a ni pastille, ni texte d\'étiquette, ni nom de bouton, ni pulsation', () => {
  motion()
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up()) // floor 3, no alert there yet
  rerender(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />) // a brand new alert appears on the floor shown
  expect(pickLabel()).toBe('Étage 3 / 3')
  expect(pip(container, 'up')).toBeNull(); expect(pip(container, 'down')).toBeNull()
  expect(down()).toHaveAccessibleName('Descendre d\'un étage')
  expect(container.querySelector('.is-fresh')).toBeNull()
  fireEvent.click(down()); fireEvent.click(down()) // leave it: now it is out of sight and counts
  expect(pickLabel()).toBe('Étage 1 / 3 · alerte : étage 3')
})

test('mouvement réduit : ni couche qui part, ni data-arriving, ni is-fresh, ni numéro qui roule', () => {
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />) // beforeEach: reduced motion
  fireEvent.click(up())
  expect(container.querySelectorAll('.level')).toHaveLength(1)
  rerender(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />)
  expect(container.querySelectorAll('[data-arriving], [data-role="leaving"], .is-fresh, [data-roll]')).toHaveLength(0)
})

test('au dernier étage, ▲ garde le focus (aria-disabled, pas disabled) et PageDown fonctionne toujours', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up())
  up().focus()
  expect(up()).toHaveFocus()
  fireEvent.click(up()) // at the limit: ignored
  expect(up()).toHaveFocus()
  expect(stageOf(container).getAttribute('data-floor')).toBe('3')
  fireEvent.keyDown(stageOf(container), { key: 'PageUp' })
  expect(stageOf(container).getAttribute('data-floor')).toBe('3')
  fireEvent.keyDown(stageOf(container), { key: 'PageDown' })
  expect(stageOf(container).getAttribute('data-floor')).toBe('2')
})

test('repli quand l\'étage disparaît après un mouvement : instantané, sans numéro qui roule ni couche qui glisse', () => {
  motion()
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up())
  rerender(<Floor snapshot={snap()} nodes={twelve().slice(0, 6)} />)
  expect(pickLabel()).toBe('Étage 2 / 2')
  expect(container.querySelectorAll('[data-roll], [data-from], [data-arriving], [data-role="leaving"]')).toHaveLength(0)
  expect(container.querySelectorAll('.level')).toHaveLength(1)
})

test('aller-retour rapide 1 → 2 → 1 : les couches gardent leur ordre dans le DOM, aucune n\'est détachée puis rattachée', () => {
  motion()
  vi.useFakeTimers()
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  const stage = container.querySelector('.levels')!
  const office = container.querySelector('.level[data-level="1"]')
  const watch = new MutationObserver(() => {}); watch.observe(stage, { childList: true })
  fireEvent.click(up())
  expect([...container.querySelectorAll('.level')].map((e) => e.getAttribute('data-level'))).toEqual(['1', '2'])
  fireEvent.click(down())
  expect([...container.querySelectorAll('.level')].map((e) => e.getAttribute('data-level'))).toEqual(['1', '2'])
  expect(container.querySelector('.level[data-level="1"]')).toBe(office)
  expect(container.querySelector('.level[data-level="1"]')!.getAttribute('data-role')).toBe('current')
  // a node moved by insertBefore shows up as removed and re-added
  expect(watch.takeRecords().flatMap((r) => [...r.removedNodes]).filter((n) => n === office)).toHaveLength(0)
  watch.disconnect()
  vi.useRealTimers()
})

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

// --- Étiquettes des baies sur les salles (#36) : des données réelles seulement
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

test('plusieurs nœuds en alerte sur un étage : le nombre est dit, au pluriel', () => {
  const a = render(<Floor snapshot={snap()} nodes={twelve({ n9: 'offline', n10: 'offline', n11: 'unknown' })} />)
  expect(up()).toHaveAccessibleName('Monter d\'un étage : 2 nœuds hors ligne à l\'étage 3')
  a.unmount()
  const b = render(<Floor snapshot={snap()} nodes={twelve({ n6: 'unknown', n7: 'unknown', n8: 'unknown' })} />)
  expect(up()).toHaveAccessibleName('Monter d\'un étage : 3 nœuds en état inconnu à l\'étage 2')
  b.unmount()
  render(<Floor snapshot={snap()} nodes={twelve({ n9: 'offline' })} />)
  expect(up()).toHaveAccessibleName('Monter d\'un étage : un nœud hors ligne à l\'étage 3')
})

test('repli pendant l\'ascenseur : les couches reçoivent data-snap (aucune transition) tant qu\'aucun mouvement ne suit', () => {
  motion()
  vi.useFakeTimers()
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up())
  expect(container.querySelector('[data-snap]')).toBeNull()
  rerender(<Floor snapshot={snap()} nodes={twelve().slice(0, 6)} />)
  expect([...container.querySelectorAll('.level')].map((e) => e.hasAttribute('data-snap'))).toEqual([true])
  fireEvent.click(down())
  expect(container.querySelector('[data-snap]')).toBeNull()
  vi.useRealTimers()
})

test('étiquette du sélecteur : largeur bornée, deux lignes d\'alerte au plus, texte complet pour les lecteurs d\'écran et en infobulle', () => {
  const many = Array.from({ length: 20 }, (_, i) => node(`s${i + 1}`, [5, 9, 13, 17].includes(i + 1) ? 'offline' : 'online')) // floors 2, 3, 4, 5 in alert
  render(<Floor snapshot={snap()} nodes={many} />)
  const label = document.querySelector('[data-floor-label]') as HTMLElement
  expect(label.className).toContain('w-[130px]'); expect(label.className).toContain('min-w-0')
  const alert = label.querySelector('[data-alert-line]') as HTMLElement
  expect(alert.className).toContain('line-clamp-2')
  expect(label.textContent).toBe('Étage 1 / 5 · alerte : étages 2, 3, 4, 5') // the full list, whatever is clipped on screen
  expect(label.getAttribute('title')).toBe('Étage 1 / 5 · alerte : étages 2, 3, 4, 5')
  expect(up()).toHaveAccessibleName('Monter d\'un étage : un nœud hors ligne à l\'étage 2, un nœud hors ligne à l\'étage 3, un nœud hors ligne à l\'étage 4, un nœud hors ligne à l\'étage 5')
})
