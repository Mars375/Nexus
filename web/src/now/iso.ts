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
/**
 * Estimated label of a seat. The leader runs from `anchor` (on the desk) to (x, y), the edge of the
 * box nearest the desk: its bottom when the label is above the desk, its top when `below`.
 */
export type SeatLabel = { x: number; y: number; anchor: Pt; below: boolean; box: Rect }
export type DrawItem = { kind: 'seat' | 'rack' | 'table'; index: number; x: number; y: number; w: number; d: number }

export const DESK = { w: 3, d: 1.5, h: 0.75 }
export const RACK = { w: 1.4, d: 1.4, h: 2.4 }
// Offset (screen units) between a desk's label anchor and its label: clears the neighbouring monitor.
export const LABEL_LIFT = 40
// Same, for the row nearest the viewer: label under the desk.
export const LABEL_DROP = 26
const UNIT = 26
const A = Math.cos(Math.PI / 6) * UNIT
const B = Math.sin(Math.PI / 6) * UNIT
const PITCH = 4 // un poste tous les 4 unités sur une rangée
const ORIGIN = { x: 150, y: 110 } // coin gauche du sol à 0° ; fixe pour que le plan à 0° garde ses coordonnées
const PAD = 12
const RACK_START = 0.8
const RACK_PITCH = 1.85
const RACK_MARGIN = 0.5
const RACK_COLUMN_PITCH = 3.6 // wide enough that the outer column never hides the LED face of the inner one (tested at the quarters)
const FLOOR_DEPTH = 14
// Racks per column so the last one still ends RACK_MARGIN before the back edge (7 at depth 14).
const RACK_PER_COLUMN = Math.floor((FLOOR_DEPTH - RACK_MARGIN - RACK.d - RACK_START) / RACK_PITCH) + 1
// Room taken by label text around its anchor, in viewBox units (labels keep their px size).
const LABEL_HALF = 110
const LABEL_TEXT_H = 42
// Three lines (40 px) on a height-limited stage (min 560 px for a frame about 1060 units tall: 0.53 px per unit, 75 units) minus the gap.
const RACK_LABEL_H = 71
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
// Floor selector (up/down buttons, « Étage n / N » and its alert line), under the rotation buttons once there are several floors.
const SELECTOR = { w: 210, h: 40 }
// The legend lists the racks of the floor shown: four at most, however many nodes there are.
const LEGEND_MAX_ROWS = 4

// Server room (floors above the office): same footprint as floor 1, so the frame and the building stay put (#36).
// Static dressing only (cooling units, cable tray, floor markings): never anything that looks like a measurement.
const COOLING = { w: 1.8, h: RACK.h }
const END_GAP = 0.45 // between the row of racks and a cooling unit, as between two racks
const AISLE_DEPTH = 2.8
const TRAY = { d: 0.6, h: 0.12, lift: 0.35 }
const ROOM_MAX_RACKS = 4
// Rack LEDs: five lights per face, the first with its top edge at LED_TOP, one every LED_STEP.
export const LED_TOP = 2.1
export const LED_STEP = 0.38

const round = (v: number) => Math.round(v * 10) / 10
const radians = (deg: number) => (deg * Math.PI) / 180

/** Rotation by `angle` degrees around the floor centre, for points and for face normals. */
function turner(width: number, depth: number, angle: number) {
  const c = Math.cos(radians(angle)), s = Math.sin(radians(angle)), cx = width / 2, cy = depth / 2
  const turn = (x: number, y: number): Pt => [cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c]
  const normal = (nx: number, ny: number): Pt => [nx * c - ny * s, nx * s + ny * c]
  return { turn, normal }
}

