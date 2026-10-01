import clsx from 'clsx'
import type { NodeState, NowSnapshot } from '@/api'
import { age } from '@/format'
import { isStale } from '@/freshness'
import { useNow } from '@/useNow'
import { DESK, RACK, box, layoutFloor, toPercent, type Box, type Layout } from './iso'
import { AGE_TICK_MS, displayName, rackLabel, rackTone, seatModels, type RackTone, type SeatModel } from './model'
import { useArrivals } from './useArrivals'
import './floor.css'

const MAX_TICKETS = 3
// Décalage vertical (px de la scène) entre le poste et son étiquette ; au-dessus des postes du fond, il dégage l'écran du poste voisin.
const LABEL_LIFT = 40

function Faces({ b, topClass }: { b: Box; topClass?: string }) {
  return (<><polygon className={clsx('f-top', topClass)} points={b.top} /><polygon className="f-left" points={b.left} /><polygon className="f-right" points={b.right} /></>)
}

function routePath(l: Layout, s: { x: number; y: number; back: boolean }): string {
  const sx = s.x + DESK.w / 2, sy = s.back ? s.y + DESK.d : s.y
  const ty = s.back ? l.table.y : l.table.y + l.table.d
  const tx = Math.min(Math.max(sx, l.table.x + 0.6), l.table.x + l.table.w - 0.6)
  const my = (sy + ty) / 2
  return 'M' + [l.project(sx, sy), l.project(sx, my), l.project(tx, my), l.project(tx, ty)].map((p) => p.join(' ')).join(' L ')
}

function Desk({ l, seat, m }: { l: Layout; seat: Layout['seats'][number]; m: SeatModel }) {
  const { x, y } = seat, p = l.project
  const pool = p(x + DESK.w / 2, y + 2.3)
  const [bx, by0] = p(x + 0.55, y + 0.27, 1.66), [, by1] = p(x + 0.55, y + 0.27, 2.75)
  const screenPts = [p(x + 0.45, y + 0.28, 1.63), p(x + 2.55, y + 0.28, 1.63), p(x + 2.55, y + 0.28, 0.86), p(x + 0.45, y + 0.28, 0.86)].map((q) => q.join(',')).join(' ')
  return (
    <g className="desk" data-agent={m.agent} data-run={String(m.run)} data-wait={String(m.wait)} data-block={String(m.block)}>
      <ellipse className="pool" cx={pool[0]} cy={pool[1]} rx={2.4 * 22.5} ry={2.4 * 13} />
      <ellipse className="pool-att" cx={pool[0]} cy={pool[1]} rx={1.9 * 22.5} ry={1.9 * 13} />
      <Faces b={box(p, x, y, 0, DESK.w, DESK.d, DESK.h)} topClass="desk-top" />
      <Faces b={box(p, x + 0.35, y + 0.15, DESK.h, 2.3, 0.12, 0.95)} />
      <polygon className="screen" points={screenPts} />
      <g className="beacon"><line x1={bx} y1={by0} x2={bx} y2={by1} /><polygon points={`${bx},${by1 - 7} ${bx + 6},${by1} ${bx},${by1 + 7} ${bx - 6},${by1}`} /></g>
    </g>
  )
}

type RackView = { node: NodeState; tone: RackTone; text: string }

