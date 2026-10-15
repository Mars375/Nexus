import { expect, test, type Page, type Route } from '@playwright/test'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { TOKEN_KEY, dataDirPath } from './e2e-env'

const TOKEN = process.env.NEXUS_E2E_TOKEN ?? ''
const NO_TOKEN = { cookies: [], origins: [] }
const OTHER_TOKEN = 'nxt_' + 'B'.repeat(43) // well formed, unknown to the server

const stored = (page: Page) => page.evaluate((key) => localStorage.getItem(key), TOKEN_KEY)

/** A 401 in the middle of an edit cannot be provoked on the real server: only these two tests mock it. */
const refuse = (route: Route, code: string) =>
  route.fulfill({
    status: 401,
    contentType: 'application/json',
    headers: { 'WWW-Authenticate': 'Bearer' },
    json: { detail: { code, message: 'refus simulé' } },
  })

/**
 * Notes the `Authorization` header of every API request the page sends, without touching them:
 * the server is the real one and answers 401 by itself since PR 3 (ADR-020).
 */
async function recordAuthorization(page: Page) {
  const seen: (string | undefined)[] = []
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) => {
      seen.push(route.request().headers()['authorization'])
      return route.continue()
    },
  )
  return seen
}

/** Runs the product's own CLI against the throwaway database of the test server. */
function nexusToken(...args: string[]) {
  const done = spawnSync('uv', ['run', '--directory', '../server', 'nexus-token', ...args], {
    cwd: fileURLToPath(new URL('..', import.meta.url)),
    env: { ...process.env, NEXUS_DATA_DIR: dataDirPath() },
    encoding: 'utf8',
  })
  expect(done.status, done.stderr).toBe(0)
  return done
}

const lockTitle = (page: Page) => page.getByRole('heading', { name: 'Nexus verrouillé' })
const tokenField = (page: Page) => page.getByLabel('Jeton d’accès')

test('le jeton émis pour les tests est dans le localStorage et part dans Authorization', async ({ page }) => {
  expect(TOKEN).toMatch(/^nxt_[A-Za-z0-9_-]{43}$/)
  const request = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/tasks')
  await page.goto('/#/travail')
  expect((await request).headers()['authorization']).toBe(`Bearer ${TOKEN}`)
  expect(await stored(page)).toBe(TOKEN)
  await expect(lockTitle(page)).toHaveCount(0)
})

test('le contrôle de santé reste anonyme', async ({ page }) => {
  const health = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/health')
  await page.goto('/#/travail')
  expect((await health).headers()['authorization']).toBeUndefined()
})

