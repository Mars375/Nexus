import clsx from 'clsx'
import { isStale, type FreshnessKind } from './freshness'
import { age, formatDateTime } from './format'
import { useNow } from './useNow'

type Props = {
  source: string
  measuredAt: string
  kind: FreshnessKind
  url?: string | null
  className?: string
}

/**
 * « source : nexus.db · mesuré il y a 32 s » (VIEWS §9, ADR-005). Le composant suit seul
 * l'horloge : l'âge avance sans nouvelle lecture et la donnée passe « périmée » d'elle-même,
 * sans redessiner la vue qui l'affiche.
 */
export function Provenance({ source, measuredAt, kind, url, className }: Props) {
  const now = useNow()
  const readable = !Number.isNaN(Date.parse(measuredAt))
  const stale = isStale(measuredAt, kind, now)
  const link = url?.startsWith('https://') ? url : null
  return (
    <span
      className={clsx('text-2xs', stale ? 'text-attention' : 'text-muted', className)}
      title={readable ? `mesuré le ${formatDateTime(measuredAt)}` : undefined}
    >
      source : {source} · {readable ? `mesuré ${age(measuredAt, now)}` : 'date de mesure illisible'}
      {stale && (
        <>
          {' · '}
          <strong className="font-medium">périmée</strong>
        </>
      )}
      {link && (
        <>
          {' · '}
          <a href={link} target="_blank" rel="noreferrer" className="underline">
            ouvrir
          </a>
        </>
      )}
    </span>
  )
}
