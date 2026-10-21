/*
 * Server rooms on the upper floors (#36): the plan of a room (racks, aisles, cooling units, cable
 * tray, floor markings), the « ÉTAGE n » mark and the full layout, reusing floor 1's frame. The rack
 * count follows the real nodes; only the decor (cooling units, cable tray, floor markings) is static
 * dressing, never anything that looks like a measurement.
 */
import {
  AISLE_DEPTH,
  COOLING,
  END_GAP,
  NORMALS,
  RACK,
  RACK_MARGIN,
  RACK_PITCH,
  ROOM_MAX_RACKS,
  TRAY,
  placeLabels,
  rackItems,
  turner,
  type Dir,
  type Layout,
  type Pt,
  type Rect,
  type SeatLabel,
} from './isoCore'

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
export function serverRoom(width: number, depth: number, rackCount: number) {
  const cx = width / 2, cy = depth / 2, pitch = RACK_PITCH
  const row = (n: number) => (n - 1) * pitch + RACK.w
  const room: PlanRect = { x: 0, y: 0, w: width, d: depth }
  const racks = Array.from({ length: rackCount }, (_, i) => ({ x: cx - row(rackCount) / 2 + i * pitch, y: cy - RACK.d / 2 }))
  const half = row(ROOM_MAX_RACKS) / 2 + END_GAP
  const units = [cx - half - COOLING.w, cx + half].map((x) => ({ x, y: cy - RACK.d / 2, w: COOLING.w, d: RACK.d, h: COOLING.h }))
  const zone = { x: units[0].x, w: units[1].x + COOLING.w - units[0].x }
  const aisles = { hot: { x: zone.x, y: cy - RACK.d / 2 - AISLE_DEPTH, w: zone.w, d: AISLE_DEPTH }, cold: { x: zone.x, y: cy + RACK.d / 2, w: zone.w, d: AISLE_DEPTH } }
  const tray = { x: zone.x, y: cy - TRAY.d / 2, w: zone.w, d: TRAY.d, z: RACK.h + TRAY.lift, h: TRAY.h }
  // Working zone around the row: the markings extend RACK_MARGIN past each aisle, the margin the racks leave before the back edge.
  const [y0, y1] = [aisles.hot.y - RACK_MARGIN, aisles.cold.y + aisles.cold.d + RACK_MARGIN]
  const markings: [Pt, Pt][] = [[[zone.x, y0], [zone.x + zone.w, y0]], [[zone.x, y1], [zone.x + zone.w, y1]], [[zone.x, y0], [zone.x, y1]], [[zone.x + zone.w, y0], [zone.x + zone.w, y1]]]
  return { room, racks, aisles, units, tray, markings }
}

// Floor units the « ÉTAGE n » mark covers around its anchor (with a little margin): rack labels keep clear of it.
const MARK = { halfW: 2.6, halfD: 0.7 }

/** Screen box of the floor mark at `angle`, on the aisle nearer to the viewer (the same choice as `layoutServerFloor`). */
export function markRect(width: number, depth: number, angle: number, project: Layout['project']): Rect {
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
