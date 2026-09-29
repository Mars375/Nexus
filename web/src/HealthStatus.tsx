import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { fetchHealth, type Health } from './api'
import { age } from './format'
import { useNow } from './useNow'

function provenance({ db, backup }: Health, now: number): string {
  let text = `source : ${db.source} · mesuré ${age(db.measured_at, now)}`
  if (backup.last_at) text += ` · dernière sauvegarde ${age(backup.last_at, now)}`
  return text
}

/** Barre d'état : santé de la base, avec provenance et fraîcheur (ADR-005). */
export function HealthStatus() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: 10_000,
    // Serveur local : toujours tenter le contrôle (pas de pause « hors ligne »),
    // et un échec compte tout de suite — l'état passe à unknown sans attendre des reprises.
    networkMode: 'always',
    retry: false,
  })
  const now = useNow()

  let status: string
  let detail: string | null = null
  let tone: 'ok' | 'unknown' | 'pending' = 'pending'
  if (health.isPending) {
    status = 'Vérification…'
  } else if (health.isError) {
    status = 'Serveur injoignable — état unknown'
    tone = 'unknown'
    detail = health.data
      ? `dernier contrôle réussi — ${provenance(health.data, now)}`
      : 'aucun contrôle réussi pour le moment'
  } else {
    const ok = health.data.db.status === 'ok'
    status = ok ? 'Base OK' : 'Base : état unknown'
    tone = ok ? 'ok' : 'unknown'
    detail = provenance(health.data, now)
  }

  return (
    <footer className="flex items-center gap-3 border-t border-line bg-surface px-4 py-1.5 text-2xs text-muted">
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
      {detail && <span className="truncate">{detail}</span>}
    </footer>
  )
}
