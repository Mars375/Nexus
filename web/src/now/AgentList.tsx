import clsx from 'clsx'
import type { NowSnapshot } from '@/api'
import { age } from '@/format'
import { useNow } from '@/useNow'
import { AGE_TICK_MS, seatModels } from './model'

const NAME: Record<string, string> = { helios: 'Helios', mnema: 'Mnema', aether: 'Aether', artemis: 'Artemis', claude: 'Claude', codex: 'Codex', orca: 'Orca', hermes: 'Hermes' }

/** Même information que l'étage, en lignes : fenêtre étroite et lecteurs d'écran. */
export function AgentList({ snapshot, className }: { snapshot: NowSnapshot; className?: string }) {
  const now = useNow(AGE_TICK_MS)
  const seats = seatModels(snapshot)
  const working = seats.filter((s) => s.run).length
  return (
    <div>
      {working === 0 && <p className="m-0 text-muted">Aucun agent ne travaille en ce moment.</p>}
      <ul aria-label="Agents" className={clsx('flex flex-col', className)}>
        {seats.map((s) => (
          <li key={s.agent} className="flex items-baseline gap-3 border-b border-line py-1.5">
            <span className={clsx('w-20 font-orbital-display font-semibold tracking-[0.12em]', s.wait ? 'text-attention' : s.block ? 'text-danger' : s.run ? 'text-run' : 'text-unknown')}>{(NAME[s.agent] ?? s.agent).toUpperCase()}</span>
            {s.task
              ? <a href={`#/travail/${s.task}`} className="min-w-0 flex-1 truncate">{s.title ?? s.task}</a>
              : <span className="flex-1 text-muted">inactif</span>}
            <span className="font-data text-[11px] text-muted">
              {s.run && s.since ? age(s.since, now) : ''}{s.wait ? ` · ${s.asks} demande${s.asks > 1 ? 's' : ''}` : ''}{s.block ? ' · tâche bloquée' : ''}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
