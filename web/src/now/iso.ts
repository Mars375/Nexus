/*
 * Géométrie de l'étage (#6, #30) : rotation puis projection isométrique, et placement des
 * postes, en fonctions pures. Unités de sol : un bureau fait 3 × 1,5. L'écran ne fait que lire
 * ce plan ; l'angle ne change que la projection, jamais le plan au sol.
 */
export type Pt = readonly [number, number]
export type Dir = '+x' | '-x' | '+y' | '-y'
/** A visible side face: its outward direction (floor axes), points, and CSS shade class. */
export type Side = { dir: Dir; points: string; shade: 'f-left' | 'f-right' }
export type Box = { top: string; sides: Side[] }
export type Seat = { x: number; y: number; back: boolean }
export type Layout = {
  width: number
  depth: number
  /** Rotation of the floor, in degrees (positive = clockwise seen from above). */
  angle: number
  seats: Seat[]
  table: { x: number; y: number; w: number; d: number }
  racks: { x: number; y: number }[]
  /** Fixed frame: the same for every angle, so nothing jumps while the floor turns. */
  viewBox: { x: number; y: number; w: number; h: number }
  project: (x: number, y: number, z?: number) => Pt
  /** One per seat, spread apart so none touches another label or a fixed corner. */
  labels: SeatLabel[]
  /** Fixed HTML corners (rack legend, table corner, rotate buttons), estimated for the smallest render. */
  zones: Rect[]
  /** Depth of a floor point once rotated (x' + y'): larger is nearer to the viewer. */
  depthOf: (x: number, y: number) => number
  /** True when a face with this outward floor normal looks towards the viewer. */
  sees: (nx: number, ny: number) => boolean
}
/** Axis-aligned box in viewBox units. */
export type Rect = { x0: number; y0: number; x1: number; y1: number }
/** Estimated label of a seat: (x, y) is the bottom-centre, where its leader line ends. */
export type SeatLabel = { x: number; y: number; box: Rect }
export type DrawItem = { kind: 'seat' | 'rack' | 'table'; index: number; x: number; y: number; w: number; d: number }

export const DESK = { w: 3, d: 1.5, h: 0.75 }
export const RACK = { w: 1.4, d: 1.4, h: 2.4 }
// Offset (screen units) between a desk's label anchor and its label: clears the neighbouring monitor.
export const LABEL_LIFT = 40
const UNIT = 26
const A = Math.cos(Math.PI / 6) * UNIT
const B = Math.sin(Math.PI / 6) * UNIT
const PITCH = 4 // un poste tous les 4 unités sur une rangée
const ORIGIN = { x: 150, y: 110 } // coin gauche du sol à 0° ; fixe pour que le plan à 0° garde ses coordonnées
const PAD = 12
// Room taken by label text around its anchor, in viewBox units (labels keep their px size).
const LABEL_HALF = 110
const LABEL_TEXT_H = 46
const GAP = 6
const SAMPLE_STEP = 5
const LABEL_STEP = 1

/*
 * Fixed HTML corners keep their size in px while the plan shrinks: their footprint in plan units
 * is computed for the smallest render, a container of MIN_FLOOR_PX (761 px window - menu - gutters).
 */
const MIN_FLOOR_PX = 529
const LEGEND = { w: 210, row: 20 }
const TABLE_CORNER = { w: 270, h: 40 }
const BUTTONS = { w: 80, h: 40 }

const round = (v: number) => Math.round(v * 10) / 10
const radians = (deg: number) => (deg * Math.PI) / 180

function turner(width: number, depth: number, angle: number) {
  const c = Math.cos(radians(angle)), s = Math.sin(radians(angle)), cx = width / 2, cy = depth / 2
  const turn = (x: number, y: number): Pt => [cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c]
  const normal = (nx: number, ny: number): Pt => [nx * c - ny * s, nx * s + ny * c]
  return { turn, normal }
}