/** Plan of the floor for `agentCount` seats and `rackCount` racks, projected at `angle` degrees inside a frame that does not depend on the angle. */
export function layoutFloor(agentCount: number, rackCount: number, angle = 0, floorCount = 1): Layout {
  const perRow = Math.max(4, Math.ceil(agentCount / 2))
  const rowWidth = perRow * PITCH
  // Racks fill columns of at most RACK_PER_COLUMN, outermost column first; each extra column widens the floor.
  const rackColumns = Math.max(1, Math.ceil(rackCount / RACK_PER_COLUMN))
  const serverWidth = rackCount > 0 ? 3.2 + (rackColumns - 1) * RACK_COLUMN_PITCH : 0
  const width = rowWidth + 1 + serverWidth
  const depth = FLOOR_DEPTH
  const seats: Seat[] = []
  for (let i = 0; i < agentCount; i++) {
    const back = i < perRow
    const col = back ? i : i - perRow
    seats.push({ x: 1.2 + col * PITCH, y: back ? 1.4 : 10.8, back })
  }
  // table centrée sur l'étendue réelle des postes
  const first = 1.2, last = 1.2 + (perRow - 1) * PITCH + DESK.w
  const table = { w: 5, d: 3.2, x: (first + last) / 2 - 2.5, y: 5.4 }
  const perColumn = Math.ceil(rackCount / rackColumns)
  const racks = Array.from({ length: rackCount }, (_, i) => ({ x: width - 2.1 - Math.floor(i / perColumn) * RACK_COLUMN_PITCH, y: RACK_START + (i % perColumn) * RACK_PITCH }))

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

  const legendRows = Math.max(1, Math.min(rackCount, LEGEND_MAX_ROWS))
  const selector = floorCount > 1
  const key = `${agentCount}:${rackCount}:${selector}`
  let vb = frames.get(key)
  if (!vb) {
    vb = fixedFrame(width, depth, seats, racks, legendRows, selector, projector)
    frames.set(key, vb)
  }
  const viewBox = vb
  const zones = zonesOf(viewBox, legendRows, selector)
  const labels = placeLabels(width, depth, angle, seatItems(width, seats), projector(angle), zones)

  const { turn, normal } = turner(width, depth, angle)
  const sees = (nx: number, ny: number) => { const [u, v] = normal(nx, ny); return u + v > 1e-9 }
  const depthOf = (x: number, y: number) => { const [u, v] = turn(x, y); return u + v }
  return { width, depth, angle, seats, table, racks, viewBox, project: projector(angle), labels, zones, depthOf, sees }
}

type Frame = Layout['viewBox']
type Projector = (a: number) => Layout['project']
const frames = new Map<string, Frame>()

/** Screen corners kept free for the legend, « TA TABLE » and the rotation buttons, in plan units at the smallest render. */
function zonesOf(vb: Frame, legendRows: number, selector: boolean): Rect[] {
  const k = vb.w / MIN_FLOOR_PX // plan units per px at the smallest render
  const right = vb.x + vb.w, bottom = vb.y + vb.h
  return [
    { x0: right - LEGEND.w * k, y0: bottom - legendRows * LEGEND.row * k, x1: right, y1: bottom },
    { x0: vb.x, y0: bottom - TABLE_CORNER.h * k, x1: vb.x + TABLE_CORNER.w * k, y1: bottom },
    { x0: vb.x, y0: vb.y, x1: vb.x + (selector ? Math.max(BUTTONS.w, SELECTOR.w) : BUTTONS.w) * k, y1: vb.y + (BUTTONS.h + (selector ? SELECTOR.h : 0)) * k },
  ]
}

const EPS = 0.01 // boxes that only touch at the gap are not overlapping
const overlaps = (a: Rect, b: Rect) => a.x0 < b.x1 + GAP - EPS && b.x0 < a.x1 + GAP - EPS && a.y0 < b.y1 + GAP - EPS && b.y0 < a.y1 + GAP - EPS

/**
 * Shift of each label box away from its desk, in order (back of the scene first): up for a label above
 * its desk, down for a label below (`below[i]`). A box touching a fixed zone or an earlier label moves
 * the least that clears it; boxes that touch nothing stay put.
 */