test.describe('sans jeton stocké', () => {
  test.use({ storageState: NO_TOKEN })

  test('un navigateur sans jeton : le vrai serveur répond 401 et Nexus reste verrouillé', async ({ page }) => {
    const seen = await recordAuthorization(page)
    const refused = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/tasks' && r.status() === 401)
    await page.goto('/#/travail')
    expect((await (await refused).json()).detail.code).toBe('auth_required')

    await expect(lockTitle(page)).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Travail' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Oublier le jeton' })).toHaveCount(0)
    expect(seen.filter((auth) => auth !== undefined)).toEqual([]) // nothing to send: nothing was sent
  })

  test('un 401 de l’API affiche l’écran verrouillé : titre, consigne, champ focalisé', async ({ page }) => {
    await page.goto('/#/travail')

    await expect(lockTitle(page)).toBeVisible()
    await expect(page.locator('code')).toHaveText('nexus-token issue loic --label navigateur')
    await expect(tokenField(page)).toHaveAttribute('type', 'password')
    await expect(tokenField(page)).toBeFocused()
    await expect(page.getByRole('navigation', { name: 'Vues' })).toHaveCount(0)
  })

  test('un jeton au mauvais format : erreur qui nomme le champ, sans le recopier, rien n’est stocké', async ({ page }) => {
    const seen = await recordAuthorization(page)
    await page.goto('/#/travail')
    await expect(lockTitle(page)).toBeVisible()
    // The app stays mounted under the lock screen and may keep polling (without a token): only a request carrying one would be a leak.
    const sentWithToken = () => seen.filter((auth) => auth !== undefined).length
    const before = sentWithToken()

    await tokenField(page).fill('trop-court-CONFIDENTIEL')
    await page.keyboard.press('Enter')

    const alert = page.getByRole('alert')
    await expect(alert).toContainText('Jeton d’accès : format invalide')
    await expect(alert).not.toContainText('CONFIDENTIEL')
    await expect(tokenField(page)).toHaveAttribute('aria-invalid', 'true')
    expect(await stored(page)).toBeNull()
    expect(sentWithToken()).toBe(before) // the typed value was never sent to the API
    expect(seen.some((auth) => auth?.includes('trop-court-CONFIDENTIEL'))).toBe(false)
  })

  test('le vrai jeton déverrouille : les données se relisent avec Authorization et le temps réel est là', async ({ page }) => {
    const seen = await recordAuthorization(page)
    await page.goto('/#/travail')
    await expect(lockTitle(page)).toBeVisible()

    await tokenField(page).fill(TOKEN)
    await page.getByRole('button', { name: 'Déverrouiller' }).click()

    await expect(lockTitle(page)).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Travail' })).toBeVisible()
    await expect(page.getByRole('main').getByText(/^source : nexus\.db · mesuré/)).toBeVisible()
    await expect(page.getByText('Temps réel : connecté')).toBeVisible()
    expect(await stored(page)).toBe(TOKEN)
    expect(seen).toContain(`Bearer ${TOKEN}`)
    await expect(page.locator('body')).not.toContainText(TOKEN)
  })

  test('un jeton bien formé mais refusé par le serveur est oublié et ramène à l’écran verrouillé', async ({ page }) => {
    await page.goto('/#/travail')
    await expect(lockTitle(page)).toBeVisible()

    await tokenField(page).fill(OTHER_TOKEN)
    await page.getByRole('button', { name: 'Déverrouiller' }).click()

    await expect(page.getByRole('status').filter({ hasText: 'refusé le jeton' })).toBeVisible()
    await expect(lockTitle(page)).toBeVisible()
    expect(await stored(page)).toBeNull()
  })
})

test('un jeton stocké puis révoqué : 401 invalid_token, jeton oublié, écran verrouillé', async ({ page }) => {
  const issued = nexusToken('issue', 'loic', '--label', 'revoque')
  const revoked = issued.stdout.trim()
  nexusToken('revoke', /nx-tok-[0-9]+/.exec(issued.stderr)![0])
  await page.addInitScript(([key, token]) => localStorage.setItem(key, token), [TOKEN_KEY, revoked])
  const refused = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/tasks' && r.status() === 401)
  await page.goto('/#/travail')

  expect((await (await refused).json()).detail.code).toBe('invalid_token')
  await expect(lockTitle(page)).toBeVisible()
  expect(await stored(page)).toBeNull()
})

test('un jeton révoqué pendant que l’interface est ouverte la verrouille et ferme le temps réel', async ({ page }) => {
  const issued = nexusToken('issue', 'loic', '--label', 'revoque-en-direct')
  const live = issued.stdout.trim()
  await page.addInitScript(([key, token]) => localStorage.setItem(key, token), [TOKEN_KEY, live])
  let closed = false
  // Only the Nexus socket: Vite's dev server keeps its own HMR WebSocket on the page.
  page.on('websocket', (ws) => {
    if (new URL(ws.url()).pathname === '/api/ws') ws.on('close', () => (closed = true))
  })
  await page.goto('/#/travail')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  expect(closed).toBe(false)

  // The first 401 on the revoked token comes either from the next REST refresh or from the ticket request,
  // whichever leaves first. A REST 401 clears the token and locks the UI, and a locked UI sends no ticket
  // request at all: so this is the only response the test can wait for in both orders.
  const revokedRefused = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname.startsWith('/api/') &&
      r.status() === 401 &&
      r.request().headers()['authorization'] === `Bearer ${live}`,
  )
  nexusToken('revoke', /nx-tok-[0-9]+/.exec(issued.stderr)![0])

  await expect.poll(() => closed).toBe(true) // the server closed the socket (4401)
  expect((await (await revokedRefused).json()).detail.code).toBe('invalid_token')
  await expect(lockTitle(page)).toBeVisible()
  expect(await stored(page)).toBeNull()
})

