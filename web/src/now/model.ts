import type { AgentId, NodeState, NowAsk, NowSnapshot } from '@/api'
import { age } from '@/format'

/** Les âges affichés sur Maintenant sont à la minute : une horloge à 30 s suffit, sans redessiner l'étage chaque seconde. */
export const AGE_TICK_MS = 30_000

export type SeatModel = { agent: AgentId; run: boolean; wait: boolean; block: boolean; task: string | null; title: string | null; since: string | null; asks: number }

/**
 * Only an ask whose approval is `pending` waits for Loïc (ADR-019, D7). One without approval
 * (before migration 0004) is never said to wait: nobody knows whether it was treated.
 */
export const isPending = (q: NowAsk): boolean => q.approval?.status === 'pending'

/** The asks that wait for Loïc, in the order received. */
export const pendingAsks = (s: NowSnapshot): NowAsk[] => s.asks.filter(isPending)

/** Un poste par agent : run d'après ses événements, demandes en attente, blocage de ses tâches. */
export function seatModels(s: NowSnapshot): SeatModel[] {
  return s.agents.map((a) => {
    const asks = pendingAsks(s).filter((q) => q.agent === a.agent).length
    return {
      agent: a.agent, run: a.state === 'run', wait: asks > 0,
      block: s.blocks.some((b) => b.lead_agent === a.agent),
      task: a.task, title: a.title, since: a.since, asks,
    }
  })
}

export type RackTone = 'ok' | 'unknown' | 'off'

/** A rack as drawn and listed: its node, tone, state text in French (« périmée » when the reading is stale) and legend line. */
export type RackView = { node: NodeState; tone: RackTone; state: string; text: string }

/** Visual tone of a rack: ok only when the node is online, unknown when unread, off otherwise. */
export function rackTone(n: NodeState): RackTone {
  if (n.status === 'online') return 'ok'
  if (n.status === 'unknown') return 'unknown'
  return 'off'
}

/** Racks per server-room floor; floor 1 is the office with the first four. */
export const RACKS_PER_FLOOR = 4

/**
 * Nodes grouped by floor, in the order received from the server (it fixes each node's floor, so
 * neither `status` nor presence reorders anyone). Always at least one floor; `undefined` = not read yet.
 */
export function nodeFloors(nodes: readonly NodeState[] | undefined): NodeState[][] {
  const list = nodes ?? []
  const floors: NodeState[][] = []
  for (let i = 0; i < list.length; i += RACKS_PER_FLOOR) floors.push(list.slice(i, i + RACKS_PER_FLOOR))
  return floors.length > 0 ? floors : [[]]
}

export type FloorAlert = 'off' | 'unknown'

/**
 * Alert shown on a floor marker: red when a fresh node is offline, amber when one is unknown or stale
 * (`stale` also covers a failed re-read), nothing otherwise. An offline-by-design node never alerts.
 */
export function floorAlert(nodes: readonly NodeState[], stale: (n: NodeState) => boolean): FloorAlert | null {
  let amber = false
  for (const n of nodes) {
    if (stale(n) || n.status === 'unknown') amber = true
    else if (n.status === 'offline') return 'off'
  }
  return amber ? 'unknown' : null
}

/** How many nodes cause the alert `floorAlert` gives (red: the fresh offline ones; amber: the unknown or stale ones). */
export function floorAlertCount(nodes: readonly NodeState[], stale: (n: NodeState) => boolean): number {
  const kind = floorAlert(nodes, stale)
  if (kind === 'off') return nodes.filter((n) => !stale(n) && n.status === 'offline').length
  return kind === 'unknown' ? nodes.filter((n) => stale(n) || n.status === 'unknown').length : 0
}

const SEVERITY: Record<FloorAlert, number> = { unknown: 1, off: 2 }
/** Most severe of some alerts (red over amber), or null when there is none. */
const worst = (list: FloorAlert[]): FloorAlert | null => list.reduce<FloorAlert | null>((w, a) => (w === null || SEVERITY[a] > SEVERITY[w] ? a : w), null)

/**
 * Alerts of the floors out of sight, seen from floor `current` (1-based): the most severe above and
 * below it (for the pips on ▲ and ▼), and every other alerting floor in order. Never the floor shown.
 */
export function floorAlertSides(alerts: readonly (FloorAlert | null)[], current: number, counts: readonly number[] = []): { above: FloorAlert | null; below: FloorAlert | null; others: { floor: number; alert: FloorAlert; count: number }[] } {
  const others = alerts.flatMap((alert, i) => alert && i + 1 !== current ? [{ floor: i + 1, alert, count: counts[i] ?? 1 }] : [])
  return { above: worst(others.filter((o) => o.floor > current).map((o) => o.alert)), below: worst(others.filter((o) => o.floor < current).map((o) => o.alert)), others }
}

const LABEL: Record<NodeState['status'], string> = {
  online: 'en ligne', unknown: 'inconnu', offline: 'hors ligne', 'offline-by-design': 'hors ligne, prévu',
}
/** State text of a node in French, as shown in the legend and on the rack label. */
export function rackLabel(n: NodeState): string {
  return LABEL[n.status]
}

/**
 * The words of a rack on a server floor, one source for the visual label and the screen-reader legend:
 * name, state (with « vu il y a … » for an offline or unknown node whose last sighting is plausible, never
 * in the future nor after the measure: nothing is invented), guardian, and the three joined.
 */
export function rackDetail(r: RackView, now: number): { name: string; state: string; guardian: string; text: string } {
  const { node } = r, seenAt = node.last_seen ? Date.parse(node.last_seen) : NaN
  const plausible = Number.isFinite(seenAt) && seenAt <= now && seenAt <= Date.parse(node.measured_at)
  const seen = (node.status === 'offline' || node.status === 'unknown') && plausible ? ` · vu ${age(node.last_seen!, now)}` : ''
  const name = node.id.toUpperCase(), state = `${r.state}${seen}`, guardian = `gardien : ${displayName(node.guardian_agent)}`
  return { name, state, guardian, text: `${name} · ${state} · ${guardian}` }
}

/** Noms affichés sur Maintenant : une seule table pour l'étage, la liste et le panneau. */
const AGENT_NAME: Record<string, string> = {
  helios: 'Helios', mnema: 'Mnema', aether: 'Aether', artemis: 'Artemis', claude: 'Claude',
  codex: 'Codex', orca: 'Orca', hermes: 'Hermes', loic: 'Loïc',
}
/** Display name of an agent (or the raw actor when it has none). */
export const displayName = (actor: string): string => AGENT_NAME[actor] ?? actor
