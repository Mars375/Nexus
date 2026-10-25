import { expect, test, type Page, type WebSocketRoute } from '@playwright/test'
import { API, auth } from './api'

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
  await page.goto('/#/travail')
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
  await expect(pane.getByText('Loïc a confié la tâche à Helios')).toBeVisible({ timeout: 3_000 })
  await expect(pane.getByText('Agent principal : Helios')).toBeVisible()
  const leadName = card(page, 'Relever les statuts').getByText('Helios', { exact: true })
  await expect(leadName).toBeVisible()
  // `.sr-only` stays "visible" to Playwright: check it is really painted and not the screen-reader copy.
  expect((await leadName.boundingBox())?.width ?? 0).toBeGreaterThan(1)
  expect(await leadName.evaluate((el) => el.closest('.sr-only'))).toBeNull()

  await createTask(page, 'Écrire la note')
  await page.getByLabel('Filtrer par agent').selectOption('helios')
  await expect(card(page, 'Écrire la note')).toBeHidden()
  await expect(column(page, 'En cours').getByText('Relever les statuts', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Effacer les filtres' }).click()
  await expect(card(page, 'Écrire la note')).toBeVisible()

  await page.screenshot({ path: 'e2e/screenshots/travail.png' })
})

test('au clavier, Entrée ouvre une carte', async ({ page }) => {
  await page.goto('/#/travail')
  await createTask(page, 'Carte au clavier')
  await card(page, 'Carte au clavier').focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('complementary', { name: /Détail de Carte au clavier/ })).toBeVisible()
})

test('un rafraîchissement raté garde le tableau affiché', async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/#/travail')
  await createTask(page, 'Toujours visible')
  await page.route('**/api/tasks', (route) => route.fulfill({ status: 503, body: '' }))

  await expect(page.getByText('Tableau non à jour')).toBeVisible({ timeout: 20_000 })
  await expect(card(page, 'Toujours visible')).toBeVisible()
})

test('un déplacement refusé revient en place avec la raison', async ({ page }) => {
  await page.goto('/#/travail')
  await createTask(page, 'Idée lointaine')
  await expect(column(page, 'Plus tard').getByText('Idée lointaine', { exact: true })).toBeVisible()

  await drag(page, 'Idée lointaine', 'Terminé')

  await expect(page.getByText('Une tâche plus tard ne peut pas passer en terminé.')).toBeVisible()
  await expect(column(page, 'Plus tard').getByText('Idée lointaine', { exact: true })).toBeVisible()
  await expect(column(page, 'Terminé').getByText('Idée lointaine', { exact: true })).toBeHidden()
})

test('bloquer demande la cause et ce qui débloquerait', async ({ page }) => {
  await page.goto('/#/travail')
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
  await page.goto('/#/travail')
  await createTask(page, 'Tâche partagée', { todo: 'Étape initiale' })
  await card(page, 'Tâche partagée').click()
  const pane = page.getByRole('complementary', { name: /Détail de Tâche partagée/ })
  await pane.getByLabel('Titre').fill('Tâche partagée (renommée)')

  // Un agent change la prochaine action via l'API, pendant que Loïc tape.
  const tasks = await (await page.request.get('/api/tasks', { headers: auth() })).json()
  const id = tasks.find((t: { title: string }) => t.title === 'Tâche partagée').id
  const res = await page.request.patch(`/api/tasks/${id}`, {
    data: { next_action: "Étape posée par l'agent" },
    headers: auth('helios'),
  })
  expect(res.ok()).toBeTruthy()

  // Au prochain rafraîchissement, le brouillon reste et le changement est signalé.
  await expect(pane.getByText('Modifiée ailleurs pendant ta saisie')).toBeVisible({ timeout: 20_000 })
  await expect(pane.getByLabel('Titre')).toHaveValue('Tâche partagée (renommée)')

  await pane.getByRole('button', { name: 'Enregistrer' }).click()
  await expect(page.getByText('Modifications enregistrées')).toBeVisible()
  const saved = await (await page.request.get(`/api/tasks/${id}`, { headers: auth() })).json()
  expect(saved.title).toBe('Tâche partagée (renommée)')
  expect(saved.next_action).toBe("Étape posée par l'agent")
})

