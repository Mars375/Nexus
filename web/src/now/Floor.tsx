import clsx from 'clsx'
import type { DragEvent, ReactNode } from 'react'
import type { NodeState, NowSnapshot } from '@/api'
import { age } from '@/format'
import { isStale } from '@/freshness'
import { useNow } from '@/useNow'
import { DESK, RACK, box, drawOrder, layoutFloor, toPercent, type Box, type Dir, type Layout } from './iso'
import { AGE_TICK_MS, displayName, rackLabel, rackTone, seatModels, type RackTone, type SeatModel } from './model'
import { useArrivals } from './useArrivals'
import { useFloorRotation, type FloorStage } from './useFloorRotation'
import './floor.css'

const MAX_TICKETS = 3

/** Top face and visible side faces of one box. */
function Faces({ b, topClass }: { b: Box; topClass?: string }) {
  return (<><polygon className={clsx('f-top', topClass)} points={b.top} />{b.sides.map((s) => <polygon key={s.dir} className={s.shade} points={s.points} />)}</>)
}

/** Path of a request thread from a seat to the table, along the floor in right angles. */
function routePath(l: Layout, s: { x: number; y: number; back: boolean }): string {
  const sx = s.x + DESK.w / 2, sy = s.back ? s.y + DESK.d : s.y
  const ty = s.back ? l.table.y : l.table.y + l.table.d
  const tx = Math.min(Math.max(sx, l.table.x + 0.6), l.table.x + l.table.w - 0.6)
  const my = (sy + ty) / 2
  return 'M' + [l.project(sx, sy), l.project(sx, my), l.project(tx, my), l.project(tx, ty)].map((p) => p.join(' ')).join(' L ')
}

/** One seat: desk, monitor (its screen only when it faces the viewer), light pool and beacon showing its state. */
function Desk({ l, seat, m }: { l: Layout; seat: Layout['seats'][number]; m: SeatModel }) {
  const { x, y } = seat, p = l.project
  const deskBox = box(l, x, y, 0, DESK.w, DESK.d, DESK.h)
  const pool = p(x + DESK.w / 2, y + 2.3)
  const [bx, by0] = p(x + 0.55, y + 0.27, 1.66), [, by1] = p(x + 0.55, y + 0.27, 2.75)
  const screenPts = [p(x + 0.45, y + 0.28, 1.63), p(x + 2.55, y + 0.28, 1.63), p(x + 2.55, y + 0.28, 0.86), p(x + 0.45, y + 0.28, 0.86)].map((q) => q.join(',')).join(' ')
  return (
    <g className="desk" data-agent={m.agent} data-run={String(m.run)} data-wait={String(m.wait)} data-block={String(m.block)}>
      <ellipse className="pool" cx={pool[0]} cy={pool[1]} rx={2.4 * 22.5} ry={2.4 * 13} />
      <ellipse className="pool-att" cx={pool[0]} cy={pool[1]} rx={1.9 * 22.5} ry={1.9 * 13} />
      <Faces b={deskBox} topClass="desk-top" />
      <polygon className="desk-hatch" points={deskBox.top} />
      <Faces b={box(l, x + 0.35, y + 0.15, DESK.h, 2.3, 0.12, 0.95)} />
      {l.sees(0, 1) && <polygon className="screen" points={screenPts} />}
      <g className="beacon"><line x1={bx} y1={by0} x2={bx} y2={by1} /><polygon points={`${bx},${by1 - 7} ${bx + 6},${by1} ${bx},${by1 + 7} ${bx - 6},${by1}`} /></g>
    </g>
  )
}

const LED_FACES: Dir[] = ['+x', '-x', '+y', '-y']
const NORMAL: Record<Dir, readonly [number, number]> = { '+x': [1, 0], '-x': [-1, 0], '+y': [0, 1], '-y': [0, -1] }

/** One indicator light on a rack side face, `z` being its top edge. */
function ledPoints(l: Layout, r: { x: number; y: number }, dir: Dir, z: number): string {
  const along = [r.x + 0.25, r.x + 1.15], across = [r.y + 0.25, r.y + 1.15]
  const fixed = dir === '+x' ? r.x + RACK.w : dir === '-x' ? r.x : dir === '+y' ? r.y + RACK.d : r.y
  const at = (u: number, zz: number) => (dir === '+x' || dir === '-x' ? l.project(fixed, u, zz) : l.project(u, fixed, zz))
  const [a, b] = dir === '+x' || dir === '-x' ? across : along
  return [at(a, z), at(b, z), at(b, z - 0.16), at(a, z - 0.16)].map((q) => q.join(',')).join(' ')
}

type RackView = { node: NodeState; tone: RackTone; text: string }

type FloorProps = { snapshot: NowSnapshot; nodes: NodeState[] | undefined; nodesFailed?: boolean }

const ROTATE_BUTTON = 'pointer-events-auto grid size-9 place-items-center rounded-md border border-line bg-surface/80 text-base text-ink hover:bg-sunken focus-visible:outline-2 focus-visible:outline-accent'

