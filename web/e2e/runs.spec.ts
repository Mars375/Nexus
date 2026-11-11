import { expect, test, type Page } from '@playwright/test'
import { API, auth } from './api'

// Le serveur de test déclare un faux `codex` (e2e/fake-codex.mjs) et un dépôt jetable : aucun modèle n'est jamais lancé.

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

// « Chronologie » repeats run statuses and agent messages: run rows are read inside « Runs ».
function runRow(pane: ReturnType<Page['getByRole']>) {
  const runs = pane.locator('section').filter({ has: pane.page().getByRole('heading', { name: 'Runs', exact: true }) })
  return runs.getByRole('listitem').filter({ hasText: 'nx-run-' })
}

async function hand(page: Page, pane: ReturnType<Page['getByRole']>, title: string, brief: string) {
  await pane.getByRole('button', { name: 'Confier à…' }).click()
  const dialog = page.getByRole('dialog', { name: `Confier « ${title} »` })
  await expect(dialog.getByText(/Lance un LLM/)).toBeVisible()
  await dialog.getByLabel(/^Brief/).fill(brief)
  await dialog.getByRole('button', { name: 'Lancer l’agent' }).click()
  return dialog
}

test('confier une tâche et suivre le run jusqu’à sa preuve', async ({ page }) => {
  await createTask('Écrire le journal')
  const pane = await openPane(page, 'Écrire le journal')
  await expect(pane.getByText('Aucun run : rien n’a été confié.')).toBeVisible()

  const dialog = await hand(page, pane, 'Écrire le journal', 'Écris une ligne dans le journal.')
  await expect(dialog).toBeHidden()

  const run = runRow(pane)
  await expect(run.getByText('Terminé', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(run.getByText(/Branche : nexus\/nx-run-\d+/)).toBeVisible()
  await expect(run.getByText(/Preuve : commit:[0-9a-f]{12}/)).toBeVisible()
})

test('un refus lisible, puis l’annulation d’un run qui attend', async ({ page }) => {
  await createTask('Longue tâche')
  await createTask('Autre tâche')

  const first = await openPane(page, 'Longue tâche')
  await hand(page, first, 'Longue tâche', 'ATTENDRE longtemps')
  const waiting = runRow(first)
  await expect(waiting.getByText('En cours', { exact: true })).toBeVisible({ timeout: 30_000 })

  const second = await openPane(page, 'Autre tâche')
  const dialog = await hand(page, second, 'Autre tâche', 'Un autre travail')
  await expect(dialog.getByRole('alert')).toContainText('Cet exécutant a déjà un run actif')
  await dialog.getByRole('button', { name: 'Annuler' }).click()

  const again = await openPane(page, 'Longue tâche')
  await again.getByRole('button', { name: /^Annuler le run nx-run-\d+$/ }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Annuler le run', exact: true }).click()
  const row = runRow(again)
  await expect(row.getByText('Annulé', { exact: true })).toBeVisible({ timeout: 30_000 })
})

test('la chronologie raconte la tâche confiée dans l’ordre, jusqu’à la preuve', async ({ page }) => {
  await createTask('Raconter le run')
  const pane = await openPane(page, 'Raconter le run')
  await hand(page, pane, 'Raconter le run', 'Écris une ligne dans le journal.')

  const story = pane.locator('section').filter({ has: page.getByRole('heading', { name: 'Chronologie' }) })
  await expect(story.getByText('Codex a terminé', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(story.getByText(/Preuve : commit:[0-9a-f]{12}/)).toBeVisible()

  // Newest first: the run ends, then the agent's words, then the run was handed over.
  const text = (await story.getByRole('listitem').allInnerTexts()).join('\n')
  const order = [/terminé : terminé/, /Codex a terminé/, /Codex travaille dessus/, /Codex a pris la tâche/, /confié à Codex/]
  const at = order.map((re) => text.search(re))
  expect(at.every((i) => i >= 0)).toBe(true)
  expect(at).toEqual([...at].sort((a, b) => a - b))
})
