import type { NodeState } from '@/api'
import { RACK, box, layoutServerFloor, type Layout, type PlanRect } from './iso'
import type { RackTone } from './model'
import { Faces, Rack } from './Rack'

const TILE = { w: 1, d: 1.4 } // perforated floor tiles of the cold aisle, in floor units

/** Corner points of a flat rectangle on the ground, as an SVG points list. */
function flat(l: Layout, r: PlanRect): string {
  return [l.project(r.x, r.y), l.project(r.x + r.w, r.y), l.project(r.x + r.w, r.y + r.d), l.project(r.x, r.y + r.d)].map((q) => q.join(',')).join(' ')
}

/** Tile joints of a rectangle, as one path. */
function joints(l: Layout, r: PlanRect): string {
  let d = ''
  for (let x = TILE.w; x < r.w - 1e-9; x += TILE.w) d += `M${l.project(r.x + x, r.y)} L${l.project(r.x + x, r.y + r.d)} `
  for (let y = TILE.d; y < r.d - 1e-9; y += TILE.d) d += `M${l.project(r.x, r.y + y)} L${l.project(r.x + r.w, r.y + y)} `
  return d.trim()
}

/**
 * A server room, drawn with the projection and angle of the office floor (`l`) so that nothing but
 * what is drawn changes between floors: a smaller floor, a cold and a hot aisle, one row of racks
 * under a cable tray, and the floor number laid on the cold aisle.
 */
export function ServerRoom({ l, floor, racks }: { l: Layout; floor: number; racks: { node: NodeState; tone: RackTone }[] }) {
  const g = layoutServerFloor(l, racks.length)
  const slab = box(l, g.room.x, g.room.y, -0.35, g.room.w, g.room.d, 0.35)
  const tray = box(l, g.tray.x, g.tray.y, g.tray.z, g.tray.w, g.tray.d, g.tray.h)
  const order = racks.map((_, i) => i).sort((a, b) => l.depthOf(g.racks[a].x + RACK.w / 2, g.racks[a].y + RACK.d / 2) - l.depthOf(g.racks[b].x + RACK.w / 2, g.racks[b].y + RACK.d / 2) || a - b)
  return (
    <>
      <polygon className="floor-top" points={slab.top} />{slab.sides.map((s) => <polygon key={s.dir} className={s.shade === 'f-left' ? 'floor-left' : 'floor-right'} points={s.points} />)}
      <polygon className="aisle-hot" points={flat(l, g.aisles.hot)} />
      <polygon className="aisle-cold" points={flat(l, g.aisles.cold)} />
      <path className="floor-grid" d={joints(l, g.aisles.cold)} />
      <text className="floor-marker" data-floor-mark={floor} transform={`matrix(${g.marker.join(' ')})`} x={g.markerAt[0]} y={g.markerAt[1]} fontSize="1.1" textAnchor="middle" dominantBaseline="central">{`ÉTAGE ${floor}`}</text>
      {order.map((i) => <Rack key={racks[i].node.id} l={l} at={g.racks[i]} node={racks[i].node} tone={racks[i].tone} face={g.ledFace} index={i} />)}
      <g className="cable-tray"><Faces b={tray} /></g>
    </>
  )
}
