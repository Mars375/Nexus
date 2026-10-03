import { describe, expect, test } from 'vitest'
import { DESK, LED_STEP, LED_TOP, RACK, box, drawOrder, layoutFloor, layoutServerFloor, ledQuad, nearestQuarter, spreadLabels, toPercent, type Rect } from './iso'

const ANGLES = Array.from({ length: 72 }, (_, i) => i * 5)
const QUARTERS = [0, 90, 180, 270]

describe('layoutFloor', () => {
  test('8 agents : deux rangées de 4, la table au centre', () => {
    const l = layoutFloor(8, 4)
    expect(l.seats).toHaveLength(8)
    expect(l.seats.filter((s) => s.back)).toHaveLength(4)
    const tableCenterX = l.table.x + l.table.w / 2
    const seatsCenterX = (Math.min(...l.seats.map((s) => s.x)) + Math.max(...l.seats.map((s) => s.x + DESK.w))) / 2
    expect(Math.abs(tableCenterX - seatsCenterX)).toBeLessThan(0.01)
    expect(l.racks).toHaveLength(4)
  })
  test('12 agents : les rangées s\'allongent, l\'étage s\'élargit', () => {
    const eight = layoutFloor(8, 4), twelve = layoutFloor(12, 4)
    expect(twelve.seats.filter((s) => s.back)).toHaveLength(6)
    expect(twelve.width).toBeGreaterThan(eight.width)
  })
  test('aucun bureau ne chevauche la table ni un autre bureau', () => {
    const l = layoutFloor(12, 4)
    const rects = [...l.seats.map((s) => ({ x: s.x, y: s.y, w: DESK.w, d: DESK.d })), { x: l.table.x, y: l.table.y, w: l.table.w, d: l.table.d }]
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i], b = rects[j]
      const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.d && b.y < a.y + a.d
      expect(overlap).toBe(false)
    }
  })
  test('1 agent et aucun nœud : un étage valable', () => {
    const l = layoutFloor(1, 0)
    expect(l.seats).toHaveLength(1)
    expect(l.racks).toHaveLength(0)
  })
  test('la légende n\'est plus dans le plan', () => {
    expect('legend' in layoutFloor(8, 4)).toBe(false)
  })
})

describe('baies dans la profondeur', () => {
  test('de 1 à 12 baies, toutes tiennent dans la profondeur du sol (deux colonnes au-delà de 7)', () => {
    for (let n = 1; n <= 12; n++) {
      const l = layoutFloor(8, n)
      expect(l.racks).toHaveLength(n)
      for (const r of l.racks) { expect(r.y, `${n} baies`).toBeGreaterThanOrEqual(0); expect(r.y + RACK.d, `${n} baies`).toBeLessThanOrEqual(l.depth) }
    }
  })
  test('de 1 à 12 baies, aucune ne chevauche une autre (en x comme en y)', () => {
    for (let n = 1; n <= 12; n++) {
      const { racks } = layoutFloor(8, n)
      for (let i = 0; i < racks.length; i++) for (let j = i + 1; j < racks.length; j++) {
        const a = racks[i], b = racks[j]
        const overlap = a.x < b.x + RACK.w && b.x < a.x + RACK.w && a.y < b.y + RACK.d && b.y < a.y + RACK.d
        expect(overlap, `${n} baies : ${i} et ${j}`).toBe(false)
      }
    }
  })
  test('toutes les baies restent dans la largeur du sol', () => {
    for (let n = 1; n <= 12; n++) { const l = layoutFloor(8, n); for (const r of l.racks) { expect(r.x).toBeGreaterThanOrEqual(0); expect(r.x + RACK.w).toBeLessThanOrEqual(l.width) } }
  })
  test('à 7 baies ou moins, les positions sont celles d\'avant', () => {
    for (let n = 1; n <= 7; n++) expect(layoutFloor(8, n).racks.map((r) => r.y)).toEqual(Array.from({ length: n }, (_, i) => 0.8 + i * 1.85))
  })
})

describe('projection', () => {
  test('à 0°, les points sont ceux de la projection isométrique d\'origine', () => {
    const l = layoutFloor(8, 4)
    const A = Math.cos(Math.PI / 6) * 26, B = Math.sin(Math.PI / 6) * 26
    const ox = 150 + l.depth * A, oy = 110
    const round = (v: number) => Math.round(v * 10) / 10
    for (const [x, y, z] of [[0, 0, 0], [3, 2, 0], [10, 7, 1.8], [l.width, l.depth, -0.35]] as const) {
      expect(l.project(x, y, z)).toEqual([round(ox + (x - y) * A), round(oy + (x + y) * B - z * 26)])
    }
  })
  test('le centre du sol ne bouge pas quand l\'étage tourne', () => {
    const base = layoutFloor(8, 4)
    const c = base.project(base.width / 2, base.depth / 2)
    for (const a of ANGLES) {
      const l = layoutFloor(8, 4, a)
      const p = l.project(l.width / 2, l.depth / 2)
      expect(Math.abs(p[0] - c[0])).toBeLessThan(0.15); expect(Math.abs(p[1] - c[1])).toBeLessThan(0.15)
    }
  })
  test('un tour complet ramène au point de départ', () => {
    const a = layoutFloor(8, 4, 0).project(3, 2, 1), b = layoutFloor(8, 4, 360).project(3, 2, 1)
    expect(b[0]).toBeCloseTo(a[0], 0); expect(b[1]).toBeCloseTo(a[1], 0)
  })
  test('à 180°, un point et son symétrique par rapport au centre échangent leurs places', () => {
    const l0 = layoutFloor(8, 4, 0), l180 = layoutFloor(8, 4, 180)
    const p = l0.project(2, 3), q = l180.project(l0.width - 2, l0.depth - 3)
    expect(q[0]).toBeCloseTo(p[0], 0); expect(q[1]).toBeCloseTo(p[1], 0)
  })
})