export function spreadLabels(boxes: Rect[], fixed: Rect[], below: boolean[] = []): number[] {
  const placed = [...fixed]
  return boxes.map((b, i) => {
    let shift = 0, cur = b
    for (let guard = 0; guard < 500; guard++) {
      const hit = placed.find((p) => overlaps(cur, p))
      if (!hit) break
      const dy = below[i] ? hit.y1 + GAP - cur.y0 : cur.y1 - (hit.y0 - GAP) // distance to clear it, away from the desk
      shift += dy
      const move = below[i] ? dy : -dy
      cur = { ...cur, y0: cur.y0 + move, y1: cur.y1 + move }
    }
    placed.push(cur)
    return shift
  })
}

/** Something that carries an HTML label: its footprint, the height the leader starts from, and where its row depth is read. */
type Labelled = { x: number; y: number; w: number; d: number; top: number; refX: number; textH?: number }

/** A label sits under its object when its row is nearer the viewer than the floor centre. */
function labelBelow(width: number, depth: number, angle: number, item: Labelled): boolean {
  const { turn } = turner(width, depth, angle)
  const [u, v] = turn(item.refX, item.y + item.d / 2), [cu, cv] = turn(width / 2, depth / 2)
  return u + v - (cu + cv) > 1e-9
}

const seatItems = (width: number, seats: Seat[]): Labelled[] => seats.map((s) => ({ x: s.x, y: s.y, w: DESK.w, d: DESK.d, top: 1.8, refX: width / 2 }))
// Racks in a row: each one is read at its own place along the row; the leader starts above the cable tray.
const rackItems = (racks: { x: number; y: number }[]): Labelled[] => racks.map((r) => ({ x: r.x, y: r.y, w: RACK.w, d: RACK.d, top: RACK.h + 0.6, refX: r.x + RACK.w / 2, textH: RACK_LABEL_H }))

/** Labels at `angle`: above or under their object by row depth, then spread so none covers another or a fixed corner. */
function placeLabels(width: number, depth: number, angle: number, items: Labelled[], project: Layout['project'], zones: Rect[]): SeatLabel[] {
  const { turn } = turner(width, depth, angle)
  const below = items.map((s) => labelBelow(width, depth, angle, s))
  const anchors = items.map((s, i): Pt => {
    const cx = s.x + s.w / 2, cy = s.y + s.d / 2
    if (!below[i]) return project(cx, cy, s.top)
    // lowest point of the footprint on screen, under its centre
    const low = Math.max(...[[s.x, s.y], [s.x + s.w, s.y], [s.x, s.y + s.d], [s.x + s.w, s.y + s.d]].map(([x, y]) => project(x, y, 0)[1]))
    return [project(cx, cy, 0)[0], low]
  })
  const order = items.map((s, i) => [i, (([u, v]) => u + v)(turn(s.x + s.w / 2, s.y + s.d / 2))] as const).sort((a, b) => a[1] - b[1] || a[0] - b[0]).map(([i]) => i)
  const boxes = order.map((i): Rect => {
    const [ax, ay] = anchors[i]
    return below[i]
      ? { x0: ax - LABEL_HALF, x1: ax + LABEL_HALF, y0: ay + LABEL_DROP, y1: ay + LABEL_DROP + (items[i].textH ?? LABEL_TEXT_H) }
      : { x0: ax - LABEL_HALF, x1: ax + LABEL_HALF, y0: ay - LABEL_LIFT - (items[i].textH ?? LABEL_TEXT_H), y1: ay - LABEL_LIFT }
  })
  const shifts = spreadLabels(boxes, zones, order.map((i) => below[i]))
  const out: SeatLabel[] = new Array(items.length)
  order.forEach((i, k) => {
    const b = boxes[k], d = below[i] ? shifts[k] : -shifts[k]
    const box = { x0: b.x0, x1: b.x1, y0: round(b.y0 + d), y1: round(b.y1 + d) }
    out[i] = { x: anchors[i][0], y: below[i] ? box.y0 : box.y1, anchor: anchors[i], below: below[i], box }
  })
  return out
}

