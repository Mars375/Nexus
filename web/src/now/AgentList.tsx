import clsx from 'clsx'
import { useSyncExternalStore } from 'react'
import type { NowSnapshot } from '@/api'
import { age } from '@/format'
import { useNow } from '@/useNow'
import { AGE_TICK_MS, displayName, seatModels } from './model'

const WIDE = '(min-width: 760px)'
const subscribe = (cb: () => void) => {
  if (typeof window.matchMedia !== 'function') return () => {}
  const mq = window.matchMedia(WIDE)
  mq.addEventListener('change', cb)
  return () => mq.removeEventListener('change', cb)
}
const isWide = () => typeof window.matchMedia === 'function' && window.matchMedia(WIDE).matches

/** Même information que l'étage, en lignes : fenêtre étroite et lecteurs d'écran. */
export function AgentList({ snapshot, className }: { snapshot: NowSnapshot; className?: string }) {
  const now = useNow(AGE_TICK_MS)
  // Au-dessus de 760 px la liste n'est que pour les lecteurs d'écran : pas de tabulation sur du invisible.
  const wide = useSyncExternalStore(subscribe, isWide, () => false)
  const seats = seatModels(snapshot)
  const working = seats.filter((s) => s.run).length
  return (
    <div>
      {working === 0 && <p className="m-0 text-muted">Aucun agent ne travaille en ce moment.</p>}
      <ul aria-label="Agents" className={clsx('flex flex-col', className)}>
        {seats.map((s) => (
          <li key={s.agent} className="flex items-baseline gap-3 border-b border-line py-1.5">
            <span className={clsx('w-20 font-orbital-display font-semibold tracking-[0.12em]', s.wait ? 'text-attention' : s.block ? 'text-danger' : s.run ? 'text-run' : 'text-unknown')}>{displayName(s.agent).toUpperCase()}</span>
            {s.task
              ? <a href={`#/travail/${s.task}`} tabIndex={wide ? -1 : undefined} className="min-w-0 flex-1 truncate">{s.title ?? s.task}</a>
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