describe('viewBox fixe', () => {
  test('identique à tous les angles', () => {
    const ref = layoutFloor(8, 4, 0).viewBox
    for (const a of [...ANGLES, 33, -47, 400]) expect(layoutFloor(8, 4, a).viewBox).toEqual(ref)
  })
  test('tout le sol, toutes les baies et toutes les étiquettes tiennent dans le cadre, à chaque angle', () => {
    // Two-column cases (8 racks and more) are sampled every 15° (the quarters included): each one builds its own frame.
    const cases = [...[0, 1, 4, 6].flatMap((r) => [1, 8, 12].map((n) => [n, r, 3] as const)), ...[8, 12].flatMap((r) => [8, 12].map((n) => [n, r, 15] as const))]
    for (const [agents, racks, step] of cases) for (let a = 0; a < 360; a += step) {
      const l = layoutFloor(agents, racks, a), { x, y, w, h } = l.viewBox
      const inside = ([px, py]: readonly [number, number], what: string) => {
        expect(px, `${what} x à ${a}°`).toBeGreaterThanOrEqual(x); expect(px, `${what} x à ${a}°`).toBeLessThanOrEqual(x + w)
        expect(py, `${what} y à ${a}°`).toBeGreaterThanOrEqual(y); expect(py, `${what} y à ${a}°`).toBeLessThanOrEqual(y + h)
      }
      for (const [cx, cy] of [[0, 0], [l.width, 0], [0, l.depth], [l.width, l.depth]]) { inside(l.project(cx, cy, 0), 'sol'); inside(l.project(cx, cy, -0.35), 'sol') }
      for (const r of l.racks) for (const [dx, dy] of [[0, 0], [RACK.w, 0], [0, RACK.d], [RACK.w, RACK.d]]) { inside(l.project(r.x + dx, r.y + dy, 0), 'baie'); inside(l.project(r.x + dx, r.y + dy, RACK.h), 'baie') }
      for (const { box: b } of l.labels) for (const c of [[b.x0, b.y0], [b.x1, b.y0], [b.x0, b.y1], [b.x1, b.y1]] as const) inside(c, 'étiquette')
    }
  })
})

describe('box', () => {
  test('à 0° : le dessus et les faces gauche (+y) et droite (+x) d\'origine', () => {
    const l = layoutFloor(8, 4)
    const b = box(l, 1, 1, 0, 3, 1.5, 0.75), p = l.project
    const pts = (list: readonly (readonly [number, number])[]) => list.map((q) => `${q[0]},${q[1]}`).join(' ')
    expect(b.top).toBe(pts([p(1, 1, 0.75), p(4, 1, 0.75), p(4, 2.5, 0.75), p(1, 2.5, 0.75)]))
    expect(b.sides.map((s) => s.dir)).toEqual(['+y', '+x'])
    expect(b.sides[0]).toMatchObject({ shade: 'f-left', points: pts([p(1, 2.5, 0.75), p(4, 2.5, 0.75), p(4, 2.5, 0), p(1, 2.5, 0)]) })
    expect(b.sides[1]).toMatchObject({ shade: 'f-right', points: pts([p(4, 1, 0.75), p(4, 2.5, 0.75), p(4, 2.5, 0), p(4, 1, 0)]) })
  })
  test('à chaque quart de tour : deux faces latérales, les bonnes', () => {
    const want: Record<number, string[]> = { 0: ['+x', '+y'], 90: ['+x', '-y'], 180: ['-x', '-y'], 270: ['+y', '-x'] }
    for (const a of QUARTERS) {
      const l = layoutFloor(8, 4, a)
      const b = box(l, 1, 1, 0, 3, 1.5, 0.75)
      expect(b.sides.map((s) => s.dir).sort(), `à ${a}°`).toEqual(want[a])
      for (const s of b.sides) expect(s.points.split(' ')).toHaveLength(4)
      expect(new Set(b.sides.map((s) => s.shade)).size).toBe(2) // une face claire, une face sombre
    }
  })
  test('à tous les angles, une face rendue est tournée vers le spectateur (plus bas à l\'écran que le centre de la boîte)', () => {
    for (let a = 0; a < 360; a += 7) {
      const l = layoutFloor(8, 4, a)
      const b = box(l, 4, 3, 0, 3, 1.5, 0.75)
      const centre = l.project(5.5, 3.75, 0.375)[1]
      expect(b.sides.length).toBeGreaterThanOrEqual(1); expect(b.sides.length).toBeLessThanOrEqual(2)
      for (const s of b.sides) {
        const ys = s.points.split(' ').map((q) => Number(q.split(',')[1]))
        expect(ys.reduce((u, v) => u + v, 0) / 4, `${s.dir} à ${a}°`).toBeGreaterThan(centre)
      }
    }
  })
  test('le dessus est plus haut à l\'écran que le bas (z monte)', () => {
    const l = layoutFloor(8, 4)
    expect(l.project(1, 1, 1)[1]).toBeLessThan(l.project(1, 1, 0)[1])
  })
  test('sees : une normale est visible quand elle regarde vers l\'avant de l\'écran', () => {
    expect(layoutFloor(8, 4, 0).sees(0, 1)).toBe(true)
    expect(layoutFloor(8, 4, 0).sees(0, -1)).toBe(false)
    expect(layoutFloor(8, 4, 180).sees(0, -1)).toBe(true)
    expect(layoutFloor(8, 4, 90).sees(0, 1)).toBe(false)
  })
})

