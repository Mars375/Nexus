/*
 * Fraîcheur des données (ADR-005) : cadence de relecture par type, et règle de péremption.
 * Une donnée est périmée quand elle a plus de STALE_FACTOR relectures de retard.
 */
export type FreshnessKind = 'tasks' | 'health' | 'nodes' | 'now'

export const REFRESH_MS: Record<FreshnessKind, number> = {
  tasks: 10_000,
  health: 10_000,
  nodes: 60_000,
  now: 10_000,
}

export const STALE_FACTOR = 3

/** Source déclarée d'un type, pour une liste vide qui n'a aucun élément à citer. */
export const SOURCE_OF: Record<FreshnessKind, string> = {
  tasks: 'nexus.db',
  health: 'nexus.db',
  nodes: 'tailscale',
  now: 'nexus.db',
}

export type Provenanced = { source: string; measured_at: string; source_url?: string | null }

export function isStale(measuredAt: string, kind: FreshnessKind, now: number): boolean {
  const measured = Date.parse(measuredAt)
  if (Number.isNaN(measured)) return true // illisible : on ne prétend pas qu'elle est fraîche
  return now - measured > STALE_FACTOR * REFRESH_MS[kind]
}

/** Provenance d'une liste : son élément le plus ancien ; vide, la dernière lecture réussie. */
export function listProvenance(
  items: Provenanced[],
  kind: FreshnessKind,
  dataUpdatedAt: number,
): { source: string; measuredAt: string } | null {
  if (items.length === 0) {
    return dataUpdatedAt > 0
      ? { source: SOURCE_OF[kind], measuredAt: new Date(dataUpdatedAt).toISOString() }
      : null
  }
  const oldest = items.reduce((a, b) => {
    const ta = Date.parse(a.measured_at)
    const tb = Date.parse(b.measured_at)
    if (Number.isNaN(tb)) return b
    if (Number.isNaN(ta)) return a
    return tb < ta ? b : a
  })
  return { source: oldest.source, measuredAt: oldest.measured_at }
}