export function Floor({ snapshot, nodes, nodesFailed = false }: { snapshot: NowSnapshot; nodes: NodeState[] | undefined; nodesFailed?: boolean }) {
  const now = useNow(AGE_TICK_MS)
  const seats = seatModels(snapshot)
  // Une mesure trop ancienne, ou une relecture en échec : jamais de vert sur une donnée périmée.
  const racks: RackView[] = (nodes ?? []).map((node) => {
    const stale = nodesFailed || isStale(node.measured_at, 'nodes', now)
    return { node, tone: stale ? 'unknown' : rackTone(node), text: `${node.id.toUpperCase()} · ${stale ? 'périmée' : rackLabel(node)}` }
  })
  const l = layoutFloor(seats.length, nodes === undefined ? 1 : racks.length) // la salle garde sa place pendant la lecture
  const freshAsks = useArrivals(snapshot.asks.map((q) => q.event))
  const freshRoutes = new Set(snapshot.asks.filter((q) => freshAsks.has(q.event)).map((q) => q.agent))
  const p = l.project
  const floor = box(p, 0, 0, -0.35, l.width, l.depth, 0.35)
  let grid = ''
  for (let i = 1; i < l.width; i++) grid += `M${p(i, 0)} L${p(i, l.depth)} `
  for (let j = 1; j < l.depth; j++) grid += `M${p(0, j)} L${p(l.width, j)} `
  const tickets = snapshot.asks.slice(0, MAX_TICKETS)
  const extra = snapshot.asks.length - tickets.length
  const tableLabel = toPercent(l, p(l.table.x + l.table.w + 0.3, l.table.y + 1, 0.4))
  const label = (ask: number) => ask === 0 ? 'aucune demande reçue (7 j)' : `${ask} demande${ask > 1 ? 's' : ''}`

  return (
    <div className="@container relative mx-auto w-full" style={{ aspectRatio: `${l.viewBox.w} / ${l.viewBox.h}`, maxHeight: '100%' }}>
      <svg viewBox={`${l.viewBox.x} ${l.viewBox.y} ${l.viewBox.w} ${l.viewBox.h}`} className="absolute inset-0 size-full" role="img"
        aria-label="Étage de Nexus : un poste par agent, ta table au centre, la salle des serveurs">
        <defs>
          <radialGradient id="now-run"><stop offset="0" stopColor="#5eead4" stopOpacity=".30" /><stop offset="1" stopColor="#5eead4" stopOpacity="0" /></radialGradient>
          <radialGradient id="now-att"><stop offset="0" stopColor="#fb923c" stopOpacity=".26" /><stop offset="1" stopColor="#fb923c" stopOpacity="0" /></radialGradient>
          <pattern id="now-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#f87171" strokeOpacity=".55" strokeWidth="1.4" /></pattern>
        </defs>
        <polygon className="floor-top" points={floor.top} /><polygon className="floor-left" points={floor.left} /><polygon className="floor-right" points={floor.right} />
        <path className="floor-grid" d={grid.trim()} />
        {seats.map((m, i) => m.wait && (
          <g key={m.agent} className={clsx('route', freshRoutes.has(m.agent) && 'is-fresh')} data-route={m.agent}>
            <path className="r-base" d={routePath(l, l.seats[i])} />
            <path className="r-spark" d={routePath(l, l.seats[i])} pathLength={100} />
          </g>
        ))}
        <g className="dais" data-on={String(snapshot.asks.length > 0)}>
          <Faces b={box(p, l.table.x, l.table.y, 0, l.table.w, l.table.d, 0.18)} />
          <Faces b={box(p, l.table.x + 0.9, l.table.y + 0.7, 0.18, l.table.w - 1.8, l.table.d - 1.4, 0.5)} topClass="table-top" />
          {tickets.map((q, i) => {
            const tx = l.table.x + 1.3 + i * 0.95
            const pts = [p(tx, l.table.y + 1.15, 0.69), p(tx + 0.7, l.table.y + 1.15, 0.69), p(tx + 0.7, l.table.y + 1.95, 0.69), p(tx, l.table.y + 1.95, 0.69)].map((q2) => q2.join(',')).join(' ')
            return <polygon key={q.event} data-ticket={q.event} className={clsx('ticket', freshAsks.has(q.event) && 'is-fresh')} points={pts} />
          })}
        </g>
        {racks.map(({ node: n, tone }, i) => {
          const r = l.racks[i]
          return (
            <g key={n.id} className="rack" data-node={n.id} data-tone={tone}>
              <Faces b={box(p, r.x, r.y, 0, RACK.w, RACK.d, RACK.h)} />
              {[0, 1, 2, 3, 4].map((j) => {
                const z = 2.1 - j * 0.38, xr = r.x + RACK.w
                const pts = [p(xr, r.y + 0.25, z), p(xr, r.y + 1.15, z), p(xr, r.y + 1.15, z - 0.16), p(xr, r.y + 0.25, z - 0.16)].map((q) => q.join(',')).join(' ')
                return <polygon key={j} className="led" points={pts} />
              })}
            </g>
          )
        })}
        {seats.map((m, i) => <Desk key={m.agent} l={l} seat={l.seats[i]} m={m} />)}
        {seats.map((m, i) => {
          const s = l.seats[i], from = s.back ? p(s.x + 1.5, s.y + 0.2, 1.8) : p(s.x + 1.5, s.y + DESK.d, 0)
          return <path key={m.agent} className="leader" d={`M${from} L${from[0]} ${from[1] + (s.back ? -LABEL_LIFT : 26)}`} />
        })}
        {racks.map(({ node: n }, i) => {
          const r = l.racks[i], led = p(r.x + RACK.w, r.y + 0.7, 1.3), lx = l.legend.x, ly = l.legend.rows[i]
          return <path key={n.id} className="leader" d={`M${led} L${lx - 14} ${ly} L${lx - 4} ${ly}`} />
        })}
      </svg>

      {seats.map((m, i) => {
        const s = l.seats[i], from = s.back ? p(s.x + 1.5, s.y + 0.2, 1.8) : p(s.x + 1.5, s.y + DESK.d, 0)
        const [left, top] = toPercent(l, [from[0], from[1] + (s.back ? -LABEL_LIFT : 26)])
        const blocked = snapshot.blocks.find((b) => b.lead_agent === m.agent)
        // Un poste dont l'agent est seulement bloqué ouvre la tâche bloquée.
        const target = m.task ?? (m.block ? blocked?.task ?? null : null)
        const targetTitle = m.title ?? blocked?.title ?? target
        const meta = m.task ? `${m.task} · ${m.since ? age(m.since, now).replace(/^il y a /, '') : 'durée inconnue'}` : m.block ? (blocked ? `${blocked.task} · bloquée` : 'tâche bloquée') : 'inactif'
        const name = <><span className="block font-orbital-display text-[13px] font-semibold tracking-[0.14em] leading-[14px]">{displayName(m.agent).toUpperCase()}</span>
          {m.title && <span className="mx-auto hidden max-w-[15ch] truncate font-data text-[11px] leading-[13px] text-ink @min-[1150px]:block">{m.title}</span>}
          <span className="hidden font-data text-[11px] leading-[13px] text-muted @min-[800px]:block">{meta}</span></>
        const cls = clsx('absolute whitespace-nowrap text-center', s.back ? '-translate-x-1/2 -translate-y-full' : '-translate-x-1/2',
          m.wait ? '[&>span:first-child]:text-attention' : m.block ? '[&>span:first-child]:text-danger' : m.run ? '' : '[&>span:first-child]:text-unknown')
        const style = { left: `${left}%`, top: `${top}%` }
        return target
          ? <a key={m.agent} href={`#/travail/${target}`} data-label={m.agent} className={clsx(cls, 'cursor-pointer bg-transparent no-underline')} style={style} aria-label={`${displayName(m.agent)}, ${targetTitle} : ouvrir la tâche`}>{name}</a>
          : <div key={m.agent} data-label={m.agent} className={cls} style={style}>{name}</div>
      })}

      <div className="absolute -translate-y-1/2 whitespace-nowrap pl-2" style={{ left: `${tableLabel[0]}%`, top: `${tableLabel[1]}%` }}>
        <span className={clsx('block font-orbital-display text-[13px] font-semibold tracking-[0.14em]', snapshot.asks.length ? 'text-attention' : 'text-muted')}>TA TABLE</span>
        <span className="block font-data text-[11px] text-muted">{label(snapshot.asks.length)}{extra > 0 && ` · +${extra} sur la table`}</span>
      </div>

      {nodes === undefined && (
        <div className="absolute -translate-y-1/2 whitespace-nowrap font-data text-[11px] text-muted" style={{ left: `${toPercent(l, [l.legend.x, l.legend.rows[0]])[0]}%`, top: `${toPercent(l, [l.legend.x, l.legend.rows[0]])[1]}%` }}>lecture des nœuds…</div>
      )}
      {racks.map(({ node: n, tone, text }, i) => {
        const [left, top] = toPercent(l, [l.legend.x, l.legend.rows[i]])
        return (
          <div key={n.id} className={clsx('absolute -translate-y-1/2 whitespace-nowrap font-data text-[11px]', tone === 'ok' ? 'text-ink' : 'text-muted')} style={{ left: `${left}%`, top: `${top}%` }}>{text}</div>
        )
      })}
    </div>
  )
}