test('« Oublier le jeton » efface le jeton stocké', async ({ page }) => {
  await page.goto('/#/travail')
  const forget = page.getByRole('button', { name: 'Oublier le jeton' })
  await expect(forget).toBeVisible()
  expect(await stored(page)).toBe(TOKEN)

  await forget.click()

  await expect(forget).toHaveCount(0)
  expect(await stored(page)).toBeNull()
})

test('un 401 pendant une modification verrouille sans perdre le brouillon, et le déverrouillage le rend', async ({ page }) => {
  await page.goto('/#/travail')
  const title = 'Brouillon sous verrou'
  await page.getByRole('button', { name: 'Nouvelle tâche' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Nouvelle tâche' })
  await dialog.getByLabel('Titre').fill(title)
  await dialog.getByLabel('Objectif').fill('Vérifier que le verrou garde le brouillon')
  await dialog.getByRole('button', { name: 'Créer la tâche' }).click()
  await expect(dialog).toBeHidden()

  await page.getByRole('button', { name: new RegExp(`^${title} —`) }).click()
  const pane = page.getByRole('complementary', { name: new RegExp(`Détail de ${title}`) })
  await pane.getByLabel('Titre').fill(`${title} (modifié)`)

  await page.route(
    (url) => url.pathname.startsWith('/api/tasks/'),
    (route) => (route.request().method() === 'PATCH' ? refuse(route, 'invalid_token') : route.fallback()),
  )
  await pane.getByRole('button', { name: 'Enregistrer' }).click()

  await expect(lockTitle(page)).toBeVisible()
  await expect(tokenField(page)).toBeFocused()
  // The app is still there, under the lock screen, but inert and hidden from assistive technology.
  await expect(page.locator('[inert][aria-hidden="true"]')).toHaveCount(1)
  await expect(page.getByRole('navigation', { name: 'Vues' })).toHaveCount(0)

  await page.unroute((url) => url.pathname.startsWith('/api/tasks/'))
  await tokenField(page).fill(TOKEN)
  await page.getByRole('button', { name: 'Déverrouiller' }).click()

  await expect(lockTitle(page)).toHaveCount(0)
  await expect(page.locator('[inert]')).toHaveCount(0)
  await expect(pane.getByLabel('Titre')).toHaveValue(`${title} (modifié)`)
})

test('un 401 pendant « Nouvelle tâche » ferme la modale : le jeton se saisit à la souris, le brouillon revient', async ({ page }) => {
  await page.goto('/#/travail')
  await page.getByRole('button', { name: 'Nouvelle tâche' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Nouvelle tâche' })
  await dialog.getByLabel('Titre').fill('Brouillon modale')
  await dialog.getByLabel('Objectif').fill('Garder le brouillon sous le verrou')

  await page.route(
    (url) => url.pathname === '/api/tasks',
    (route) => (route.request().method() === 'POST' ? refuse(route, 'invalid_token') : route.fallback()),
  )
  await dialog.getByRole('button', { name: 'Créer la tâche' }).click()

  await expect(lockTitle(page)).toBeVisible()
  await expect(dialog).toHaveCount(0)
  await tokenField(page).click() // a real mouse click: the page must not be under pointer-events: none
  await page.keyboard.type('texte-tape')
  await expect(tokenField(page)).toHaveValue('texte-tape')

  await page.unroute((url) => url.pathname === '/api/tasks')
  await tokenField(page).fill(TOKEN)
  await page.getByRole('button', { name: 'Déverrouiller' }).click()
  await expect(lockTitle(page)).toHaveCount(0)

  // The dialog's open state is kept by the view: it comes back by itself, draft included.
  const reopened = page.getByRole('dialog', { name: 'Nouvelle tâche' })
  await expect(reopened).toBeVisible()
  await expect(reopened.getByLabel('Titre')).toHaveValue('Brouillon modale')
  await expect(reopened.getByLabel('Objectif')).toHaveValue('Garder le brouillon sous le verrou')
})