describe('ordre de dessin', () => {
  test('depthOf : profondeur après rotation (x\' + y\')', () => {
    const l = layoutFloor(8, 4)
    expect(l.depthOf(2, 3)).toBeCloseTo(5)
    const l180 = layoutFloor(8, 4, 180)
    expect(l180.depthOf(2, 3)).toBeCloseTo(l.width + l.depth - 5)
  })
  test('à chaque quart de tour, un objet devant n\'est jamais dessiné avant un objet derrière', () => {
    for (const [agents, racks] of [[8, 4], [12, 6], [3, 1], [1, 0]] as const) for (const a of QUARTERS) {
      const l = layoutFloor(agents, racks, a)
      const order = drawOrder(l)
      expect(order).toHaveLength(agents + racks + 1)
      // Rotation du plan : rectangles alignés sur les axes de l'écran à chaque quart de tour.
      const rot = (x: number, y: number) => {
        const c = Math.cos((a * Math.PI) / 180), s = Math.sin((a * Math.PI) / 180), dx = x - l.width / 2, dy = y - l.depth / 2
        return [l.width / 2 + dx * c - dy * s, l.depth / 2 + dx * s + dy * c] as const
      }
      const rect = (o: (typeof order)[number]) => {
        const [x1, y1] = rot(o.x, o.y), [x2, y2] = rot(o.x + o.w, o.y + o.d)
        return { x0: Math.min(x1, x2), x1: Math.max(x1, x2), y0: Math.min(y1, y2), y1: Math.max(y1, y2) }
      }
      const behind = (p: ReturnType<typeof rect>, q: ReturnType<typeof rect>) => (p.x1 <= q.x0 + 1e-9 || p.y1 <= q.y0 + 1e-9)
      const front = (p: ReturnType<typeof rect>, q: ReturnType<typeof rect>) => (q.x1 <= p.x0 + 1e-9 || q.y1 <= p.y0 + 1e-9)
      for (let i = 0; i < order.length; i++) for (let j = i + 1; j < order.length; j++) {
        const early = rect(order[i]), late = rect(order[j])
        // si `late` est sans ambiguïté derrière `early`, l'ordre est faux
        const wrong = front(early, late) && !behind(early, late)
        expect(wrong, `${order[i].kind}${order[i].index} dessiné avant ${order[j].kind}${order[j].index} à ${a}°`).toBe(false)
      }
    }
  })
  test('contient chaque poste, chaque baie et la table une fois', () => {
    const order = drawOrder(layoutFloor(8, 4, 90))
    expect(order.filter((o) => o.kind === 'seat').map((o) => o.index).sort()).toEqual([0, 1, 2, 3, 4, 5, 6, 7])
    expect(order.filter((o) => o.kind === 'rack').map((o) => o.index).sort()).toEqual([0, 1, 2, 3])
    expect(order.filter((o) => o.kind === 'table')).toHaveLength(1)
  })
})

describe('nearestQuarter', () => {
  test('cale sur le multiple de 90 le plus proche', () => {
    expect(nearestQuarter(44)).toBe(0)
    expect(nearestQuarter(46)).toBe(90)
    expect(nearestQuarter(-46)).toBe(-90)
    expect(nearestQuarter(-44)).toBe(0)
    expect(nearestQuarter(359)).toBe(360)
    expect(nearestQuarter(400)).toBe(360)
    expect(nearestQuarter(-400)).toBe(-360)
    expect(Object.is(nearestQuarter(-10), 0)).toBe(true) // jamais -0
  })
})

test('toPercent place un point du viewBox en pourcentage', () => {
  const l = layoutFloor(8, 4)
  const [px, py] = toPercent(l, [l.viewBox.x + l.viewBox.w / 2, l.viewBox.y + l.viewBox.h / 4])
  expect(px).toBeCloseTo(50); expect(py).toBeCloseTo(25)
})

