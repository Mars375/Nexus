import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { defineConfig } from '@playwright/test'

// Base jetable : les tests de bout en bout ne touchent jamais la vraie nexus.db.
const dataDir = mkdtempSync(join(tmpdir(), 'nexus-e2e-'))
const API_PORT = '8799'
const WEB_PORT = 5199

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    locale: 'fr-FR',
    timezoneId: 'Europe/Paris',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  // work.spec attend une base vide ; now.spec y crée des données : il passe donc après.
  projects: [
    { name: 'work', testMatch: /work.spec.ts/ },
    { name: 'now', testMatch: /now.spec.ts/, dependencies: ['work'] },
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