test("un champ rempli par un agent pendant la saisie ne bloque pas l'enregistrement", async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/#/travail')
  await createTask(page, 'Idée à mûrir')
  await card(page, 'Idée à mûrir').click()
  const pane = page.getByRole('complementary', { name: /Détail de Idée à mûrir/ })
  await pane.getByLabel('Objectif').fill('Objectif précisé par Loïc')

  // Pendant ce temps, un agent l'active (à faire) en posant une prochaine action.
  const tasks = await (await page.request.get('/api/tasks', { headers: auth() })).json()
  const id = tasks.find((t: { title: string }) => t.title === 'Idée à mûrir').id
  await page.request.post(`/api/tasks/${id}/status`, {
    data: { status: 'todo', next_action: 'Étape posée par Helios' },
    headers: auth('helios'),
  })

  await expect(pane.getByText('Modifiée ailleurs pendant ta saisie')).toBeVisible({ timeout: 20_000 })
  const save = pane.getByRole('button', { name: 'Enregistrer' })
  await expect(save).toBeEnabled()
  await save.click()
  await expect(page.getByText('Modifications enregistrées')).toBeVisible()
})

test("un commentaire commencé sur une tâche ne suit pas vers une autre", async ({ page }) => {
  await page.goto('/#/travail')
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
  await page.goto('/#/travail')
  await createTask(page, 'Principale actuelle', { todo: 'Continuer' })
  await drag(page, 'Principale actuelle', 'En cours')
  await expect(column(page, 'En cours').getByText('Opération principale', { exact: true })).toBeVisible()

  await createTask(page, 'Préparée principale', { todo: 'Commencer' })
  const tasks = await (await page.request.get('/api/tasks', { headers: auth() })).json()
  const id = tasks.find((t: { title: string }) => t.title === 'Préparée principale').id
  await page.request.patch(`/api/tasks/${id}`, { headers: auth(), data: { operation_role: 'main' } })
  await page.reload()

  await drag(page, 'Préparée principale', 'En cours')
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('celle-ci démarrera comme auxiliaire')).toBeVisible()
  await dialog.getByRole('button', { name: 'Déplacer en en cours' }).click()

  await expect(column(page, 'En cours').getByText('Préparée principale', { exact: true })).toBeVisible()
  // The board card is optimistic: the status POST may still be in flight when the API is read.
  // Wait for the server to have resolved the role instead of reading it once.
  await expect
    .poll(
      async (): Promise<string | null> => {
        const response = await page.request.get(`/api/tasks/${id}`, { headers: auth() })
        if (!response.ok()) throw new Error(`GET /api/tasks/${id} : ${response.status()}`)
        return (await response.json()).operation_role
      },
      { message: 'le rôle d’opération doit être résolu côté serveur', timeout: 5_000 },
    )
    .toBe('auxiliary')
})

test('le tableau et le détail disent d\'où viennent les données', async ({ page }) => {
  await page.goto('/#/travail')
  await expect(page.getByRole('main').getByText(/^source : nexus\.db · mesuré il y a/).first()).toBeVisible()
  await createTask(page, 'Tracer la provenance')
  await card(page, 'Tracer la provenance').click()
  const pane = page.getByRole('complementary', { name: 'Détail de Tracer la provenance' })
  await expect(pane.locator('header').getByText(/^source : nexus\.db · mesuré il y a/)).toBeVisible()
})


test('une tâche créée par l’API apparaît en moins d’une seconde', async ({ page, request }) => {
  await page.goto('/#/travail')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  const res = await request.post(`${API}/api/tasks`, {
    headers: auth(),
    data: { title: 'Arrivée en direct', objective: 'Prouver le temps réel' },
  })
  expect(res.ok()).toBeTruthy()
  await expect(card(page, 'Arrivée en direct')).toBeVisible({ timeout: 1000 })
})

