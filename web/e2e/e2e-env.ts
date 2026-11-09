// Constantes partagées par playwright.config.ts, le setup global et les specs.
import { execFileSync } from 'node:child_process'
import { existsSync, lstatSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'

export const API_PORT = '8799'
export const WEB_PORT = 5199
export const WEB_ORIGIN = `http://localhost:${WEB_PORT}`
/** Même clé que `TOKEN_KEY` de src/auth.ts (e2e/auth.spec.ts échoue si elles divergent). */
export const TOKEN_KEY = 'nexus.token'

/** A symlink named like ours could still point at a real data dir: refused. */
function isRealDirectory(path: string): boolean {
  try {
    const stat = lstatSync(path)
    return stat.isDirectory() && !stat.isSymbolicLink()
  } catch {
    return false
  }
}

/**
 * Base jetable : les tests de bout en bout ne touchent jamais la vraie nexus.db. Le processus
 * principal la crée et la publie dans l'environnement ; les workers, qui relisent la config, la
 * retrouvent au lieu d'en créer une autre.
 */
export function dataDirPath(): string {
  // An inherited value is trusted only if it is one of our throwaway directories: directly under
  // the OS temp dir, named `nexus-e2e-*`. Anything else (a real data dir) is replaced.
  const inherited = process.env.NEXUS_E2E_DATA_DIR
  const ours =
    inherited !== undefined &&
    resolve(dirname(resolve(inherited))) === resolve(tmpdir()) &&
    basename(resolve(inherited)).startsWith('nexus-e2e-') &&
    isRealDirectory(resolve(inherited))
  if (!ours) process.env.NEXUS_E2E_DATA_DIR = mkdtempSync(join(tmpdir(), 'nexus-e2e-'))
  return process.env.NEXUS_E2E_DATA_DIR as string
}

export const storageStatePath = (): string => join(dataDirPath(), 'storage-state.json')

/**
 * Un faux `codex` (e2e/fake-codex.mjs) et un dépôt git jetable, dans la base jetable : le serveur
 * de test les déclare (NEXUS_CODEX_BIN, NEXUS_RUN_WORKDIRS) et peut ainsi confier un run sans
 * jamais lancer un vrai modèle. Idempotent : les workers relisent la config.
 */
export function codexFixture(): { bin: string; repo: string } {
  const root = join(dataDirPath(), 'codex-e2e')
  const repo = join(root, 'repo')
  const script = resolve('e2e/fake-codex.mjs')
  const bin = join(root, process.platform === 'win32' ? 'codex-e2e.cmd' : 'codex-e2e')
  if (!existsSync(bin)) {
    mkdirSync(repo, { recursive: true })
    const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('GIT_')))
    const git = (...args: string[]) => execFileSync('git', args, { cwd: repo, env, stdio: 'ignore' })
    git('init', '-q')
    writeFileSync(join(repo, 'LISEZMOI.txt'), 'dépôt de test\n')
    git('add', 'LISEZMOI.txt')
    git('-c', 'user.name=e2e', '-c', 'user.email=e2e@example.invalid', 'commit', '--no-gpg-sign', '-q', '-m', 'départ')
    if (process.platform === 'win32') {
      writeFileSync(bin, `@"${process.execPath}" "${script}" %*\r\n`)
    } else {
      writeFileSync(bin, `#!/bin/sh\nexec "${process.execPath}" "${script}" "$@"\n`, { mode: 0o755 })
    }
  }
  return { bin, repo }
}
