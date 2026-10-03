import type { AgentId, NodeState, NowSnapshot } from '@/api'

/** Les âges affichés sur Maintenant sont à la minute : une horloge à 30 s suffit, sans redessiner l'étage chaque seconde. */
export const AGE_TICK_MS = 30_000

export type SeatModel = { agent: AgentId; run: boolean; wait: boolean; block: boolean; task: string | null; title: string | null; since: string | null; asks: number }

/** Un poste par agent : run d'après ses événements, demandes reçues, blocage de ses tâches. */
export function seatModels(s: NowSnapshot): SeatModel[] {
  return s.agents.map((a) => {
    const asks = s.asks.filter((q) => q.agent === a.agent).length
    return {
      agent: a.agent, run: a.state === 'run', wait: asks > 0,
      block: s.blocks.some((b) => b.lead_agent === a.agent),
      task: a.task, title: a.title, since: a.since, asks,
    }
  })
}

export type RackTone = 'ok' | 'unknown' | 'off'

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

const LABEL: Record<NodeState['status'], string> = {
  online: 'en ligne', unknown: 'unknown', offline: 'hors ligne', 'offline-by-design': 'hors ligne, prévu',
}
export function rackLabel(n: NodeState): string {
  return LABEL[n.status]
}

/** Noms affichés sur Maintenant : une seule table pour l'étage, la liste et le panneau. */
const AGENT_NAME: Record<string, string> = {
  helios: 'Helios', mnema: 'Mnema', aether: 'Aether', artemis: 'Artemis', claude: 'Claude',
  codex: 'Codex', orca: 'Orca', hermes: 'Hermes', loic: 'Loïc',
}
export const displayName = (actor: string): string => AGENT_NAME[actor] ?? actor