test('après une coupure, la reconnexion rattrape ce qui a changé', async ({ page, request }) => {
  // Chaque connexion est numérotée : seuls comptent les messages reçus APRÈS la coupure.
  // Sans cela, la connexion d'avant (côté serveur) pourrait livrer le changement en direct
  // et le test passerait sans prouver le rattrapage.
  const log: { connection: number; message: string }[] = []
  let connections = 0
  let blocked = false
  const live: { current: { page: WebSocketRoute; server: WebSocketRoute } | null } = { current: null }
  const urls: string[] = []
  // Only the Nexus socket: Vite's dev server keeps its own HMR WebSocket on the page.
  page.on('websocket', (ws) => {
    if (new URL(ws.url()).pathname === '/api/ws') urls.push(ws.url())
  })
  await page.routeWebSocket(/\/api\/ws/, (ws) => {
    if (blocked) {
      void ws.close({ code: 1011, reason: 'coupure simulée' })
      return
    }
    const connection = ++connections
    const server = ws.connectToServer()
    server.onMessage((message) => {
      log.push({ connection, message: String(message) })
      ws.send(message)
    })
    live.current = { page: ws, server }
  })
  await page.goto('/#/travail')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()

  blocked = true
  const cut = connections
  await live.current!.server.close()
  await live.current!.page.close({ code: 1011, reason: 'coupure simulée' })
  await expect(page.getByText(/Temps réel : reconnexion/)).toBeVisible()

  const res = await request.post(`${API}/api/tasks`, {
    headers: auth(),
    data: { title: 'Pendant la coupure', objective: 'Rattrapage' },
  })
  expect(res.ok()).toBeTruthy()
  const ref = (await res.json()).id as string

  blocked = false
  await expect(page.getByText('Temps réel : connecté')).toBeVisible({ timeout: 15_000 })
  await expect
    .poll(
      () =>
        log.some(
          (entry) =>
            entry.connection > cut &&
            entry.message.includes('"task_changed"') &&
            entry.message.includes(`"${ref}"`),
        ),
      { timeout: 5000 },
    )
    .toBe(true)
  await expect(card(page, 'Pendant la coupure')).toBeVisible()
  // Le ticket voyage en sous-protocole, jamais dans l'URL (#57).
  expect(urls.length).toBeGreaterThan(1)
  expect(urls.filter((url) => url.includes('nxw_'))).toEqual([])
})

// --- Tâche terminée en lecture seule et tâche de suite (#65, ADR-022) ---

const RUN = Date.now() // titles are unique: the database is shared with the other tests

