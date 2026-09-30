import { expect, test, type Page } from '@playwright/test'

async function createTask(page: Page, title: string, opts: { todo?: string } = {}) {
  await page.getByRole('button', { name: 'Nouvelle tâche' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Nouvelle tâche' })
  await dialog.getByLabel('Titre').fill(title)
  await dialog.getByLabel('Objectif').fill(`Objectif de ${title}`)
  if (opts.todo) {
    await dialog.getByLabel('Colonne').selectOption('todo')
    await dialog.getByLabel('Prochaine action').fill(opts.todo)
  }
  await dialog.getByRole('button', { name: 'Créer la tâche' }).click()
  await expect(dialog).toBeHidden()
}

const column = (page: Page, name: string) => page.getByRole('region', { name, exact: true })
const card = (page: Page, title: string) => page.getByRole('button', { name: new RegExp(`^${title} —`) })

async function drag(page: Page, title: string, to: string) {
  const source = await card(page, title).boundingBox()
  const target = await column(page, to).boundingBox()
  if (!source || !target) throw new Error('élément introuvable')
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2)
  await page.mouse.down()
  await page.mouse.move(source.x + source.width / 2 + 10, source.y + 10, { steps: 4 })
  await page.mouse.move(target.x + target.width / 2, target.y + 80, { steps: 12 })
  await page.mouse.up()
}

test('créer, déplacer, commenter et filtrer une tâche', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Aucune tâche pour l’instant.').or(page.getByText("Aucune tâche pour l'instant."))).toBeVisible()
  await expect(page.getByRole('main').getByText(/^source : nexus\.db · mesuré il y a/)).toBeVisible()

  await createTask(page, 'Relever les statuts', { todo: 'Lire kanban_db.py' })
  await expect(column(page, 'À faire').getByText('Relever les statuts', { exact: true })).toBeVisible()

  await drag(page, 'Relever les statuts', 'En cours')
  await expect(column(page, 'En cours').getByText('Relever les statuts', { exact: true })).toBeVisible()
  await expect(column(page, 'En cours').getByText('Opération principale', { exact: true })).toBeVisible()

  await card(page, 'Relever les statuts').click()
  const pane = page.getByRole('complementary', { name: /Détail de Relever les statuts/ })
  await pane.getByLabel('Nouveau commentaire').fill('Tables relevées, reste les enums.')
  await pane.getByRole('button', { name: 'Commenter' }).click()
  await expect(pane.getByText('Tables relevées, reste les enums.')).toBeVisible()
  await expect(pane.getByText(/Loïc l'a passée de à faire à en cours/)).toBeVisible()

  const title = pane.getByLabel('Titre')
  await title.fill('')
  await expect(pane.getByText('Le titre ne peut pas être vide.')).toBeVisible()
  await expect(pane.getByRole('button', { name: 'Enregistrer' })).toBeDisabled()
  await title.fill('Relever les statuts')

  await pane.getByLabel('Agent principal').selectOption('helios')
  await pane.getByRole('button', { name: 'Enregistrer' }).click()
  await expect(page.getByText('Modifications enregistrées')).toBeVisible()
  // L'historique suit tout de suite, sans attendre le rafraîchissement périodique (10 s).
  await expect(pane.getByText('Loïc a modifié un champ')).toBeVisible({ timeout: 3_000 })

  await createTask(page, 'Écrire la note')
  await page.getByLabel('Filtrer par agent').selectOption('helios')
  await expect(card(page, 'Écrire la note')).toBeHidden()
  await expect(column(page, 'En cours').getByText('Relever les statuts', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Effacer les filtres' }).click()
  await expect(card(page, 'Écrire la note')).toBeVisible()

  await page.screenshot({ path: 'e2e/screenshots/travail.png' })
})

test('au clavier, Entrée ouvre une carte', async ({ page }) => {
  await page.goto('/')
  await createTask(page, 'Carte au clavier')
  await card(page, 'Carte au clavier').focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('complementary', { name: /Détail de Carte au clavier/ })).toBeVisible()
})

test('un rafraîchissement raté garde le tableau affiché', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await createTask(page, 'Toujours visible')
  await page.route('**/api/tasks', (route) => route.fulfill({ status: 503, body: '' }))

  await expect(page.getByText('Tableau non à jour')).toBeVisible({ timeout: 20_000 })
  await expect(card(page, 'Toujours visible')).toBeVisible()
})

test('un déplacement refusé revient en place avec la raison', async ({ page }) => {
  await page.goto('/')
  await createTask(page, 'Idée lointaine')
  await expect(column(page, 'Plus tard').getByText('Idée lointaine', { exact: true })).toBeVisible()

  await drag(page, 'Idée lointaine', 'Terminé')

  await expect(page.getByText('Une tâche plus tard ne peut pas passer en terminé.')).toBeVisible()
  await expect(column(page, 'Plus tard').getByText('Idée lointaine', { exact: true })).toBeVisible()
  await expect(column(page, 'Terminé').getByText('Idée lointaine', { exact: true })).toBeHidden()
})

test('bloquer demande la cause et ce qui débloquerait', async ({ page }) => {
  await page.goto('/')
  await createTask(page, 'Lire Artémis', { todo: 'SSH vers artemis' })
  await drag(page, 'Lire Artémis', 'En cours')
  await expect(column(page, 'En cours').getByText('Lire Artémis', { exact: true })).toBeVisible()

  await drag(page, 'Lire Artémis', 'Bloqué')
  const dialog = page.getByRole('dialog')
  const confirm = dialog.getByRole('button', { name: 'Déplacer en bloqué' })
  await expect(confirm).toBeDisabled()
  await dialog.getByLabel('Ce qui bloque').fill('Artémis éteint')
  await dialog.getByLabel('Ce qui débloquerait').fill('Loïc rallume le nœud')
  await confirm.click()

  await expect(column(page, 'Bloqué').getByText('Bloqué : Artémis éteint', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'e2e/screenshots/bloque.png' })
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.reload()
  await expect(column(page, 'Bloqué').getByText('Bloqué : Artémis éteint', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'e2e/screenshots/bloque-sombre.png' })
})

test("une modification d'un agent pendant la saisie n'efface pas le brouillon", async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await createTask(page, 'Tâche partagée', { todo: 'Étape initiale' })
  await card(page, 'Tâche partagée').click()
  const pane = page.getByRole('complementary', { name: /Détail de Tâche partagée/ })
  await pane.getByLabel('Titre').fill('Tâche partagée (renommée)')

  // Un agent change la prochaine action via l'API, pendant que Loïc tape.
  const tasks = await (await page.request.get('/api/tasks')).json()
  const id = tasks.find((t: { title: string }) => t.title === 'Tâche partagée').id
  const res = await page.request.patch(`/api/tasks/${id}`, {
    data: { next_action: "Étape posée par l'agent" },
    headers: { 'X-Nexus-Actor': 'helios' },
  })
  expect(res.ok()).toBeTruthy()

  // Au prochain rafraîchissement, le brouillon reste et le changement est signalé.
  await expect(pane.getByText('Modifiée ailleurs pendant ta saisie')).toBeVisible({ timeout: 20_000 })
  await expect(pane.getByLabel('Titre')).toHaveValue('Tâche partagée (renommée)')

  await pane.getByRole('button', { name: 'Enregistrer' }).click()
  await expect(page.getByText('Modifications enregistrées')).toBeVisible()
  const saved = await (await page.request.get(`/api/tasks/${id}`)).json()
  expect(saved.title).toBe('Tâche partagée (renommée)')
  expect(saved.next_action).toBe("Étape posée par l'agent")
})

test("un champ rempli par un agent pendant la saisie ne bloque pas l'enregistrement", async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/')
  await createTask(page, 'Idée à mûrir')
  await card(page, 'Idée à mûrir').click()
  const pane = page.getByRole('complementary', { name: /Détail de Idée à mûrir/ })
  await pane.getByLabel('Objectif').fill('Objectif précisé par Loïc')

  // Pendant ce temps, un agent l'active (à faire) en posant une prochaine action.
  const tasks = await (await page.request.get('/api/tasks')).json()
  const id = tasks.find((t: { title: string }) => t.title === 'Idée à mûrir').id
  await page.request.post(`/api/tasks/${id}/status`, {
    data: { status: 'todo', next_action: 'Étape posée par Helios' },
    headers: { 'X-Nexus-Actor': 'helios' },
  })

  await expect(pane.getByText('Modifiée ailleurs pendant ta saisie')).toBeVisible({ timeout: 20_000 })
  const save = pane.getByRole('button', { name: 'Enregistrer' })
  await expect(save).toBeEnabled()
  await save.click()
  await expect(page.getByText('Modifications enregistrées')).toBeVisible()
})

