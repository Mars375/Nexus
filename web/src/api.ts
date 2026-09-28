// Toute donnée passe par l'API FastAPI — jamais d'accès direct propre au navigateur (ADR-017).

export type Health = {
  version: string
  db: { status: 'ok' | 'unknown'; source: string; measured_at: string }
  backup: { last_at: string | null; count: number; source: string }
}

/** Au-delà, un contrôle sans réponse compte comme un échec (état unknown, ADR-005). */
export const HEALTH_TIMEOUT_MS = 5_000

export async function fetchHealth(
  signal?: AbortSignal,
  timeoutMs: number = HEALTH_TIMEOUT_MS,
): Promise<Health> {
  const timeout = AbortSignal.timeout(timeoutMs)
  const res = await fetch('/api/health', {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
