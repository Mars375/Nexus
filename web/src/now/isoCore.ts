/*
 * Shared floor types, dimensions and label geometry (#6, #30): the rotation helper, the label
 * descriptors (seatItems, rackItems) and the label placement/spread. The floor plans themselves live
 * in iso.ts (layoutFloor, office floor) and isoServerRoom.ts (serverRoom). Floor units: a desk is
 * 3 x 1.5. The screen only reads the plan; the angle changes the projection, never the ground plan.
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
export const UNIT = 26
export const A = Math.cos(Math.PI / 6) * UNIT
export const B = Math.sin(Math.PI / 6) * UNIT
export const PITCH = 4 // un poste tous les 4 unités sur une rangée
export const ORIGIN = { x: 150, y: 110 } // coin gauche du sol à 0° ; fixe pour que le plan à 0° garde ses coordonnées
export const PAD = 12
export const RACK_START = 0.8
export const RACK_PITCH = 1.85
export const RACK_MARGIN = 0.5
export const RACK_COLUMN_PITCH = 3.6 // wide enough that the outer column never hides the LED face of the inner one (tested at the quarters)
export const FLOOR_DEPTH = 14
// Racks per column so the last one still ends RACK_MARGIN before the back edge (7 at depth 14).
export const RACK_PER_COLUMN = Math.floor((FLOOR_DEPTH - RACK_MARGIN - RACK.d - RACK_START) / RACK_PITCH) + 1
// Room taken by label text around its anchor, in viewBox units (labels keep their px size).
const LABEL_HALF = 110
const LABEL_TEXT_H = 42
// Three lines (40 px) on a height-limited stage (min 560 px for a frame about 1060 units tall: 0.53 px per unit, 75 units) minus the gap.
const RACK_LABEL_H = 71
const GAP = 6
export const SAMPLE_STEP = 5
export const LABEL_STEP = 1

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
export const LEGEND_MAX_ROWS = 4

// Server room (floors above the office): same footprint as floor 1, so the frame and the building stay put (#36).
// Static dressing only (cooling units, cable tray, floor markings): never anything that looks like a measurement.
export const COOLING = { w: 1.8, h: RACK.h }
export const END_GAP = 0.45 // between the row of racks and a cooling unit, as between two racks
export const AISLE_DEPTH = 2.8
export const TRAY = { d: 0.6, h: 0.12, lift: 0.35 }
export const ROOM_MAX_RACKS = 4
// Rack LEDs: five lights per face, the first with its top edge at LED_TOP, one every LED_STEP.
export const LED_TOP = 2.1
export const LED_STEP = 0.38

/** Rounds to one decimal, so projected coordinates stay stable and compact. */
export const round = (v: number) => Math.round(v * 10) / 10
/** Degrees to radians. */
export const radians = (deg: number) => (deg * Math.PI) / 180

/** Rotation by `angle` degrees around the floor centre, for points and for face normals. */
export function turner(width: number, depth: number, angle: number) {
  const c = Math.cos(radians(angle)), s = Math.sin(radians(angle)), cx = width / 2, cy = depth / 2
  const turn = (x: number, y: number): Pt => [cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c]
  const normal = (nx: number, ny: number): Pt => [nx * c - ny * s, nx * s + ny * c]
  return { turn, normal }
}

export const NORMALS: Record<Dir, Pt> = { '+y': [0, 1], '+x': [1, 0], '-x': [-1, 0], '-y': [0, -1] }

/** Screen corners kept free for the legend, « TA TABLE » and the rotation buttons, in plan units at the smallest render. */
export function zonesOf(vb: { x: number; y: number; w: number; h: number }, legendRows: number, selector: boolean): Rect[] {
  const k = vb.w / MIN_FLOOR_PX // plan units per px at the smallest render
  const right = vb.x + vb.w, bottom = vb.y + vb.h
  return [
    { x0: right - LEGEND.w * k, y0: bottom - legendRows * LEGEND.row * k, x1: right, y1: bottom },
    { x0: vb.x, y0: bottom - TABLE_CORNER.h * k, x1: vb.x + TABLE_CORNER.w * k, y1: bottom },
    { x0: vb.x, y0: vb.y, x1: vb.x + (selector ? Math.max(BUTTONS.w, SELECTOR.w) : BUTTONS.w) * k, y1: vb.y + (BUTTONS.h + (selector ? SELECTOR.h : 0)) * k },
  ]
}

const EPS = 0.01 // boxes that only touch at the gap are not overlapping
/** True when two boxes touch or come within the label gap of each other. */
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
export type Labelled = { x: number; y: number; w: number; d: number; top: number; refX: number; textH?: number }

/** A label sits under its object when its row is nearer the viewer than the floor centre. */
function labelBelow(width: number, depth: number, angle: number, item: Labelled): boolean {
  const { turn } = turner(width, depth, angle)
  const [u, v] = turn(item.refX, item.y + item.d / 2), [cu, cv] = turn(width / 2, depth / 2)
  return u + v - (cu + cv) > 1e-9
}

/** Label descriptors of the desks: the row depth is read at the floor's middle column. */
export const seatItems = (width: number, seats: Seat[]): Labelled[] => seats.map((s) => ({ x: s.x, y: s.y, w: DESK.w, d: DESK.d, top: 1.8, refX: width / 2 }))
// Racks in a row: each one is read at its own place along the row; the leader starts above the cable tray.
/** Label descriptors of a row of racks: each read at its own place, the leader starting above the cable tray. */
export const rackItems = (racks: { x: number; y: number }[]): Labelled[] => racks.map((r) => ({ x: r.x, y: r.y, w: RACK.w, d: RACK.d, top: RACK.h + 0.6, refX: r.x + RACK.w / 2, textH: RACK_LABEL_H }))

/** Labels at `angle`: above or under their object by row depth, then spread so none covers another or a fixed corner. */
export function placeLabels(width: number, depth: number, angle: number, items: Labelled[], project: Layout['project'], zones: Rect[]): SeatLabel[] {
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
