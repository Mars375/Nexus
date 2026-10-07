// Constantes partagées par playwright.config.ts, le setup global et les specs.
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export const API_PORT = '8799'
export const WEB_PORT = 5199
export const WEB_ORIGIN = `http://localhost:${WEB_PORT}`
/** Même clé que `TOKEN_KEY` de src/auth.ts (e2e/auth.spec.ts échoue si elles divergent). */
export const TOKEN_KEY = 'nexus.token'

/**
 * Base jetable : les tests de bout en bout ne touchent jamais la vraie nexus.db. Le processus
 * principal la crée et la publie dans l'environnement ; les workers, qui relisent la config, la
 * retrouvent au lieu d'en créer une autre.
 */
export function dataDirPath(): string {
  process.env.NEXUS_E2E_DATA_DIR ??= mkdtempSync(join(tmpdir(), 'nexus-e2e-'))
  return process.env.NEXUS_E2E_DATA_DIR
}

export const storageStatePath = (): string => join(dataDirPath(), 'storage-state.json')
