import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { API, auth, type Actor } from './api'

const RUN = Date.now() // subjects are unique: the database is shared with the other specs

type Published = { event: string; approval: string; subject: string }

/** An agent publishes a request for Loïc through the API (the token must be the actor's own). */
async function publish(
  request: APIRequestContext, actor: Actor, kind: 'question' | 'needs_human', slug: string, payload: Record<string, unknown>, text?: string,
): Promise<Published> {
  const subject = `${slug} ${RUN}`
  const res = await request.post(`${API}/api/events`, {
    headers: auth(actor),
    data: { id: `evt_appr_${slug}_${RUN}`.replace(/\W/g, '_'), at: new Date().toISOString(), actor, kind, subject, needs: ['loic'], payload, ...(text && { body: text }) },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  const body = await res.json()
  const approval = (body.effects as { action: string; approval: string }[]).find((e) => e.action === 'approval')!.approval
  return { event: body.id, approval, subject }
}

const read = async (request: APIRequestContext, ref: string) => (await request.get(`${API}/api/approvals/${ref}`, { headers: auth() })).json()
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
  const other = await request.post(`${API}/api/approvals/${ask.approval}/answer`, { headers: auth(), data: { text: 'Déjà répondu' } })
  expect(other.ok()).toBeTruthy()
  await expect(c.getByText('Traitée entre-temps par Loïc : ta réponse n\'a pas été envoyée')).toBeVisible({ timeout: 5_000 })
  await expect(c.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('Ma réponse trop tardive')
  await expect(c.getByRole('button', { name: 'Répondre', exact: true })).toBeDisabled()
})

test('un agent publie une autre demande sous les yeux de Loïc : la saisie en cours reste', async ({ page, request }) => {
  const first = await publish(request, 'mnema', 'question', 'saisie-en-cours', {})
  const c = await openCard(page, first)
  await c.getByRole('textbox', { name: 'Ta réponse' }).fill('Je suis en train d\'écrire')
  const reread = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/now' && r.ok())
  const second = await publish(request, 'helios', 'question', 'nouvelle-demande', {})
  await reread // the live channel makes the page read Maintenant again
  await expect(card(page, second)).toBeVisible()
  await expect(c.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('Je suis en train d\'écrire')
  await expect(c.getByText('Traitée entre-temps')).toHaveCount(0)
})

test('une demande qui expire pendant la saisie : bandeau, brouillon gardé, envoi bloqué', async ({ page, request }) => {
  // The server refuses a deadline under one minute: the clock is not waited for, the read is rewritten.
  const ask = await publish(request, 'helios', 'needs_human', 'expire-vite', { ...validation, expires_at: new Date(Date.now() + 65_000).toISOString() })
  const c = await openCard(page, ask)
  await expect(c.getByText(/^expire dans/)).toBeVisible()
  await c.getByRole('radio', { name: 'Avec la vidéo' }).check()
  await page.route('**/api/now', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    for (const a of body.asks) {
      if (a.event === ask.event) a.approval = { ...a.approval, status: 'expired', expires_at: new Date(Date.now() - 60_000).toISOString() }
    }
    await route.fulfill({ response: res, json: body })
  })
  await publish(request, 'mnema', 'question', 'declencheur-relecture', {}) // live message: Maintenant is read again
  await expect(c.getByText('Expirée entre-temps : ta décision n\'a pas été envoyée')).toBeVisible()
  await expect(c.getByRole('radio', { name: 'Avec la vidéo' })).toBeChecked()
  await expect(c.getByRole('button', { name: 'Valider', exact: true })).toBeDisabled()
  await expect(c.getByRole('button', { name: 'Refuser', exact: true })).toBeDisabled()
  expect((await read(request, ask.approval)).status).toBe('pending') // only the page's read was rewritten
})

test('un texte d\'agent sans coupure ne fait déborder ni la carte ni le panneau', async ({ page, request }) => {
  const url = 'https://exemple.test/' + 'a'.repeat(99) // 120 characters, no space
  const body = 'b'.repeat(300)
  const long = await publish(request, 'helios', 'needs_human', 'texte-long', { consequence: 'c'.repeat(200), options: [url, 'Court'] }, body)
  const question = await publish(request, 'mnema', 'question', 'texte-long-question', { options: [url] }, body)
  for (const width of [1440, 1100, 760]) {
    await page.setViewportSize({ width, height: 1200 })
    for (const ask of [long, question]) {
      await page.goto('about:blank') // a fresh page: the card starts folded
      const c = await openCard(page, ask)
      await expect(c.getByRole('textbox').first()).toBeVisible()
      const m = await page.evaluate((id) => {
        const el = document.querySelector(`[data-ask="${id}"]`)!
        const aside = el.closest('aside')!
        const root = document.scrollingElement!
        return { card: [el.scrollWidth, el.clientWidth], aside: [aside.scrollWidth, aside.clientWidth], page: [root.scrollWidth, root.clientWidth] }
      }, ask.event)
      expect(m.card[0], `carte à ${width} px`).toBeLessThanOrEqual(m.card[1])
      expect(m.aside[0], `panneau à ${width} px`).toBeLessThanOrEqual(m.aside[1])
      expect(m.page[0], `page à ${width} px`).toBeLessThanOrEqual(m.page[1])
    }
  }
})
