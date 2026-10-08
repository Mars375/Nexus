// Appels directs à l'API depuis les specs : chaque appel porte le jeton de son acteur (ADR-020).
// Les jetons sont émis par e2e/global-setup.ts dans la base jetable ; les workers héritent de
// l'environnement. Aucun `extraHTTPHeaders` global : il masquerait l'en-tête de l'interface.
export const API = 'http://127.0.0.1:8799'

export const ACTORS = ['loic', 'helios', 'mnema', 'aether', 'artemis', 'claude', 'codex', 'orca', 'hermes'] as const
export type Actor = (typeof ACTORS)[number]

/** `Authorization: Bearer …` de l'acteur (Loïc par défaut) : à passer en `headers` d'un appel. */
export function auth(actor: Actor = 'loic'): { Authorization: string } {
  const token = actor === 'loic' ? process.env.NEXUS_E2E_TOKEN : (JSON.parse(process.env.NEXUS_E2E_TOKENS ?? '{}') as Record<string, string>)[actor]
  if (!token) throw new Error(`jeton e2e absent pour ${actor} (globalSetup n’a pas tourné ?)`)
  return { Authorization: `Bearer ${token}` }
}