export function layoutFloor(agentCount: number, rackCount: number, angle = 0): Layout {
  const perRow = Math.max(4, Math.ceil(agentCount / 2))
  const rowWidth = perRow * PITCH
  const serverWidth = rackCount > 0 ? 3.2 : 0
  const width = rowWidth + 1 + serverWidth
  const depth = 14
  const seats: Seat[] = []
  for (let i = 0; i < agentCount; i++) {
    const back = i < perRow
    const col = back ? i : i - perRow
    seats.push({ x: 1.2 + col * PITCH, y: back ? 1.4 : 10.8, back })
  }
  // table centrée sur l'étendue réelle des postes
  const first = 1.2, last = 1.2 + (perRow - 1) * PITCH + DESK.w
  const table = { w: 5, d: 3.2, x: (first + last) / 2 - 2.5, y: 5.4 }
  const racks = Array.from({ length: rackCount }, (_, i) => ({ x: width - 2.1, y: 0.8 + i * 1.85 }))

  // origine choisie pour que le coin gauche du sol (0, depth) tombe à ORIGIN.x à 0°
  const ox = ORIGIN.x + depth * A
  const oy = ORIGIN.y
  const projector = (a: number) => {
    const { turn } = turner(width, depth, a)
    return (x: number, y: number, z = 0): Pt => {
      const [u, v] = turn(x, y)
      return [round(ox + (u - v) * A), round(oy + (u + v) * B - z * UNIT)]
    }
  }

  const key = `${agentCount}:${rackCount}`
  let vb = frames.get(key)
  if (!vb) {
    vb = fixedFrame(width, depth, seats, racks, rackCount, projector)
    frames.set(key, vb)
  }
  const viewBox = vb
  const zones = zonesOf(viewBox, rackCount)
  const labels = placeLabels(width, depth, angle, seats, projector(angle), zones)

  const { turn, normal } = turner(width, depth, angle)
  const sees = (nx: number, ny: number) => { const [u, v] = normal(nx, ny); return u + v > 1e-9 }
  const depthOf = (x: number, y: number) => { const [u, v] = turn(x, y); return u + v }
  return { width, depth, angle, seats, table, racks, viewBox, project: projector(angle), labels, zones, depthOf, sees }
}

type Frame = Layout['viewBox']
type Projector = (a: number) => Layout['project']
const frames = new Map<string, Frame>()

function zonesOf(vb: Frame, rackCount: number): Rect[] {
  const k = vb.w / MIN_FLOOR_PX // plan units per px at the smallest render
  const right = vb.x + vb.w, bottom = vb.y + vb.h
  return [
    { x0: right - LEGEND.w * k, y0: bottom - Math.max(1, rackCount) * LEGEND.row * k, x1: right, y1: bottom },
    { x0: vb.x, y0: bottom - TABLE_CORNER.h * k, x1: vb.x + TABLE_CORNER.w * k, y1: bottom },
    { x0: vb.x, y0: vb.y, x1: vb.x + BUTTONS.w * k, y1: vb.y + BUTTONS.h * k },
  ]
}

const overlaps = (a: Rect, b: Rect) => a.x0 < b.x1 + GAP && b.x0 < a.x1 + GAP && a.y0 < b.y1 + GAP && b.y0 < a.y1 + GAP

/**
 * Extra lift for each label box, in order (back of the scene first): a box touching a fixed zone or
 * an earlier label moves up until it touches nothing. Boxes that touch nothing stay put.
 */
export function spreadLabels(boxes: Rect[], fixed: Rect[]): number[] {
  const placed = [...fixed]
  return boxes.map((b) => {
    let lift = 0, cur = b
    for (let guard = 0; guard < 500; guard++) {
      const hit = placed.find((p) => overlaps(cur, p))
      if (!hit) break
      const dy = cur.y1 - (hit.y0 - GAP)
      lift += dy
      cur = { ...cur, y0: cur.y0 - dy, y1: cur.y1 - dy }
    }
    placed.push(cur)
    return lift
  })
}

function placeLabels(width: number, depth: number, angle: number, seats: Seat[], project: Layout['project'], zones: Rect[]): SeatLabel[] {
  const { turn } = turner(width, depth, angle)
  const anchors = seats.map((s) => project(s.x + DESK.w / 2, s.y + DESK.d / 2, 1.8))
  const order = seats.map((s, i) => [i, (([u, v]) => u + v)(turn(s.x + DESK.w / 2, s.y + DESK.d / 2))] as const).sort((a, b) => a[1] - b[1] || a[0] - b[0]).map(([i]) => i)
  const boxes = order.map((i): Rect => ({ x0: anchors[i][0] - LABEL_HALF, x1: anchors[i][0] + LABEL_HALF, y0: anchors[i][1] - LABEL_LIFT - LABEL_TEXT_H, y1: anchors[i][1] - LABEL_LIFT }))
  const lifts = spreadLabels(boxes, zones)
  const out: SeatLabel[] = new Array(seats.length)
  order.forEach((i, k) => {
    const b = boxes[k], l = lifts[k]
    const box = { x0: b.x0, x1: b.x1, y0: round(b.y0 - l), y1: round(b.y1 - l) }
    out[i] = { x: anchors[i][0], y: box.y1, box }
  })
  return out
}