const hit = (a: Rect, b: Rect) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1
const rect = (x0: number, y0: number, x1: number, y1: number): Rect => ({ x0, y0, x1, y1 })

describe('spreadLabels', () => {
  test('ne bouge pas des étiquettes qui ne se touchent pas', () => {
    expect(spreadLabels([rect(0, 0, 10, 10), rect(50, 0, 60, 10)], [rect(0, 100, 10, 110)])).toEqual([0, 0])
  })
  test('relève vers le haut l\'étiquette qui en touche une autre, la première (le fond) reste', () => {
    const boxes = [rect(0, 100, 100, 146), rect(40, 110, 140, 156)]
    const lifts = spreadLabels(boxes, [])
    expect(lifts[0]).toBe(0)
    expect(lifts[1]).toBeGreaterThan(0)
    expect(boxes[1].y1 - lifts[1]).toBeLessThanOrEqual(boxes[0].y0)
  })
  test('évite les zones fixes et ne s\'arrête que lorsque plus rien ne touche', () => {
    const fixed = [rect(0, 80, 200, 120)]
    const boxes = [rect(10, 90, 60, 130), rect(30, 130, 80, 170), rect(20, 60, 70, 100)]
    const lifts = spreadLabels(boxes, fixed)
    const placed = boxes.map((b, i) => rect(b.x0, b.y0 - lifts[i], b.x1, b.y1 - lifts[i]))
    for (const p of placed) expect(hit(p, fixed[0])).toBe(false)
    for (let i = 0; i < placed.length; i++) for (let j = i + 1; j < placed.length; j++) expect(hit(placed[i], placed[j])).toBe(false)
    for (const v of lifts) expect(v).toBeGreaterThanOrEqual(0)
  })
  test('une étiquette du bas est décalée vers le bas, loin du bureau', () => {
    const boxes = [rect(0, 100, 100, 146), rect(40, 110, 140, 156)]
    const shifts = spreadLabels(boxes, [], [true, true])
    expect(shifts[0]).toBe(0)
    expect(shifts[1]).toBeGreaterThan(0) // décalage « loin du bureau » : vers le bas ici
    expect(boxes[1].y0 + shifts[1]).toBeGreaterThanOrEqual(boxes[0].y1)
  })
  test('déterministe : même entrée, même sortie', () => {
    const boxes = [rect(0, 0, 100, 40), rect(20, 10, 120, 50), rect(40, 20, 140, 60)]
    expect(spreadLabels(boxes, [])).toEqual(spreadLabels(boxes, []))
  })
})

describe('étiquettes du plan', () => {
  test('à chaque quart de tour, pour 8 et 12 agents, aucune étiquette ne touche une autre ni une zone fixe', () => {
    for (const agents of [8, 12]) for (const a of QUARTERS) {
      const l = layoutFloor(agents, 4, a)
      expect(l.labels).toHaveLength(agents)
      expect(l.zones.length).toBeGreaterThanOrEqual(3) // légende, coin de la table, boutons
      for (let i = 0; i < agents; i++) {
        for (const z of l.zones) expect(hit(l.labels[i].box, z), `étiquette ${i} touche une zone fixe, ${agents} agents à ${a}°`).toBe(false)
        for (let j = i + 1; j < agents; j++) expect(hit(l.labels[i].box, l.labels[j].box), `étiquettes ${i} et ${j}, ${agents} agents à ${a}°`).toBe(false)
      }
    }
  })
  test('le résultat est stable : mêmes entrées, mêmes étiquettes', () => {
    expect(layoutFloor(12, 4, 90).labels).toEqual(layoutFloor(12, 4, 90).labels)
  })
  test('à chaque angle, les étiquettes relevées tiennent dans le cadre fixe', () => {
    for (const agents of [1, 8, 12]) for (let a = 0; a < 360; a += 3) {
      const l = layoutFloor(agents, 4, a), { x, y, w, h } = l.viewBox
      for (const { box: b } of l.labels) { expect(b.y0, `${agents} à ${a}°`).toBeGreaterThanOrEqual(y); expect(b.y1).toBeLessThanOrEqual(y + h); expect(b.x0).toBeGreaterThanOrEqual(x); expect(b.x1).toBeLessThanOrEqual(x + w) }
    }
  })
  test('la rangée la plus éloignée a son étiquette au-dessus, la plus proche en dessous, à chaque quart de tour', () => {
    const farRow = (a: number) => (a === 0 || a === 270 ? 'back' : 'front') // rangée éloignée du spectateur : celle qui est au-dessus
    for (const agents of [8, 12]) for (const a of QUARTERS) {
      const l = layoutFloor(agents, 4, a)
      l.seats.forEach((s, i) => {
        const above = (s.back ? 'back' : 'front') === farRow(a)
        expect(l.labels[i].below, `poste ${i}, ${agents} agents à ${a}°`).toBe(!above)
      })
    }
  })
  test('à tout angle, la règle suit la profondeur de la rangée par rapport au centre du sol', () => {
    for (let a = 0; a < 360; a += 7) {
      const l = layoutFloor(8, 4, a)
      l.seats.forEach((s, i) => {
        const rowDepth = l.depthOf(l.width / 2, s.y + DESK.d / 2) - l.depthOf(l.width / 2, l.depth / 2)
        if (Math.abs(rowDepth) > 1e-6) expect(l.labels[i].below, `à ${a}°`).toBe(rowDepth > 0)
      })
    }
  })
  test('le trait de rappel part du bureau, va du côté de l\'étiquette et reste court', () => {
    let longest = 0
    for (const agents of [8, 12]) for (const a of QUARTERS) {
      const l = layoutFloor(agents, 4, a)
      l.labels.forEach((lab) => {
        const len = Math.abs(lab.y - lab.anchor[1])
        longest = Math.max(longest, len)
        expect(lab.x).toBe(lab.anchor[0])
        if (lab.below) { expect(lab.y).toBeGreaterThanOrEqual(lab.anchor[1] + 26 - 1e-9); expect(lab.box.y0).toBeCloseTo(lab.y, 5) }
        else { expect(lab.y).toBeLessThanOrEqual(lab.anchor[1] - 40 + 1e-9); expect(lab.box.y1).toBeCloseTo(lab.y, 5) }
      })
    }
    expect(longest).toBeLessThanOrEqual(130)
  })
})