test("un commentaire commencé sur une tâche ne suit pas vers une autre", async ({ page }) => {
  await page.goto('/')
  await createTask(page, 'Tâche A')
  await createTask(page, 'Tâche B')

  await card(page, 'Tâche A').click()
  await page.getByLabel('Nouveau commentaire').fill('Note destinée à A')
  await card(page, 'Tâche B').click()

  const pane = page.getByRole('complementary', { name: /Détail de Tâche B/ })
  await expect(pane).toBeVisible()
  await expect(pane.getByLabel('Nouveau commentaire')).toHaveValue('')
})

test("une tâche préparée « principale » démarre en auxiliaire si une autre est en cours", async ({ page }) => {
  await page.goto('/')
  await createTask(page, 'Principale actuelle', { todo: 'Continuer' })
  await drag(page, 'Principale actuelle', 'En cours')
  await expect(column(page, 'En cours').getByText('Opération principale', { exact: true })).toBeVisible()

  await createTask(page, 'Préparée principale', { todo: 'Commencer' })
  const tasks = await (await page.request.get('/api/tasks')).json()
  const id = tasks.find((t: { title: string }) => t.title === 'Préparée principale').id
  await page.request.patch(`/api/tasks/${id}`, { data: { operation_role: 'main' } })
  await page.reload()

  await drag(page, 'Préparée principale', 'En cours')
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('celle-ci démarrera comme auxiliaire')).toBeVisible()
  await dialog.getByRole('button', { name: 'Déplacer en en cours' }).click()

  await expect(column(page, 'En cours').getByText('Préparée principale', { exact: true })).toBeVisible()
  const started = await (await page.request.get(`/api/tasks/${id}`)).json()
  expect(started.operation_role).toBe('auxiliary')
})

test('le tableau et le détail disent d\'où viennent les données', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('main').getByText(/^source : nexus\.db · mesuré il y a/).first()).toBeVisible()
  await createTask(page, 'Tracer la provenance')
  await card(page, 'Tracer la provenance').click()
  const pane = page.getByRole('complementary', { name: 'Détail de Tracer la provenance' })
  await expect(pane.locator('header').getByText(/^source : nexus\.db · mesuré il y a/)).toBeVisible()
})
