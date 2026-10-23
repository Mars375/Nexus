/*
 * SVG drawing helpers for the floor: boxes, rack LEDs, painter's order, quarter-turn rounding and
 * percentage conversion. Consumed through ./iso by Floor.tsx and ServerRoom.tsx, Rack.tsx (box,
 * ledQuad) and useFloorRotation.ts (nearestQuarter, which takes an angle rather than a Layout).
 */
import {
  DESK,
  NORMALS,
  RACK,
  radians,
  type Box,
  type Dir,
  type DrawItem,
  type Layout,
  type Pt,
  type Side,
} from './isoCore'

/** One indicator light on a rack side face, `z` being its top edge. */
export function ledQuad(l: Pick<Layout, 'project'>, r: { x: number; y: number }, dir: Dir, z: number): Pt[] {
  const along = [r.x + 0.25, r.x + 1.15], across = [r.y + 0.25, r.y + 1.15]
  const fixed = dir === '+x' ? r.x + RACK.w : dir === '-x' ? r.x : dir === '+y' ? r.y + RACK.d : r.y
  const at = (u: number, zz: number) => (dir === '+x' || dir === '-x' ? l.project(fixed, u, zz) : l.project(u, fixed, zz))
  const [a, b] = dir === '+x' || dir === '-x' ? across : along
  return [at(a, z), at(b, z), at(b, z - 0.16), at(a, z - 0.16)]
}

/** Points list of a polygon, as an SVG `points` attribute. */
const pts = (list: Pt[]) => list.map((p) => `${p[0]},${p[1]}`).join(' ')

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
