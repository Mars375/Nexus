import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const API = 'http://127.0.0.1:8799'
const RUN = Date.now() // subjects are unique: the database is shared with the other specs

type Published = { event: string; approval: string; subject: string }

/** An agent publishes a request for Loïc through the API (the actor header must match the body). */
async function publish(
  request: APIRequestContext, actor: string, kind: 'question' | 'needs_human', slug: string, payload: Record<string, unknown>,
): Promise<Published> {
  const subject = `${slug} ${RUN}`
  const res = await request.post(`${API}/api/events`, {
    headers: { 'X-Nexus-Actor': actor },
    data: { id: `evt_appr_${slug}_${RUN}`.replace(/\W/g, '_'), at: new Date().toISOString(), actor, kind, subject, needs: ['loic'], payload },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  const body = await res.json()
  const approval = (body.effects as { action: string; approval: string }[]).find((e) => e.action === 'approval')!.approval
  return { event: body.id, approval, subject }
}

const read = async (request: APIRequestContext, ref: string) => (await request.get(`${API}/api/approvals/${ref}`)).json()
const card = (page: Page, p: Published) => page.locator(`[data-ask="${p.event}"]`)

async function openCard(page: Page, p: Published) {
  await page.goto('/#/maintenant')
  const c = card(page, p)
  await c.getByRole('button', { name: p.subject }).click()
  return c
}

const validation = { consequence: 'La v2 part chez les clients.', options: ['Avec la vidéo', 'Sans la vidéo'] }

test('Loïc valide une demande avec un choix : l\'agent relit « approved » et cet indice', async ({ page, request }) => {
  const ask = await publish(request, 'helios', 'needs_human', 'valider-v2', validation)
  const c = await openCard(page, ask)
  await expect(c.getByText('en attente', { exact: true })).toBeVisible()
  await expect(c.getByText('Conséquence annoncée par Helios')).toBeVisible()
  await expect(c.getByRole('button', { name: 'Valider', exact: true })).toBeDisabled()
  await c.getByRole('radio', { name: 'Sans la vidéo' }).check()
  await c.getByRole('textbox', { name: /Note/ }).fill('Go, sans la vidéo')
  await c.getByRole('button', { name: 'Valider', exact: true }).click()
  await expect(c.getByText('validée', { exact: true })).toBeVisible()
  const approval = await read(request, ask.approval)
  expect(approval.status).toBe('approved')
  expect(approval.decided_by).toBe('loic')
  expect(approval.response).toMatchObject({ choice: 1, text: 'Go, sans la vidéo' })
})

test('Loïc refuse une demande : « rejected », sans choix', async ({ page, request }) => {
  const ask = await publish(request, 'helios', 'needs_human', 'refuser-v3', validation)
  const c = await openCard(page, ask)
  await c.getByRole('radio', { name: 'Avec la vidéo' }).check()
  await c.getByRole('button', { name: 'Refuser', exact: true }).click()
  await expect(c.getByText('refusée', { exact: true })).toBeVisible()
  const approval = await read(request, ask.approval)
  expect(approval.status).toBe('rejected')
  expect(approval.response.choice).toBeNull()
})

test('Loïc répond à une question depuis une option proposée', async ({ page, request }) => {
  const ask = await publish(request, 'mnema', 'question', 'version-python', { options: ['3.12', '3.13'] })
  const c = await openCard(page, ask)
  await expect(c.getByRole('button', { name: 'Répondre', exact: true })).toBeDisabled()
  await expect(c.getByText('Écris une réponse pour pouvoir répondre.')).toBeVisible()
  await c.getByRole('button', { name: '3.13' }).click()
  await expect(c.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('3.13')
  expect((await read(request, ask.approval)).status).toBe('pending') // quick-fill sends nothing
  await c.getByRole('button', { name: 'Répondre', exact: true }).click()
  await expect(c.getByText('répondue', { exact: true })).toBeVisible()
  const approval = await read(request, ask.approval)
  expect(approval).toMatchObject({ status: 'answered', decided_by: 'loic' })
  expect(approval.response.text).toBe('3.13')
})

test('tout se fait au clavier : Entrée déplie, Tab atteint le champ, la réponse part', async ({ page, request }) => {
  const ask = await publish(request, 'mnema', 'question', 'clavier', {})
  await page.goto('/#/maintenant')
  const header = card(page, ask).getByRole('button', { name: ask.subject })
  await header.focus()
  await page.keyboard.press('Enter')
  await expect(header).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Tab')
  await expect(card(page, ask).getByRole('textbox', { name: 'Ta réponse' })).toBeFocused()
  await page.keyboard.type('Au clavier')
  await page.keyboard.press('Tab')
  await expect(card(page, ask).getByRole('button', { name: 'Répondre', exact: true })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(card(page, ask).getByText('répondue', { exact: true })).toBeVisible()
  expect((await read(request, ask.approval)).response.text).toBe('Au clavier')
})

test('deux fenêtres décident la même demande en même temps : une seule gagne, l\'autre voit le bandeau', async ({ browser, request }) => {
  const ask = await publish(request, 'helios', 'needs_human', 'course', validation)
  const [ctxA, ctxB] = [await browser.newContext(), await browser.newContext()]
  const [a, b] = [await ctxA.newPage(), await ctxB.newPage()]
  try {
    const [ca, cb] = [await openCard(a, ask), await openCard(b, ask)]
    await ca.getByRole('radio', { name: 'Sans la vidéo' }).check()
    await cb.getByRole('radio', { name: 'Avec la vidéo' }).check()
    await Promise.all([ca.getByRole('button', { name: 'Valider', exact: true }).click(), cb.getByRole('button', { name: 'Refuser', exact: true }).click()])
    await expect.poll(async () => (await read(request, ask.approval)).status).not.toBe('pending')
    const status = (await read(request, ask.approval)).status as 'approved' | 'rejected'
    const [winner, loser] = status === 'approved' ? [ca, cb] : [cb, ca]
    await expect(winner.getByText(status === 'approved' ? 'validée' : 'refusée', { exact: true })).toBeVisible()
    await expect(loser.getByText('Traitée entre-temps par Loïc : ta décision n\'a pas été envoyée')).toBeVisible()
    await expect(loser.getByRole('alert')).toContainText('déjà')
    // the losing draft stays on screen and cannot be sent
    await expect(loser.getByRole('radio', { checked: true })).toBeVisible()
    await expect(loser.getByRole('button', { name: 'Valider', exact: true })).toBeDisabled()
    await expect(loser.getByRole('button', { name: 'Refuser', exact: true })).toBeDisabled()
  } finally {
    await ctxA.close(); await ctxB.close()
  }
})

test('une demande traitée ailleurs pendant la saisie : bandeau, saisie gardée', async ({ page, request }) => {
  const ask = await publish(request, 'mnema', 'question', 'ailleurs', {})
  const c = await openCard(page, ask)
  await c.getByRole('textbox', { name: 'Ta réponse' }).fill('Ma réponse trop tardive')
  const other = await request.post(`${API}/api/approvals/${ask.approval}/answer`, { data: { text: 'Déjà répondu' } })
  expect(other.ok()).toBeTruthy()
  await expect(c.getByText('Traitée entre-temps par Loïc : ta réponse n\'a pas été envoyée')).toBeVisible({ timeout: 5_000 })
  await expect(c.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('Ma réponse trop tardive')
  await expect(c.getByRole('button', { name: 'Répondre', exact: true })).toBeDisabled()
})

test('un agent publie une autre demande sous les yeux de Loïc : la saisie en cours reste', async ({ page, request }) => {
  test.setTimeout(60_000)
  const first = await publish(request, 'mnema', 'question', 'saisie-en-cours', {})
  const c = await openCard(page, first)
  await c.getByRole('textbox', { name: 'Ta réponse' }).fill('Je suis en train d\'écrire')
  const second = await publish(request, 'helios', 'question', 'nouvelle-demande', {})
  await expect(card(page, second)).toBeVisible({ timeout: 2_000 }) // arrives by the live channel
  await expect(c.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('Je suis en train d\'écrire')
  // and again after the periodic read
  await page.waitForTimeout(10_500)
  await expect(c.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('Je suis en train d\'écrire')
})

test('une demande expirée ne peut plus être traitée', async ({ page, request }) => {
  test.setTimeout(120_000)
  const soon = new Date(Date.now() + 61_000).toISOString() // the server refuses less than a minute
  const ask = await publish(request, 'helios', 'needs_human', 'expire-vite', { ...validation, expires_at: soon })
  const c = await openCard(page, ask)
  await expect(c.getByText(/^expire dans/)).toBeVisible()
  await c.getByRole('radio', { name: 'Avec la vidéo' }).check()
  await expect(c.getByText('expirée', { exact: true })).toBeVisible({ timeout: 80_000 })
  await expect(c.getByText('Expirée entre-temps : ta décision n\'a pas été envoyée')).toBeVisible()
  await expect(c.getByRole('button', { name: 'Valider', exact: true })).toBeDisabled()
  expect((await read(request, ask.approval)).status).toBe('expired')
})
