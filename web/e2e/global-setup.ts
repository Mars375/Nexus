/*
 * Avant les tests (le serveur a déjà démarré et migré la base jetable, voir `webServer`) : émet un
 * jeton `loic` dans cette base avec la CLI du produit et le place dans le `localStorage` de
 * l'interface (storageState), pour que toutes les requêtes des tests portent `Authorization`.
 * Le jeton ne vit que dans le dossier temporaire du test (mkdtemp, droits 0700) et l'environnement
 * du processus de test ; il n'est jamais affiché.
 */
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { WEB_ORIGIN, dataDirPath, storageStatePath, TOKEN_KEY } from './e2e-env'

export default function globalSetup() {
  const out = execFileSync(
    'uv',
    ['run', '--directory', '../server', 'nexus-token', 'issue', 'loic', '--label', 'e2e'],
    {
      cwd: fileURLToPath(new URL('..', import.meta.url)),
      env: { ...process.env, NEXUS_DATA_DIR: dataDirPath() },
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'], // the CLI prints the token on stdout and guidance on stderr
    },
  )
  const token = out.trim()
  if (!/^nxt_[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('nexus-token n’a pas renvoyé un jeton valide')
  writeFileSync(
    storageStatePath(),
    JSON.stringify({ cookies: [], origins: [{ origin: WEB_ORIGIN, localStorage: [{ name: TOKEN_KEY, value: token }] }] }),
    { mode: 0o600 },
  )
  process.env.NEXUS_E2E_TOKEN = token // read by e2e/auth.spec.ts; workers inherit it
}