/** Fixed frame: bounds over every angle (floor, racks, labels once spread), so nothing jumps while turning. */
function fixedFrame(width: number, depth: number, seats: Seat[], racks: { x: number; y: number }[], legendRows: number, selector: boolean, projector: Projector): Frame {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  const grow = (p: Pt) => { minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]); minY = Math.min(minY, p[1]); maxY = Math.max(maxY, p[1]) }
  for (let a = 0; a < 360; a += SAMPLE_STEP) {
    const p = projector(a)
    for (const [cx, cy] of [[0, 0], [width, 0], [0, depth], [width, depth]]) { grow(p(cx, cy, -0.35)); grow(p(cx, cy, 0)) }
    for (const r of racks) for (const [dx, dy] of [[0, 0], [RACK.w, 0], [0, RACK.d], [RACK.w, RACK.d]]) grow(p(r.x + dx, r.y + dy, RACK.h))
    // The server room lies inside floor 1's footprint, so this grows nothing today: it keeps the frame honest if the room changes.
    for (let n = 1; n <= ROOM_MAX_RACKS; n++) {
      const g = serverRoom(width, depth, n)
      for (const [cx, cy] of [[g.room.x, g.room.y], [g.room.x + g.room.w, g.room.y], [g.room.x, g.room.y + g.room.d], [g.room.x + g.room.w, g.room.y + g.room.d]]) { grow(p(cx, cy, -0.35)); grow(p(cx, cy, 0)) }
      for (const r of g.racks) for (const [dx, dy] of [[0, 0], [RACK.w, 0], [0, RACK.d], [RACK.w, RACK.d]]) grow(p(r.x + dx, r.y + dy, RACK.h))
      for (const u of g.units) for (const [dx, dy] of [[0, 0], [u.w, 0], [0, u.d], [u.w, u.d]]) grow(p(u.x + dx, u.y + dy, u.h))
      for (const [dx, dy] of [[0, 0], [g.tray.w, 0], [0, g.tray.d], [g.tray.w, g.tray.d]]) { grow(p(g.tray.x + dx, g.tray.y + dy, g.tray.z)); grow(p(g.tray.x + dx, g.tray.y + dy, g.tray.z + g.tray.h)) }
    }
  }
  // label boxes unspread give the horizontal extent and a first top
  // With several floors, the racks' labels (one set per rack count) must fit too: floors share one frame.
  const sets: { items: Labelled[]; rooms: boolean }[] = [{ items: seatItems(width, seats), rooms: false }, ...(selector ? [1, 2, 3, 4].map((n) => ({ items: rackItems(serverRoom(width, depth, n).racks), rooms: true })) : [])]
  const unspread = (a: number) => sets.flatMap(({ items }) => placeLabels(width, depth, a, items, projector(a), []))
  let labelTop = Infinity, labelBottom = -Infinity
  for (let a = 0; a < 360; a += SAMPLE_STEP) for (const { box } of unspread(a)) { minX = Math.min(minX, box.x0); maxX = Math.max(maxX, box.x1); labelTop = Math.min(labelTop, box.y0); labelBottom = Math.max(labelBottom, box.y1) }
  const top0 = Math.min(minY, labelTop) - PAD, bottom0 = Math.max(maxY, labelBottom) + PAD
  let vb: Frame = { x: round(minX - PAD), y: round(top0), w: round(maxX - minX + 2 * PAD), h: round(bottom0 - top0) }
  // Spread labels can go further up or down than that; the zones depend on the frame, so settle it in a few passes.
  for (let pass = 0; pass < 8; pass++) {
    const zones = zonesOf(vb, legendRows, selector)
    let top = vb.y + PAD, bottom = vb.y + vb.h - PAD
    for (let a = 0; a < 360; a += LABEL_STEP) for (const { box } of sets.flatMap(({ items, rooms }) => placeLabels(width, depth, a, items, projector(a), rooms ? [...zones, markRect(width, depth, a, projector(a))] : zones))) { top = Math.min(top, box.y0); bottom = Math.max(bottom, box.y1) }
    if (top >= vb.y + PAD - 0.05 && bottom <= vb.y + vb.h - PAD + 0.05) break
    const y = round(top - PAD)
    vb = { ...vb, y, h: round(bottom + PAD - y) }
  }
  return vb
}

