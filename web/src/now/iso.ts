/*
 * Public assembly of the Now floor: composes the office plan from isoCore,
 * the upper floors from isoServerRoom and the SVG primitives from isoRender.
 */
import {
  A,
  B,
  DESK,
  FLOOR_DEPTH,
  LABEL_STEP,
  LEGEND_MAX_ROWS,
  ORIGIN,
  PAD,
  PITCH,
  RACK,
  RACK_COLUMN_PITCH,
  RACK_PER_COLUMN,
  RACK_PITCH,
  RACK_START,
  ROOM_MAX_RACKS,
  SAMPLE_STEP,
  UNIT,
  placeLabels,
  rackItems,
  round,
  seatItems,
  turner,
  zonesOf,
  type Labelled,
  type Layout,
  type Pt,
  type Seat,
} from './isoCore'
import { markRect, serverRoom } from './isoServerRoom'

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

export { DESK, LABEL_DROP, LABEL_LIFT, LED_STEP, LED_TOP, RACK, spreadLabels } from './isoCore'
export { layoutServerFloor } from './isoServerRoom'
export { box, drawOrder, ledQuad, nearestQuarter, toPercent } from './isoRender'
export type { Box, Dir, DrawItem, Layout, Pt, Rect, Seat, SeatLabel, Side } from './isoCore'
export type { PlanRect, ServerFloor } from './isoServerRoom'