describe('étage 1 : zones et cadre (#36)', () => {
  // Frames of `master`, measured before the floors existed: with at most 4 nodes floor 1 must not move.
  test('le cadre de l\'étage 1 jusqu\'à 4 baies est celui de master', () => {
    expect(layoutFloor(1, 0).viewBox).toEqual({ x: 136.3, y: -28.3, w: 725.5, h: 648.8 })
    expect(layoutFloor(8, 4).viewBox).toEqual({ x: 131.4, y: -12.3, w: 807.2, h: 821.3 })
    expect(layoutFloor(12, 4).viewBox).toEqual({ x: 108.8, y: -7.5, w: 1032.6, h: 905.9 })
    expect(layoutFloor(8, 4, 0, 1).viewBox).toEqual(layoutFloor(8, 4).viewBox)
  })
  test('la légende ne dépasse pas 4 lignes, quel que soit le nombre de nœuds', () => {
    const legend = (n: number) => { const l = layoutFloor(8, n), z = l.zones[0]; return (z.y1 - z.y0) / (l.viewBox.w / 529) }
    expect(legend(4)).toBeCloseTo(80, 5)
    for (const n of [5, 8, 12]) expect(legend(n)).toBeCloseTo(80, 5)
    expect(legend(2)).toBeCloseTo(40, 5)
    expect(legend(0)).toBeCloseTo(20, 5)
  })
  test('avec plusieurs étages, la zone haut-gauche réserve la place du sélecteur sous les boutons', () => {
    const top = (floors: number) => { const l = layoutFloor(8, 4, 0, floors), z = l.zones[2], k = l.viewBox.w / 529; return { w: (z.x1 - z.x0) / k, h: (z.y1 - z.y0) / k } }
    expect(top(1)).toEqual({ w: expect.closeTo(80, 5), h: expect.closeTo(40, 5) })
    expect(top(2).w).toBeGreaterThanOrEqual(170 - 1e-6)
    expect(top(2).h).toBeGreaterThanOrEqual(80 - 1e-6)
  })
  test('avec plusieurs étages, aucune étiquette ne touche une zone fixe à chaque quart de tour (8 et 12 agents)', () => {
    for (const agents of [8, 12]) for (const a of QUARTERS) {
      const l = layoutFloor(agents, 4, a, 3)
      for (let i = 0; i < agents; i++) {
        for (const z of l.zones) expect(hit(l.labels[i].box, z), `étiquette ${i}, ${agents} agents à ${a}°`).toBe(false)
        for (let j = i + 1; j < agents; j++) expect(hit(l.labels[i].box, l.labels[j].box), `étiquettes ${i} et ${j}, ${agents} agents à ${a}°`).toBe(false)
      }
    }
  })
  test('avec plusieurs étages, le cadre reste fixe à tous les angles et contient les étiquettes', () => {
    for (const agents of [8, 12]) {
      const ref = layoutFloor(agents, 4, 0, 2).viewBox
      for (let a = 0; a < 360; a += 5) {
        const l = layoutFloor(agents, 4, a, 2), { x, y, w, h } = l.viewBox
        expect(l.viewBox).toEqual(ref)
        for (const { box: b } of l.labels) { expect(b.y0).toBeGreaterThanOrEqual(y); expect(b.y1).toBeLessThanOrEqual(y + h); expect(b.x0).toBeGreaterThanOrEqual(x); expect(b.x1).toBeLessThanOrEqual(x + w) }
      }
    }
  })
})