/** Fixed frame: bounds over every angle (floor, racks, labels once spread), so nothing jumps while turning. */
function fixedFrame(width: number, depth: number, seats: Seat[], racks: { x: number; y: number }[], rackCount: number, projector: Projector): Frame {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  const grow = (p: Pt) => { minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]); minY = Math.min(minY, p[1]); maxY = Math.max(maxY, p[1]) }
  for (let a = 0; a < 360; a += SAMPLE_STEP) {
    const p = projector(a)
    for (const [cx, cy] of [[0, 0], [width, 0], [0, depth], [width, depth]]) { grow(p(cx, cy, -0.35)); grow(p(cx, cy, 0)) }
    for (const r of racks) for (const [dx, dy] of [[0, 0], [RACK.w, 0], [0, RACK.d], [RACK.w, RACK.d]]) grow(p(r.x + dx, r.y + dy, RACK.h))
  }
  // label boxes unspread give the horizontal extent and a first top
  const unspread = (a: number) => placeLabels(width, depth, a, seats, projector(a), [])
  let labelTop = Infinity
  for (let a = 0; a < 360; a += SAMPLE_STEP) for (const { box } of unspread(a)) { minX = Math.min(minX, box.x0); maxX = Math.max(maxX, box.x1); labelTop = Math.min(labelTop, box.y0) }
  let vb: Frame = { x: round(minX - PAD), y: round(Math.min(minY, labelTop) - PAD), w: round(maxX - minX + 2 * PAD), h: 0 }
  vb.h = round(maxY + PAD - vb.y)
  // Spread labels can rise above that; the zones depend on the frame, so settle it in a few passes.
  for (let pass = 0; pass < 8; pass++) {
    const zones = zonesOf(vb, rackCount)
    let top = vb.y + PAD
    for (let a = 0; a < 360; a += LABEL_STEP) for (const { box } of placeLabels(width, depth, a, seats, projector(a), zones)) top = Math.min(top, box.y0)
    if (top >= vb.y + PAD - 0.05) break
    const y = round(top - PAD)
    vb = { ...vb, y, h: round(vb.h + (vb.y - y)) }
  }
  return vb
}

const pts = (list: Pt[]) => list.map((p) => `${p[0]},${p[1]}`).join(' ')

const NORMALS: Record<Dir, Pt> = { '+y': [0, 1], '+x': [1, 0], '-x': [-1, 0], '-y': [0, -1] }

/** Top face plus the side faces that look towards the viewer at the layout's angle. */
export function box(l: Pick<Layout, 'project' | 'angle' | 'sees'>, x: number, y: number, z: number, w: number, d: number, h: number): Box {
  const p = l.project, t = z + h
  const faces: Record<Dir, Pt[]> = {
    '+y': [p(x, y + d, t), p(x + w, y + d, t), p(x + w, y + d, z), p(x, y + d, z)],
    '+x': [p(x + w, y, t), p(x + w, y + d, t), p(x + w, y + d, z), p(x + w, y, z)],
    '-x': [p(x, y, t), p(x, y + d, t), p(x, y + d, z), p(x, y, z)],
    '-y': [p(x, y, t), p(x + w, y, t), p(x + w, y, z), p(x, y, z)],
  }
  const sides: Side[] = []
  for (const dir of ['+y', '+x', '-x', '-y'] as const) {
    const [nx, ny] = NORMALS[dir]
    if (!l.sees(nx, ny)) continue
    const [u, v] = [nx * Math.cos(radians(l.angle)) - ny * Math.sin(radians(l.angle)), nx * Math.sin(radians(l.angle)) + ny * Math.cos(radians(l.angle))]
    sides.push({ dir, points: pts(faces[dir]), shade: u - v < 0 ? 'f-left' : 'f-right' })
  }
  return { top: pts([p(x, y, t), p(x + w, y, t), p(x + w, y + d, t), p(x, y + d, t)]), sides }
}

/** Seats, racks and table from the back of the scene to the front, for the painter's algorithm. */
export function drawOrder(l: Layout): DrawItem[] {
  const items: DrawItem[] = [
    ...l.seats.map((s, index): DrawItem => ({ kind: 'seat', index, x: s.x, y: s.y, w: DESK.w, d: DESK.d })),
    ...l.racks.map((r, index): DrawItem => ({ kind: 'rack', index, x: r.x, y: r.y, w: RACK.w, d: RACK.d })),
    { kind: 'table', index: 0, ...l.table },
  ]
  const key = (o: DrawItem) => l.depthOf(o.x + o.w / 2, o.y + o.d / 2)
  return items.map((o) => [key(o), o] as const).sort((a, b) => a[0] - b[0]).map(([, o]) => o)
}

/** Nearest multiple of 90, ties going up; never -0. */
export function nearestQuarter(angle: number): number {
  return Math.floor(angle / 90 + 0.5) * 90 + 0
}

export function toPercent(layout: Layout, p: Pt): readonly [number, number] {
  const { x, y, w, h } = layout.viewBox
  return [((p[0] - x) / w) * 100, ((p[1] - y) / h) * 100]
}