/** A task closed through the API, as Loïc would have: todo → in_progress → done. */
async function closedTask(page: Page, title: string, opts: { evidence?: string[] } = {}): Promise<string> {
  const headers = auth()
  const created = await page.request.post('/api/tasks', {
    headers,
    data: { title, objective: `Objectif de ${title}`, status: 'todo', next_action: 'Prévue avant la clôture' },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const id = (await created.json()).id as string
  for (const status of ['in_progress', 'done']) {
    const res = await page.request.post(`/api/tasks/${id}/status`, {
      headers,
      data: { status, ...(status === 'done' && opts.evidence && { evidence: opts.evidence }) },
    })
    expect(res.ok(), await res.text()).toBeTruthy()
  }
  return id
}

test('Loïc ouvre une tâche terminée par un vrai clic, y joint une preuve, puis ouvre une tâche de suite', async ({ page }) => {
  const title = `Livraison ${RUN}`
  const id = await closedTask(page, title)
  await page.goto('/#/travail')

  // La carte d'une tâche terminée n'est pas déplaçable : le clic ne doit pas attendre.
  const closedCard = page.getByRole('button', { name: `${title} — ouvrir`, exact: true })
  await expect(closedCard).toBeVisible()
  expect(await closedCard.getAttribute('aria-disabled')).toBeNull()
  expect(await closedCard.getAttribute('aria-roledescription')).toBeNull()
  await expect(column(page, 'Terminé').getByText('Prévue avant la clôture')).toHaveCount(0)
  await closedCard.click({ timeout: 3_000 })

  const pane = page.getByRole('complementary', { name: `Détail de ${title}` })
  await expect(pane.getByText(/Cette tâche ne se modifie plus/)).toBeVisible()
  await expect(pane.getByRole('button', { name: 'Enregistrer' })).toHaveCount(0)
  await expect(pane.getByLabel('Titre')).toHaveCount(0)

  // Joindre une preuve : la tâche reste terminée, la preuve apparaît et l'historique la nomme.
  await pane.getByLabel('Joindre une preuve').fill(`commit:e2e${RUN}`)
  await pane.getByRole('button', { name: 'Joindre' }).click()
  await expect(pane.getByText(`commit:e2e${RUN}`, { exact: true })).toBeVisible()
  await expect(pane.getByText('Loïc a joint une preuve')).toBeVisible({ timeout: 3_000 })
  const stored = await (await page.request.get(`/api/tasks/${id}`, { headers: auth() })).json()
  expect(stored.status).toBe('done')
  expect(stored.evidence).toEqual([`commit:e2e${RUN}`])

  // Joindre deux fois la même preuve : le refus du serveur s'affiche, le texte reste.
  await pane.getByLabel('Joindre une preuve').fill(`commit:e2e${RUN}`)
  await pane.getByRole('button', { name: 'Joindre' }).click()
  await expect(pane.getByRole('alert')).toContainText('déjà jointe')
  await expect(pane.getByLabel('Joindre une preuve')).toHaveValue(`commit:e2e${RUN}`)

  // Tâche de suite : la boîte porte la ligne « Suite de », la carte et le panneau aussi ensuite.
  await pane.getByRole('button', { name: 'Ouvrir une tâche de suite' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nouvelle tâche' })
  await expect(dialog.getByText(`Suite de ${id} — ${title}`)).toBeVisible()
  await dialog.getByLabel('Titre').fill(`Correctif ${RUN}`)
  await dialog.getByLabel('Objectif').fill('Corriger ce qui a été livré')
  await dialog.getByRole('button', { name: 'Créer la tâche' }).click()
  await expect(dialog).toBeHidden()

  const followUp = column(page, 'Plus tard').getByRole('button', { name: new RegExp(`^Correctif ${RUN} —`) })
  await expect(followUp).toBeVisible()
  await expect(followUp.getByText(`Suite de #${id.replace('nx-task-', '')}`)).toBeVisible()
  await expect(pane.getByText('Suivie par :')).toBeVisible({ timeout: 5_000 })
  await expect(pane.getByRole('button', { name: new RegExp(`^Correctif ${RUN}`) })).toBeVisible()

  // Le lien « Suite de » mène à la tâche suivie, et « Suivie par » revient à la suite.
  await followUp.click()
  const followPane = page.getByRole('complementary', { name: `Détail de Correctif ${RUN}` })
  await expect(followPane.getByRole('button', { name: `Suite de ${id} — ${title}` })).toBeVisible()
  await followPane.getByRole('button', { name: `Suite de ${id} — ${title}` }).click()
  await expect(page.getByRole('complementary', { name: `Détail de ${title}` })).toBeVisible()
  await page.screenshot({ path: 'e2e/screenshots/tache-terminee.png' })
})

test('un agent clôt la tâche pendant que Loïc édite le panneau : le brouillon reste, l’envoi est refusé avec son motif', async ({ page }) => {
  test.setTimeout(60_000)
  const title = `Édition concurrente ${RUN}`
  const headers = auth('helios')
  const created = await page.request.post('/api/tasks', {
    headers: auth(),
    data: { title, objective: 'Clôturée par un agent', status: 'todo', next_action: 'Étape en cours' },
  })
  const id = (await created.json()).id as string
  const at = new Date().toISOString()
  const send = async (suffix: string, body: Record<string, unknown>) => {
    const res = await page.request.post('/api/events', {
      headers,
      data: { id: `evt_done_${RUN}_${suffix}`, at, actor: 'helios', task: id, subject: suffix, ...body },
    })
    expect(res.ok(), await res.text()).toBeTruthy()
  }
  await send('claimed', { kind: 'claimed' })
  await send('working', { kind: 'working', run: `run-${RUN}` })

  await page.goto('/#/travail')
  await card(page, title).click()
  const pane = page.getByRole('complementary', { name: `Détail de ${title}` })
  await pane.getByLabel('Titre').fill(`${title} (retouché)`)

  await send('done', { kind: 'done', run: `run-${RUN}`, evidence: [`commit:agent${RUN}`] })

  await expect(pane.getByText(/Cette tâche vient d’être terminée/)).toBeVisible({ timeout: 20_000 })
  await expect(pane.getByLabel('Titre')).toHaveValue(`${title} (retouché)`)
  await expect(pane.getByRole('button', { name: 'Enregistrer' })).toBeDisabled()
  await expect(pane.getByText(`commit:agent${RUN}`)).toBeVisible()

  await pane.getByRole('button', { name: 'Abandonner le brouillon' }).click()
  await expect(pane.getByLabel('Titre')).toHaveCount(0)
  await expect(pane.getByRole('button', { name: 'Ouvrir une tâche de suite' })).toBeVisible()
  const stored = await (await page.request.get(`/api/tasks/${id}`, { headers: auth() })).json()
  expect(stored.title).toBe(title)
})