describe('salle des serveurs (#36)', () => {
  const FLOOR_COUNTS = [1, 2, 3] as const
  const hull = (pts: readonly (readonly [number, number])[]) => {
    const p = [...pts].sort((a, b) => a[0] - b[0] || a[1] - b[1])
    const cross = (o: readonly number[], a: readonly number[], b: readonly number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    const build = (list: typeof p) => { const h: (readonly [number, number])[] = []; for (const q of list) { while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], q) <= 0) h.pop(); h.push(q) } return h }
    const lower = build(p), upper = build([...p].reverse())
    return [...lower.slice(0, -1), ...upper.slice(0, -1)]
  }
  const inside = (h: ReturnType<typeof hull>, q: readonly [number, number]) => h.every((a, i) => { const b = h[(i + 1) % h.length]; return (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0]) > 0.05 })
  const corners = (x: number, y: number, w: number, d: number, z0: number, z1: number) => ([[x, y], [x + w, y], [x, y + d], [x + w, y + d]] as const).flatMap(([px, py]) => [[px, py, z0], [px, py, z1]] as const)

  test('la salle a l\'emprise exacte de l\'étage 1, quel que soit le nombre de baies et d\'agents', () => {
    for (const agents of [1, 8, 12]) for (const k of [1, 2, 3, 4]) {
      const base = layoutFloor(agents, 4, 0, 2)
      expect(layoutServerFloor(base, k).room).toEqual({ x: 0, y: 0, w: base.width, d: base.depth })
    }
  })
  test('les baies sont en rangée, centrées (1 à 3 baies aussi), sans chevauchement, dans la salle', () => {
    const base = layoutFloor(8, 4, 0, 2)
    for (const k of [1, 2, 3, 4]) {
      const { room, racks } = layoutServerFloor(base, k)
      expect(racks).toHaveLength(k)
      const left = Math.min(...racks.map((r) => r.x)), right = Math.max(...racks.map((r) => r.x + RACK.w))
      expect((left + right) / 2, `${k} baies`).toBeCloseTo(base.width / 2, 6)
      for (const r of racks) {
        expect(r.y + RACK.d / 2).toBeCloseTo(base.depth / 2, 6)
        expect(r.x).toBeGreaterThanOrEqual(room.x); expect(r.x + RACK.w).toBeLessThanOrEqual(room.x + room.w)
      }
      for (let i = 1; i < racks.length; i++) expect(racks[i].x).toBeGreaterThanOrEqual(racks[i - 1].x + RACK.w)
    }
  })
  test('les allées chaude et froide longent la rangée, de part et d\'autre, de même profondeur', () => {
    const { aisles } = layoutServerFloor(layoutFloor(8, 4, 0, 2), 4)
    expect(aisles.cold.y).toBeCloseTo(14 / 2 + RACK.d / 2, 6) // right in front of the +y side of the row
    expect(aisles.hot.y + aisles.hot.d).toBeCloseTo(14 / 2 - RACK.d / 2, 6)
    expect(aisles.hot.d).toBeCloseTo(aisles.cold.d, 6); expect(aisles.cold.d).toBeGreaterThan(1)
  })
  test('un groupe de refroidissement à chaque bout de la rangée, toujours au même endroit, sans toucher les baies', () => {
    const base = layoutFloor(8, 4, 0, 2)
    const ref = layoutServerFloor(base, 4).units
    expect(ref).toHaveLength(2)
    for (const k of [1, 2, 3, 4]) {
      const { units, racks, room } = layoutServerFloor(base, k)
      expect(units).toEqual(ref)
      const [a, b] = units
      expect(a.x + a.w / 2 + b.x + b.w / 2).toBeCloseTo(base.width, 6) // symmetric about the centre
      for (const u of units) {
        expect(u.x).toBeGreaterThanOrEqual(room.x); expect(u.x + u.w).toBeLessThanOrEqual(room.x + room.w)
        expect(u.y + u.d / 2).toBeCloseTo(base.depth / 2, 6)
        for (const r of racks) expect(u.x + u.w <= r.x - 0.4 || r.x + RACK.w <= u.x - 0.4, `unité et baie à moins de 0,4`).toBe(true)
      }
    }
  })
  test('le chemin de câbles a la même longueur à tous les étages, d\'une unité à l\'autre et au-dessus de tout', () => {
    const base = layoutFloor(8, 4, 0, 2)
    expect(new Set([1, 2, 3, 4].map((k) => layoutServerFloor(base, k).tray.w)).size).toBe(1)
    const { tray, units } = layoutServerFloor(base, 4)
    expect(tray.z).toBeGreaterThan(Math.max(RACK.h, ...units.map((u) => u.h))); expect(tray.h).toBeCloseTo(0.12, 6)
    expect(tray.x).toBeLessThanOrEqual(units[0].x + 1e-9); expect(tray.x + tray.w).toBeGreaterThanOrEqual(units[1].x + units[1].w - 1e-9)
  })
  test('les marques au sol sont de simples traits fixes, tous dans la salle', () => {
    const base = layoutFloor(8, 4, 0, 2), { room, markings } = layoutServerFloor(base, 4)
    expect(markings.length).toBeGreaterThan(0)
    for (const [[x0, y0], [x1, y1]] of markings) for (const [px, py] of [[x0, y0], [x1, y1]]) { expect(px).toBeGreaterThanOrEqual(room.x); expect(px).toBeLessThanOrEqual(room.x + room.w); expect(py).toBeGreaterThanOrEqual(room.y); expect(py).toBeLessThanOrEqual(room.y + room.d) }
  })
  test('sol, sommets des baies, chemin de câbles et marquage tiennent dans le cadre fixe, tous les 5°', () => {
    for (const agents of [1, 8, 12]) for (const floors of FLOOR_COUNTS) for (let a = 0; a < 360; a += 5) {
      const base = layoutFloor(agents, 4, a, floors), { x, y, w, h } = base.viewBox
      expect(base.viewBox).toEqual(layoutFloor(agents, 4, 0, floors).viewBox)
      for (const k of [1, 2, 3, 4]) {
        const f = layoutServerFloor(base, k)
        const pts: (readonly [number, number])[] = []
        for (const [px, py] of [[f.room.x, f.room.y], [f.room.x + f.room.w, f.room.y], [f.room.x, f.room.y + f.room.d], [f.room.x + f.room.w, f.room.y + f.room.d]]) pts.push(base.project(px, py, 0), base.project(px, py, -0.35))
        for (const r of f.racks) for (const [px, py, pz] of corners(r.x, r.y, RACK.w, RACK.d, 0, RACK.h)) pts.push(base.project(px, py, pz))
        for (const [px, py, pz] of corners(f.tray.x, f.tray.y, f.tray.w, f.tray.d, f.tray.z, f.tray.z + f.tray.h)) pts.push(base.project(px, py, pz))
        for (const u of f.units) for (const [px, py, pz] of corners(u.x, u.y, u.w, u.d, 0, u.h)) pts.push(base.project(px, py, pz))
        for (const [p0, p1] of f.markings) pts.push(base.project(p0[0], p0[1], 0), base.project(p1[0], p1[1], 0))
        pts.push(base.project(f.markerAt[0], f.markerAt[1], 0))
        for (const [px, py] of pts) {
          expect(px, `${agents} agents, ${k} baies à ${a}°`).toBeGreaterThanOrEqual(x); expect(px).toBeLessThanOrEqual(x + w)
          expect(py, `${agents} agents, ${k} baies à ${a}°`).toBeGreaterThanOrEqual(y); expect(py).toBeLessThanOrEqual(y + h)
        }
      }
    }
  })
  test('le centre de la rangée de baies reste au centre du sol à chaque quart de tour (0,5 unité près)', () => {
    for (const k of [1, 2, 3, 4]) for (const a of QUARTERS) {
      const base = layoutFloor(8, 4, a, 2), f = layoutServerFloor(base, k)
      const pts = f.racks.flatMap((r) => corners(r.x, r.y, RACK.w, RACK.d, 0, RACK.h).map(([px, py, pz]) => base.project(px, py, pz)))
      const mid = [(Math.min(...pts.map((p) => p[0])) + Math.max(...pts.map((p) => p[0]))) / 2, (Math.min(...pts.map((p) => p[1])) + Math.max(...pts.map((p) => p[1]))) / 2]
      const centre = base.project(base.width / 2, base.depth / 2, RACK.h / 2) // the envelope is centred on the middle of the racks' height
      expect(Math.abs(mid[0] - centre[0]), `${k} baies à ${a}°`).toBeLessThanOrEqual(0.5)
      expect(Math.abs(mid[1] - centre[1]), `${k} baies à ${a}°`).toBeLessThanOrEqual(0.5)
    }
  })
  test('à chaque quart de tour, aucune LED n\'est cachée par une autre baie ni par le chemin de câbles', () => {
    for (const k of [1, 2, 3, 4]) for (const a of QUARTERS) {
      const base = layoutFloor(8, 4, a, 2), f = layoutServerFloor(base, k)
      expect(['+y', '-y'], `${k} baies à ${a}°`).toContain(f.ledFace)
      expect(base.sees(0, f.ledFace === '+y' ? 1 : -1)).toBe(true)
      const hulls = f.racks.map((r) => hull(corners(r.x, r.y, RACK.w, RACK.d, 0, RACK.h).map(([px, py, pz]) => base.project(px, py, pz))))
      const trayHull = hull(corners(f.tray.x, f.tray.y, f.tray.w, f.tray.d, f.tray.z, f.tray.z + f.tray.h).map(([px, py, pz]) => base.project(px, py, pz)))
      const unitHulls = f.units.map((u) => ({ at: [u.x + u.w / 2, u.y + u.d / 2] as const, hull: hull(corners(u.x, u.y, u.w, u.d, 0, u.h).map(([px, py, pz]) => base.project(px, py, pz))) }))
      f.racks.forEach((r, i) => {
        for (let j = 0; j < 5; j++) {
          const quad = ledQuad(base, r, f.ledFace, LED_TOP - j * LED_STEP)
          const probes = [...quad, [quad.reduce((s, q) => s + q[0], 0) / 4, quad.reduce((s, q) => s + q[1], 0) / 4] as const]
          for (const q of probes) {
            expect(inside(trayHull, q), `LED ${j} de la baie ${i} sous le chemin de câbles, ${k} baies à ${a}°`).toBe(false)
            for (const u of unitHulls) if (base.depthOf(...u.at) > base.depthOf(r.x + RACK.w / 2, r.y + RACK.d / 2)) expect(inside(u.hull, q), `LED ${j} de la baie ${i} cachée par une unité de refroidissement, ${k} baies à ${a}°`).toBe(false)
            f.racks.forEach((o, m) => { if (m !== i && base.depthOf(o.x + RACK.w / 2, o.y + RACK.d / 2) > base.depthOf(r.x + RACK.w / 2, r.y + RACK.d / 2)) expect(inside(hulls[m], q), `LED ${j} de la baie ${i} cachée par la baie ${m}, ${k} baies à ${a}°`).toBe(false) })
          }
        }
      })
    }
  })
  test('le marquage est une matrice affine qui pose un point du sol là où project le met', () => {
    for (const a of [0, 37, 90, 180, 270]) {
      const base = layoutFloor(8, 4, a, 2), { marker } = layoutServerFloor(base, 4)
      const [ma, mb, mc, md, me, mf] = marker
      for (const [px, py] of [[0, 0], [2, 0], [0, 3], [5, 2.5]] as const) {
        const [sx, sy] = base.project(px, py, 0)
        expect(ma * px + mc * py + me, `à ${a}°`).toBeCloseTo(sx, 0); expect(mb * px + md * py + mf, `à ${a}°`).toBeCloseTo(sy, 0)
      }
    }
  })
  test('« ÉTAGE n » se lit toujours à l\'endroit (jamais à l\'envers ni en miroir) et n\'est jamais caché par une baie ni par le chemin de câbles, à tous les angles', () => {
    for (const k of [1, 2, 3, 4]) for (let a = 0; a < 360; a += 5) {
      const base = layoutFloor(8, 4, a, 2), f = layoutServerFloor(base, k)
      const [ma, mb, mc, md] = f.marker
      expect(ma * md - mb * mc, `miroir, ${k} baies à ${a}°`).toBeGreaterThan(0)
      // reading direction on screen: the plan x axis, turned half a turn when the mark is flipped
      const dir = f.markerFlip ? -1 : 1
      expect(dir * ma, `à l'envers, ${k} baies à ${a}°`).toBeGreaterThanOrEqual(-1e-6)
      const hulls = [...f.racks.map((r) => corners(r.x, r.y, RACK.w, RACK.d, 0, RACK.h)), ...f.units.map((u) => corners(u.x, u.y, u.w, u.d, 0, u.h)), corners(f.tray.x, f.tray.y, f.tray.w, f.tray.d, f.tray.z, f.tray.z + f.tray.h)].map((c) => hull(c.map(([px, py, pz]) => base.project(px, py, pz))))
      for (let t = -2.4; t <= 2.4 + 1e-9; t += 0.4) {
        const q = base.project(f.markerAt[0] + dir * t, f.markerAt[1], 0)
        hulls.forEach((h, i) => expect(inside(h, q), `le marquage touche l'obstacle ${i}, ${k} baies à ${a}° (t = ${t.toFixed(1)})`).toBe(false))
      }
    }
  })
  test('une étiquette par baie : aucune ne touche une autre ni un coin fixe, à chaque quart de tour et tous les 15°, 8 et 12 agents', () => {
    for (const agents of [8, 12]) for (const k of [1, 2, 3, 4]) for (let a = 0; a < 360; a += 15) {
      const l = layoutFloor(agents, 4, a, 3), f = layoutServerFloor(l, k)
      expect(f.labels).toHaveLength(k)
      f.labels.forEach((lab, i) => {
        for (const z of l.zones) expect(hit(lab.box, z), `étiquette ${i} touche une zone fixe, ${agents} agents, ${k} baies à ${a}°`).toBe(false)
        for (let j = i + 1; j < k; j++) expect(hit(lab.box, f.labels[j].box), `étiquettes ${i} et ${j}, ${agents} agents, ${k} baies à ${a}°`).toBe(false)
      })
    }
  })
  test('les étiquettes des baies tiennent dans le cadre fixe à chaque angle', () => {
    for (const agents of [8, 12]) for (let a = 0; a < 360; a += 5) {
      const l = layoutFloor(agents, 4, a, 2), { x, y, w, h } = l.viewBox
      for (const k of [1, 2, 3, 4]) for (const { box: b } of layoutServerFloor(l, k).labels) {
        expect(b.x0, `${agents} agents, ${k} baies à ${a}°`).toBeGreaterThanOrEqual(x); expect(b.x1).toBeLessThanOrEqual(x + w)
        expect(b.y0).toBeGreaterThanOrEqual(y); expect(b.y1).toBeLessThanOrEqual(y + h)
      }
    }
  })
  test('le cadre de l\'étage 1 ne bouge pas quand on ajoute les étiquettes des baies (4 nœuds et moins)', () => {
    expect(layoutFloor(8, 4, 0, 1).viewBox).toEqual({ x: 131.4, y: -12.3, w: 807.2, h: 821.3 })
  })
  test('à 45° pile, une face LED visible existe quand même', () => {
    const f = layoutServerFloor(layoutFloor(8, 4, 45, 2), 4)
    expect(['+y', '-y', '+x', '-x']).toContain(f.ledFace)
  })
})
