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
