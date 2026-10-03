import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { NodeState, NowSnapshot } from '@/api'
import { Floor, FloorScene } from './Floor'
import { resetFloorRotation } from './useFloorRotation'
import { LABEL_LIFT, drawOrder, layoutFloor, toPercent } from './iso'

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

test('chaque étiquette de poste est au-dessus de son bureau, quel que soit l\'angle', () => {
  for (const a of QUARTERS) {
    const { container } = render(<FloorScene snapshot={snap()} nodes={[]} angle={a} />)
    const l = layoutFloor(3, 0, a)
    const agents = ['helios', 'mnema', 'artemis']
    agents.forEach((agent, i) => {
      const s = l.seats[i], from = l.project(s.x + 1.5, s.y + 0.75, 1.8)
      const [left, top] = toPercent(l, [from[0], from[1] - LABEL_LIFT])
      const el = container.querySelector(`[data-label="${agent}"]`) as HTMLElement
      expect(el.className, agent).toContain('-translate-y-full')
      expect(parseFloat(el.style.left)).toBeCloseTo(left, 3)
      expect(parseFloat(el.style.top)).toBeCloseTo(top, 3)
      const leader = container.querySelectorAll('path.leader')[i]
      expect(leader.getAttribute('d')).toBe(`M${from} L${from[0]} ${from[1] - LABEL_LIFT}`)
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
    expect(rows.map((r) => r.textContent)).toEqual(['HELIOS · en ligne', 'SYNAPSE · unknown', 'ARTEMIS · hors ligne, prévu'])
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

beforeEach(() => { resetFloorRotation(); vi.stubGlobal('PointerEvent', TestPointerEvent); vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q })) })
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
