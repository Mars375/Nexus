import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import type { ReactNode } from 'react'
import { REFRESH_MS } from './freshness'
import { fetchHealth, type Health } from './api'
import { age } from './format'
import type { LiveState } from './live'
import { LiveStatus } from './LiveStatus'
import { Provenance } from './Provenance'
import { useNow } from './useNow'

function Detail({ data }: { data: Health }) {
  const now = useNow()
  return (
    <>
      <Provenance source={data.db.source} measuredAt={data.db.measured_at} kind="health" />
      {data.backup.last_at && <> · dernière sauvegarde {age(data.backup.last_at, now)}</>}
    </>
  )
}

/** Barre d'état : santé de la base, avec provenance et fraîcheur (ADR-005). */
export function HealthStatus({ live }: { live?: LiveState } = {}) {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: REFRESH_MS.health,
    // Serveur local : toujours tenter le contrôle (pas de pause « hors ligne »),
    // et un échec compte tout de suite — l'état passe à unknown sans attendre des reprises.
    networkMode: 'always',
    retry: false,
  })

  let status: string
  let detail: ReactNode = null
  let tone: 'ok' | 'unknown' | 'pending' = 'pending'
  if (health.isPending) {
    status = 'Vérification…'
  } else if (health.isError) {
    status = 'Serveur injoignable — état unknown'
    tone = 'unknown'
    detail = health.data
      ? <>dernier contrôle réussi — <Detail data={health.data} /></>
      : 'aucun contrôle réussi pour le moment'
  } else {
    const ok = health.data.db.status === 'ok'
    status = ok ? 'Base OK' : 'Base : état unknown'
    tone = ok ? 'ok' : 'unknown'
    detail = <Detail data={health.data} />
  }

  return (
    <footer className="orbital flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line bg-surface px-4 py-1.5 text-2xs text-muted">
      <span className="flex items-center gap-1.5">
        <span
          aria-hidden
          className={clsx(
            'size-2 rounded-full',
            tone === 'ok' && 'bg-ok',
            tone === 'unknown' && 'bg-attention',
            tone === 'pending' && 'bg-line',
          )}
        />
        <span role="status" className="text-ink">{status}</span>
      </span>
      {detail && <span className="min-w-0 break-words">{detail}</span>}
      {live && <LiveStatus state={live} />}
    </footer>
  )
}
