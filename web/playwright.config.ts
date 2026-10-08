import { defineConfig } from '@playwright/test'
import { API_PORT, WEB_PORT, dataDirPath, storageStatePath } from './e2e/e2e-env'

const dataDir = dataDirPath()

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  // Après le démarrage du serveur : émet un jeton par acteur dans la base jetable ; celui de `loic` va dans le storageState (e2e/global-setup.ts).
  globalSetup: './e2e/global-setup.ts',
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    locale: 'fr-FR',
    timezoneId: 'Europe/Paris',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    // Le jeton `loic` est déjà dans le localStorage : les requêtes de l'interface portent Authorization.
    storageState: storageStatePath(),
  },
  // work.spec attend une base vide ; now.spec y crée des données : il passe donc après.
  projects: [
    { name: 'work', testMatch: /work.spec.ts/ },
    { name: 'now', testMatch: /now.spec.ts/, dependencies: ['work'] },
    // approvals.spec crée ses propres demandes (sujets uniques) : il ne dépend d'aucune donnée des autres.
    { name: 'approvals', testMatch: /approvals.spec.ts/, dependencies: ['work'] },
    { name: 'visuals', testMatch: /visuals.spec.ts/, dependencies: ['now'] },
    // auth.spec joue les 401 du vrai serveur (deux tests seulement les simulent) ; il émet puis révoque un jeton et crée une tâche (« Brouillon sous verrou »), sans effet sur les autres projets.
    { name: 'auth', testMatch: /auth.spec.ts/, dependencies: ['work'] },
  ],
  webServer: [
    {
      command: 'uv run --directory ../server nexus',
      env: { NEXUS_DATA_DIR: dataDir, NEXUS_PORT: API_PORT },
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `pnpm exec vite --port ${WEB_PORT} --strictPort`,
      env: { NEXUS_PORT: API_PORT },
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
