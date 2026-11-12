import { expect, test, type Page } from '@playwright/test'
import { API, auth } from './api'

// Le serveur de test déclare un faux `claude` (e2e/fake-claude.mjs) : aucun modèle n'est jamais lancé, et le faux ne commite pas.
// Le commit de la preuve est fait par Nexus lui-même.

async function createTask(title: string): Promise<void> {
  const res = await fetch(`${API}/api/tasks`, {
    method: 'POST',
    headers: { ...auth(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, objective: `Objectif de ${title}`, status: 'todo', next_action: 'lancer' }),
  })
  expect(res.status).toBe(201)
}

async function openPane(page: Page, title: string) {
  await page.goto('/#/travail')
  await page.getByRole('button', { name: new RegExp(`^${title} —`) }).click()
  return page.getByRole('complementary', { name: `Détail de ${title}` })
}

test('confier une tâche à Claude avec Opus : le run s’affiche avec son modèle et la preuve du commit de Nexus', async ({ page }) => {
  await createTask('Écrire avec Claude')
  const pane = await openPane(page, 'Écrire avec Claude')

  await pane.getByRole('button', { name: 'Confier à…' }).click()
  const dialog = page.getByRole('dialog', { name: 'Confier « Écrire avec Claude »' })
  await dialog.getByLabel(/^Exécutant/).selectOption('claude')
  await expect(dialog.getByLabel(/^Modèle/)).toHaveValue('sonnet') // Sonnet est présélectionné
  await dialog.getByLabel(/^Modèle/).selectOption('opus')
  await expect(dialog.getByText(/consomme l’abonnement Claude/)).toBeVisible()
  await dialog.getByLabel(/^Brief/).fill('Écris une ligne dans TRAVAIL-CLAUDE.txt.')
  await dialog.getByRole('button', { name: 'Lancer l’agent' }).click()
  await expect(dialog).toBeHidden()

  const runs = pane.locator('section').filter({ has: page.getByRole('heading', { name: 'Runs', exact: true }) })
  const run = runs.getByRole('listitem').filter({ hasText: 'nx-run-' })
  await expect(run.getByText('Terminé', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(run).toContainText('Opus')
  await expect(run.getByText(/Branche : nexus\/nx-run-\d+/)).toBeVisible()
  await expect(run.getByText(/Preuve : commit:[0-9a-f]{12}/)).toBeVisible()

  const story = pane.locator('section').filter({ has: page.getByRole('heading', { name: 'Chronologie' }) })
  await expect(story.getByText('Claude Code a terminé ; Nexus a commité', { exact: true })).toBeVisible()
})
