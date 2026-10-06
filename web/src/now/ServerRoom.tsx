import { RACK, box, layoutServerFloor, type Layout, type PlanRect } from './iso'
import { rackDetail, type RackView } from './model'
import { toPercent } from './iso'
import { Faces, Rack } from './Rack'

const TILE = { w: 1, d: 1.4 } // perforated floor tiles of the cold aisle, in floor units

/** Corner points of a flat rectangle on the ground, as an SVG points list. */
function flat(l: Layout, r: PlanRect, z = 0): string {
  return [l.project(r.x, r.y, z), l.project(r.x + r.w, r.y, z), l.project(r.x + r.w, r.y + r.d, z), l.project(r.x, r.y + r.d, z)].map((q) => q.join(',')).join(' ')
}

/** Tile joints of a rectangle, as one path. */
function joints(l: Layout, r: PlanRect): string {
  let d = ''
  for (let x = TILE.w; x < r.w - 1e-9; x += TILE.w) d += `M${l.project(r.x + x, r.y)} L${l.project(r.x + x, r.y + r.d)} `
  for (let y = TILE.d; y < r.d - 1e-9; y += TILE.d) d += `M${l.project(r.x, r.y + y)} L${l.project(r.x + r.w, r.y + y)} `
  return d.trim()
}

/**
 * A server room, drawn with the projection and angle of the office floor (`l`), on exactly its
 * footprint, so that nothing but what is drawn changes between floors. Racks are the only data:
 * everything else is static dressing (technical floor, aisles, markings, a cooling unit at each end
 * of the row, a cable tray) and carries no light, gauge or reading, so it can never pass for a measure.
 */
export function ServerRoom({ l, floor, racks }: { l: Layout; floor: number; racks: RackView[] }) {
  const g = layoutServerFloor(l, racks.length)
  const slab = box(l, g.room.x, g.room.y, -0.35, g.room.w, g.room.d, 0.35)
  const tray = box(l, g.tray.x, g.tray.y, g.tray.z, g.tray.w, g.tray.d, g.tray.h)
  const depth = (r: { x: number; y: number; w: number; d: number }) => l.depthOf(r.x + r.w / 2, r.y + r.d / 2)
  // Racks and cooling units share the painter's order.
  const items = [
    ...racks.map((r, i) => ({ key: r.node.id, d: depth({ ...g.racks[i], w: RACK.w, d: RACK.d }), rack: i, unit: -1 })),
    ...g.units.map((u, i) => ({ key: `unit-${i}`, d: depth(u), rack: -1, unit: i })),
  ].sort((a, b) => a.d - b.d || a.key.localeCompare(b.key))
  const grid = joints(l, g.room)
  const markings = g.markings.map(([a, b]) => `M${l.project(...a)} L${l.project(...b)}`).join(' ')
  return (
    <>
      <polygon className="floor-top" points={slab.top} />{slab.sides.map((s) => <polygon key={s.dir} className={s.shade === 'f-left' ? 'floor-left' : 'floor-right'} points={s.points} />)}
      <path className="floor-grid" d={grid} />
      <polygon className="aisle-hot" points={flat(l, g.aisles.hot)} />
      <polygon className="aisle-cold" points={flat(l, g.aisles.cold)} />
      <path className="floor-grid aisle-tiles" d={joints(l, g.aisles.cold)} />
      <path className="floor-marking" d={markings} />
      <text className="floor-marker" data-floor-mark={floor} transform={`matrix(${g.marker.join(' ')})${g.markerFlip ? ` rotate(180 ${g.markerAt[0]} ${g.markerAt[1]})` : ''}`} x={g.markerAt[0]} y={g.markerAt[1]} fontSize="1.1" textAnchor="middle" dominantBaseline="central">{`ÉTAGE ${floor}`}</text>
      {items.map((it) => {
        if (it.rack >= 0) return <Rack key={it.key} l={l} at={g.racks[it.rack]} node={racks[it.rack].node} tone={racks[it.rack].tone} face={g.ledFace} index={it.rack} />
        const u = g.units[it.unit]
        return (
          <g key={it.key} className="cooling">
            <Faces b={box(l, u.x, u.y, 0, u.w, u.d, u.h)} />
            <polygon className="cooling-grille" points={flat(l, { x: u.x + 0.25, y: u.y + 0.25, w: u.w - 0.5, d: u.d - 0.5 }, u.h)} />
          </g>
        )
      })}
      <g className="cable-tray"><Faces b={tray} /></g>
      {g.labels.map((lab, i) => <path key={racks[i].node.id} className="leader" d={`M${lab.anchor} L${lab.x} ${lab.y}`} />)}
    </>
  )
}

const NAME_TONE = (r: RackView): string => r.tone === 'off' ? (r.node.status === 'offline-by-design' ? 'text-unknown' : 'text-danger') : r.tone === 'unknown' ? 'text-attention' : ''

/**
 * HTML labels of a server floor's racks, laid like the desks' labels. Real data only: the name, the
 * state text of the model (« périmée » included), when an offline or unknown node was last seen, its guardian.
 * Purely visual (aria-hidden): the sr-only legend list is built from the same `rackDetail`, so screen readers lose nothing.
 */
export function RackLabels({ l, racks, now }: { l: Layout; racks: RackView[]; now: number }) {
  const g = layoutServerFloor(l, racks.length)
  return (
    <div aria-hidden="true">
      {racks.map((r, i) => {
        const lab = g.labels[i], [left, top] = toPercent(l, [lab.x, lab.y])
        const d = rackDetail(r, now)
        return (
          <div key={r.node.id} data-rack-label={r.node.id} className={`absolute whitespace-nowrap text-center -translate-x-1/2 ${lab.below ? 'translate-y-0' : '-translate-y-full'}`} style={{ left: `${left}%`, top: `${top}%` }}>
            <span data-line className={`block font-orbital-display text-[13px] font-semibold tracking-[0.14em] leading-[14px] ${NAME_TONE(r)}`}>{d.name}</span>
            <span data-line className="mx-auto block max-w-[34ch] truncate font-data text-[11px] leading-[13px] text-muted">{d.state}</span>
            <span data-line className="mx-auto hidden font-data text-[11px] leading-[13px] text-muted @min-[800px]:block">{d.guardian}</span>
          </div>
        )
      })}
    </div>
  )
}
