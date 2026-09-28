// Toute donnée passe par l'API FastAPI — jamais d'accès direct propre au navigateur (ADR-017).

export type Health = {
  version: string
  db: { status: 'ok' | 'unknown'; source: string; measured_at: string }
  backup: { last_at: string | null; count: number; source: string }
}

export async function fetchHealth(): Promise<Health> {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
