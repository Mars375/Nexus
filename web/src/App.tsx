import { useQuery } from '@tanstack/react-query'
import { fetchHealth, type Health } from './api'
import { useNow } from './useNow'

function age(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return `il y a ${seconds} s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `il y a ${minutes} min`
  return `il y a ${Math.round(minutes / 60)} h`
}

function provenance({ db, backup }: Health, now: number): string {
  let text = `source : ${db.source} · mesuré ${age(db.measured_at, now)}`
  if (backup.last_at) text += ` · dernière sauvegarde ${age(backup.last_at, now)}`
  return text
}

export default function App() {
  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth, refetchInterval: 10_000 })
  const now = useNow()

  let status: string
  let detail: string | null = null
  if (health.isPending) {
    status = 'Vérification…'
  } else if (health.isError) {
    // ADR-005 : unknown, avec la date du dernier contrôle réussi s'il y en a eu un.
    status = 'Serveur injoignable — état unknown'
    detail = health.data
      ? `dernier contrôle réussi — ${provenance(health.data, now)}`
      : 'aucun contrôle réussi pour le moment'
  } else {
    status = health.data.db.status === 'ok' ? 'Base OK' : 'Base : état unknown'
    detail = provenance(health.data, now)
  }

  return (
    <main>
      <h1>Nexus</h1>
      <p role="status">{status}</p>
      {detail && <p className="provenance">{detail}</p>}
    </main>
  )
}