export type PlanRect = { x: number; y: number; w: number; d: number }
export type ServerFloor = {
  /** The whole floor: exactly floor 1's footprint. */
  room: PlanRect
  racks: { x: number; y: number }[]
  /** Cold aisle in front of the LED side (+y, perforated tiles), hot aisle behind: same size, along the row. */
  aisles: { cold: PlanRect; hot: PlanRect }
  /** Cooling units at each end of a row of four: fixed, whatever the rack count. */
  units: (PlanRect & { h: number })[]
  /** Cable tray above the racks and units: a thin box, as long as the row of four plus both units. */
  tray: PlanRect & { z: number; h: number }
  /** Floor markings (the working zone around the row), as plan segments. */
  markings: [Pt, Pt][]
  /** Floor point where the « ÉTAGE n » mark is laid, in the aisle nearer to the viewer. */
  markerAt: Pt
  /** matrix(a b c d e f) taking plan units to the screen on the ground (z = 0): the mark turns with the floor. */
  marker: readonly [number, number, number, number, number, number]
  /** True when the mark must be turned 180° about `markerAt` to read left to right. */
  markerFlip: boolean
  /** Side of the racks carrying the LEDs: +y when it faces the viewer, else -y; never ±x, which a neighbour can hide. */
  ledFace: Dir
  /** One label per rack, placed and spread like the desks' (none touches another or a fixed corner). */
  labels: SeatLabel[]
}

/** Fixed geometry of a server room on the floor of `width` × `depth`: the whole floor, the row centred on its centre (the rotation centre). */
function serverRoom(width: number, depth: number, rackCount: number) {
  const cx = width / 2, cy = depth / 2, pitch = RACK_PITCH
  const row = (n: number) => (n - 1) * pitch + RACK.w
  const room: PlanRect = { x: 0, y: 0, w: width, d: depth }
  const racks = Array.from({ length: rackCount }, (_, i) => ({ x: cx - row(rackCount) / 2 + i * pitch, y: cy - RACK.d / 2 }))
  const half = row(ROOM_MAX_RACKS) / 2 + END_GAP
  const units = [cx - half - COOLING.w, cx + half].map((x) => ({ x, y: cy - RACK.d / 2, w: COOLING.w, d: RACK.d, h: COOLING.h }))
  const zone = { x: units[0].x, w: units[1].x + COOLING.w - units[0].x }
  const aisles = { hot: { x: zone.x, y: cy - RACK.d / 2 - AISLE_DEPTH, w: zone.w, d: AISLE_DEPTH }, cold: { x: zone.x, y: cy + RACK.d / 2, w: zone.w, d: AISLE_DEPTH } }
  const tray = { x: zone.x, y: cy - TRAY.d / 2, w: zone.w, d: TRAY.d, z: RACK.h + TRAY.lift, h: TRAY.h }
  const [y0, y1] = [aisles.hot.y - 0.5, aisles.cold.y + aisles.cold.d + 0.5]
  const markings: [Pt, Pt][] = [[[zone.x, y0], [zone.x + zone.w, y0]], [[zone.x, y1], [zone.x + zone.w, y1]], [[zone.x, y0], [zone.x, y1]], [[zone.x + zone.w, y0], [zone.x + zone.w, y1]]]
  return { room, racks, aisles, units, tray, markings }
}

