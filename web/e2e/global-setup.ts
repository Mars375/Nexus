/*
 * Avant les tests (le serveur a déjà démarré et migré la base jetable, voir `webServer`) : émet un
 * jeton par acteur dans cette base avec la CLI du produit (le serveur les exige partout, et un
 * événement doit porter le jeton de son acteur). Celui de `loic` est aussi placé dans le
 * `localStorage` de l'interface (storageState), pour que ses requêtes portent `Authorization`.
 * Le jeton ne vit que dans le dossier temporaire du test (mkdtemp, droits 0700) et l'environnement
 * du processus de test ; il n'est jamais affiché.
 */
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { ACTORS } from './api'
import { WEB_ORIGIN, dataDirPath, storageStatePath, TOKEN_KEY } from './e2e-env'

function issue(actor: string): string {
  const out = execFileSync(
    'uv',
    ['run', '--directory', '../server', 'nexus-token', 'issue', actor, '--label', 'e2e'],
    {
      cwd: fileURLToPath(new URL('..', import.meta.url)),
      env: { ...process.env, NEXUS_DATA_DIR: dataDirPath() },
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'], // the CLI prints the token on stdout and guidance on stderr
    },
  )
  const token = out.trim()
  if (!/^nxt_[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('nexus-token n’a pas renvoyé un jeton valide')
  return token
}

export default function globalSetup() {
  const tokens = Object.fromEntries(ACTORS.map((actor) => [actor, issue(actor)]))
  writeFileSync(
    storageStatePath(),
    JSON.stringify({ cookies: [], origins: [{ origin: WEB_ORIGIN, localStorage: [{ name: TOKEN_KEY, value: tokens.loic }] }] }),
    { mode: 0o600 },
  )
  // Read by e2e/api.ts and e2e/auth.spec.ts; the workers inherit the environment.
  process.env.NEXUS_E2E_TOKEN = tokens.loic
  process.env.NEXUS_E2E_TOKENS = JSON.stringify(tokens)
}