/** The floor with its rotation: drag, arrow keys and two buttons; the angle settles on quarter turns. */
export function Floor(props: FloorProps) {
  const { angle, rotateBy, stage } = useFloorRotation()
  return (
    <FloorScene {...props} angle={angle} stage={stage}>
      <div className="absolute left-0 top-0 flex gap-1">
        <button type="button" className={ROTATE_BUTTON} aria-label="Tourner l'étage vers la gauche" onClick={() => rotateBy(-90)}><span aria-hidden="true">↺</span></button>
        <button type="button" className={ROTATE_BUTTON} aria-label="Tourner l'étage vers la droite" onClick={() => rotateBy(90)}><span aria-hidden="true">↻</span></button>
      </div>
    </FloorScene>
  )
}

/** The floor seen at `angle` degrees: pure drawing, the angle is owned by the caller. */
export function FloorScene({ snapshot, nodes, nodesFailed = false, angle, stage, children }: FloorProps & { angle: number; stage?: FloorStage; children?: ReactNode }) {
  const now = useNow(AGE_TICK_MS)
  const seats = seatModels(snapshot)
  // Une mesure trop ancienne, ou une relecture en échec : jamais de vert sur une donnée périmée.
  const racks: RackView[] = (nodes ?? []).map((node) => {
    const stale = nodesFailed || isStale(node.measured_at, 'nodes', now)
    return { node, tone: stale ? 'unknown' : rackTone(node), text: `${node.id.toUpperCase()} · ${stale ? 'périmée' : rackLabel(node)}` }
  })
  const l = layoutFloor(seats.length, nodes === undefined ? 1 : racks.length, angle) // la salle garde sa place pendant la lecture
  const freshAsks = useArrivals(snapshot.asks.map((q) => q.event))
  const freshRoutes = new Set(snapshot.asks.filter((q) => freshAsks.has(q.event)).map((q) => q.agent))
  const p = l.project
  const floor = box(l, 0, 0, -0.35, l.width, l.depth, 0.35)
  let grid = ''
  for (let i = 1; i < l.width; i++) grid += `M${p(i, 0)} L${p(i, l.depth)} `
  for (let j = 1; j < l.depth; j++) grid += `M${p(0, j)} L${p(l.width, j)} `
  const tickets = snapshot.asks.slice(0, MAX_TICKETS)
  const extra = snapshot.asks.length - tickets.length
  const label = (ask: number) => ask === 0 ? 'aucune demande reçue (7 j)' : `${ask} demande${ask > 1 ? 's' : ''}`

  const dais = (
    <g key="table" className="dais" data-on={String(snapshot.asks.length > 0)}>
      <Faces b={box(l, l.table.x, l.table.y, 0, l.table.w, l.table.d, 0.18)} />
      <Faces b={box(l, l.table.x + 0.9, l.table.y + 0.7, 0.18, l.table.w - 1.8, l.table.d - 1.4, 0.5)} topClass="table-top" />
      {tickets.map((q, i) => {
        const tx = l.table.x + 1.3 + i * 0.95
        const pts = [p(tx, l.table.y + 1.15, 0.69), p(tx + 0.7, l.table.y + 1.15, 0.69), p(tx + 0.7, l.table.y + 1.95, 0.69), p(tx, l.table.y + 1.95, 0.69)].map((q2) => q2.join(',')).join(' ')
        return <polygon key={q.event} data-ticket={q.event} className={clsx('ticket', freshAsks.has(q.event) && 'is-fresh')} points={pts} />
      })}
    </g>
  )
  const rackView = (index: number) => {
    const rv = racks[index]
    if (!rv) return null
    const r = l.racks[index], { node: n, tone } = rv
    const face = LED_FACES.find((d) => l.sees(...NORMAL[d])) ?? '+x'
    return (
      <g key={`rack-${n.id}`} className="rack" data-node={n.id} data-tone={tone}>
        <Faces b={box(l, r.x, r.y, 0, RACK.w, RACK.d, RACK.h)} />
        {[0, 1, 2, 3, 4].map((j) => {
          // Three stacked layers whose opacity follows the tone, so a change fades instead of jumping.
          const pts = ledPoints(l, r, face, 2.1 - j * 0.38)
          return <g key={j}><polygon className="led" data-face={face} points={pts} /><polygon className="led-on" points={pts} /><polygon className="led-ring" points={pts} /></g>
        })}
      </g>
    )
  }

  return (
    <div className="@container relative mx-auto w-full select-none focus-visible:outline-2 focus-visible:outline-accent" style={{ aspectRatio: `${l.viewBox.w} / ${l.viewBox.h}`, maxHeight: '100%', touchAction: 'pan-y' }}
      {...(stage && { ...stage, onDragStart: (e: DragEvent<HTMLElement>) => e.preventDefault(), role: 'group', tabIndex: 0, 'data-stage': '', 'data-angle': Math.round(angle * 10) / 10, 'aria-label': 'Étage : glisser, ou flèches gauche et droite, pour le faire pivoter' })}>
      <svg viewBox={`${l.viewBox.x} ${l.viewBox.y} ${l.viewBox.w} ${l.viewBox.h}`} className="absolute inset-0 size-full" role="img"
        aria-label="Étage de Nexus : un poste par agent, ta table au centre, la salle des serveurs">
        <defs>
          <radialGradient id="now-run"><stop offset="0" stopColor="#5eead4" stopOpacity=".30" /><stop offset="1" stopColor="#5eead4" stopOpacity="0" /></radialGradient>
          <radialGradient id="now-att"><stop offset="0" stopColor="#fb923c" stopOpacity=".26" /><stop offset="1" stopColor="#fb923c" stopOpacity="0" /></radialGradient>
          <pattern id="now-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#f87171" strokeOpacity=".55" strokeWidth="1.4" /></pattern>
        </defs>
        <polygon className="floor-top" points={floor.top} />{floor.sides.map((s) => <polygon key={s.dir} className={s.shade === 'f-left' ? 'floor-left' : 'floor-right'} points={s.points} />)}
        <path className="floor-grid" d={grid.trim()} />
        {seats.map((m, i) => m.wait && (
          <g key={m.agent} className={clsx('route', freshRoutes.has(m.agent) && 'is-fresh')} data-route={m.agent}>
            <path className="r-base" d={routePath(l, l.seats[i])} />
            <path className="r-spark" d={routePath(l, l.seats[i])} pathLength={100} />
          </g>
        ))}
        {drawOrder(l).map((o) => o.kind === 'seat' ? <Desk key={seats[o.index].agent} l={l} seat={l.seats[o.index]} m={seats[o.index]} /> : o.kind === 'rack' ? rackView(o.index) : dais)}
        {seats.map((m, i) => {
          const end = l.labels[i]
          return <path key={m.agent} className="leader" d={`M${end.anchor} L${end.x} ${end.y}`} />
        })}
      </svg>

      {seats.map((m, i) => {
        const [left, top] = toPercent(l, [l.labels[i].x, l.labels[i].y])
        const blocked = snapshot.blocks.find((b) => b.lead_agent === m.agent)
        // Un poste dont l'agent est seulement bloqué ouvre la tâche bloquée.
        const target = m.task ?? (m.block ? blocked?.task ?? null : null)
        const targetTitle = m.title ?? blocked?.title ?? target
        const meta = m.task ? `${m.task} · ${m.since ? age(m.since, now).replace(/^il y a /, '') : 'durée inconnue'}` : m.block ? (blocked ? `${blocked.task} · bloquée` : 'tâche bloquée') : 'inactif'
        // Narrow floor (< 800 px): the task alone on one line, cut with « … »; the duration comes back from 800 px.
        const brief = m.task ?? (m.block ? (blocked?.task ?? 'tâche bloquée') : 'inactif')
        const name = <><span className="block font-orbital-display text-[13px] font-semibold tracking-[0.14em] leading-[14px]">{displayName(m.agent).toUpperCase()}</span>
          {m.title && <span className="mx-auto hidden max-w-[15ch] truncate font-data text-[11px] leading-[13px] text-ink @min-[1150px]:block">{m.title}</span>}
          <span className="mx-auto block max-w-[16ch] truncate font-data text-[11px] leading-[13px] text-muted @min-[800px]:hidden">{brief}</span>
          <span className="hidden font-data text-[11px] leading-[13px] text-muted @min-[800px]:block">{meta}</span></>
        const cls = clsx('absolute whitespace-nowrap text-center -translate-x-1/2', l.labels[i].below ? 'translate-y-0' : '-translate-y-full',
          m.wait ? '[&>span:first-child]:text-attention' : m.block ? '[&>span:first-child]:text-danger' : m.run ? '' : '[&>span:first-child]:text-unknown')
        const style = { left: `${left}%`, top: `${top}%` }
        return target
          ? <a key={m.agent} href={`#/travail/${target}`} data-label={m.agent} draggable={false} className={clsx(cls, 'cursor-pointer bg-transparent no-underline')} style={style} aria-label={`${displayName(m.agent)}, ${targetTitle} : ouvrir la tâche`}>{name}</a>
          : <div key={m.agent} data-label={m.agent} className={cls} style={style}>{name}</div>
      })}

      <div data-table-corner className="pointer-events-none absolute bottom-0 left-0 whitespace-nowrap">
        <span className={clsx('block font-orbital-display text-[13px] font-semibold tracking-[0.14em]', snapshot.asks.length ? 'text-attention' : 'text-muted')}>TA TABLE</span>
        <span className="block font-data text-[11px] text-muted">{label(snapshot.asks.length)}{extra > 0 && ` · +${extra} sur la table`}</span>
      </div>

      <ul data-legend className="pointer-events-none absolute bottom-0 right-0 m-0 flex list-none flex-col gap-1 p-0 font-data text-[11px]">
        {nodes === undefined && <li className="text-muted">{nodesFailed ? 'nœuds illisibles' : 'lecture des nœuds…'}</li>}
        {racks.map(({ node: n, tone, text }) => (
          <li key={n.id} className={clsx('flex items-center gap-2', tone === 'ok' ? 'text-ink' : 'text-muted')}><span className="legend-dot" data-tone={tone} aria-hidden="true" />{text}</li>
        ))}
      </ul>
      {children}
    </div>
  )
}
