import { render } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { NodeState, NowSnapshot } from '@/api'
import { Floor, FloorScene } from './Floor'
import { drawOrder, layoutFloor, toPercent } from './iso'
import { node, setupFloorTest, snap } from './floorSupport'

setupFloorTest()

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