// Floor units the « ÉTAGE n » mark covers around its anchor (with a little margin): rack labels keep clear of it.
const MARK = { halfW: 2.6, halfD: 0.7 }

/** Screen box of the floor mark at `angle`, on the aisle nearer to the viewer (the same choice as `layoutServerFloor`). */
function markRect(width: number, depth: number, angle: number, project: Layout['project']): Rect {
  const g = serverRoom(width, depth, 1), { turn } = turner(width, depth, angle)
  const mid = (r: PlanRect): Pt => [r.x + r.w / 2, r.y + r.d / 2]
  const depthOf = (p: Pt) => { const [u, v] = turn(...p); return u + v }
  const cold = mid(g.aisles.cold), hot = mid(g.aisles.hot)
  const at = depthOf(cold) >= depthOf(hot) ? cold : hot
  const pts = [[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([sx, sy]) => project(at[0] + sx * MARK.halfW, at[1] + sy * MARK.halfD, 0))
  return { x0: Math.min(...pts.map((q) => q[0])), y0: Math.min(...pts.map((q) => q[1])), x1: Math.max(...pts.map((q) => q[0])), y1: Math.max(...pts.map((q) => q[1])) }
}

/** Server room for `rackCount` racks (1 to 4), reusing the projection, angle and frame of the floor-1 layout. */
export function layoutServerFloor(base: Layout, rackCount: number): ServerFloor {
  const g = serverRoom(base.width, base.depth, rackCount)
  // Laid on the aisle nearer to the viewer, so the racks (behind it) never hide the mark.
  const centre = (r: PlanRect): Pt => [r.x + r.w / 2, r.y + r.d / 2]
  const cold = centre(g.aisles.cold), hot = centre(g.aisles.hot)
  const markerAt = base.depthOf(...cold) >= base.depthOf(...hot) ? cold : hot
  const o = base.project(0, 0), px = base.project(10, 0), py = base.project(0, 10)
  const marker = [(px[0] - o[0]) / 10, (px[1] - o[1]) / 10, (py[0] - o[0]) / 10, (py[1] - o[1]) / 10, o[0], o[1]] as const
  const ledFace: Dir = base.sees(0, 1) ? '+y' : base.sees(0, -1) ? '-y' : (['+x', '-x', '+y', '-y'] as const).find((d) => base.sees(...NORMALS[d])) ?? '+x'
  // The plan x axis is the reading direction: when it runs leftwards on screen the mark is turned half a turn.
  const labels = placeLabels(base.width, base.depth, base.angle, rackItems(g.racks), base.project, [...base.zones, markRect(base.width, base.depth, base.angle, base.project)])
  return { ...g, markerAt, marker, markerFlip: marker[0] < 0, ledFace, labels }
}

/** One indicator light on a rack side face, `z` being its top edge. */
export function ledQuad(l: Pick<Layout, 'project'>, r: { x: number; y: number }, dir: Dir, z: number): Pt[] {
  const along = [r.x + 0.25, r.x + 1.15], across = [r.y + 0.25, r.y + 1.15]
  const fixed = dir === '+x' ? r.x + RACK.w : dir === '-x' ? r.x : dir === '+y' ? r.y + RACK.d : r.y
  const at = (u: number, zz: number) => (dir === '+x' || dir === '-x' ? l.project(fixed, u, zz) : l.project(u, fixed, zz))
  const [a, b] = dir === '+x' || dir === '-x' ? across : along
  return [at(a, z), at(b, z), at(b, z - 0.16), at(a, z - 0.16)]
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

/** A point of the viewBox as percentages of its width and height, for HTML laid over the SVG. */
export function toPercent(layout: Layout, p: Pt): readonly [number, number] {
  const { x, y, w, h } = layout.viewBox
  return [((p[0] - x) / w) * 100, ((p[1] - y) / h) * 100]
}
