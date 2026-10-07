import { expect, test, type Page, type Route } from '@playwright/test'
import { TOKEN_KEY } from './e2e-env'

const TOKEN = process.env.NEXUS_E2E_TOKEN ?? ''
const NO_TOKEN = { cookies: [], origins: [] }
const OTHER_TOKEN = 'nxt_' + 'B'.repeat(43) // well formed, unknown to the server

const stored = (page: Page) => page.evaluate((key) => localStorage.getItem(key), TOKEN_KEY)

const refuse = (route: Route, code: string) =>
  route.fulfill({
    status: 401,
    contentType: 'application/json',
    headers: { 'WWW-Authenticate': 'Bearer' },
    json: { detail: { code, message: 'refus simulé' } },
  })

/**
 * Plays the server of PR 3: every API route but the health check answers 401 unless the request
 * carries the real token. The real server does not require it yet.
 */
async function requireToken(page: Page) {
  const seen: (string | undefined)[] = []
  await page.route(
    (url) => url.pathname.startsWith('/api/') && url.pathname !== '/api/health',
    (route) => {
      const auth = route.request().headers()['authorization']
      seen.push(auth)
      if (auth === `Bearer ${TOKEN}`) return route.continue()
      return refuse(route, auth ? 'invalid_token' : 'auth_required')
    },
  )
  return seen
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

  test('un serveur qui n’exige pas de jeton : l’application marche, sans écran verrouillé', async ({ page }) => {
    await page.goto('/#/travail')
    await expect(page.getByRole('heading', { name: 'Travail' })).toBeVisible()
    await expect(lockTitle(page)).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Oublier le jeton' })).toHaveCount(0)
  })

  test('un 401 de l’API affiche l’écran verrouillé : titre, consigne, champ focalisé', async ({ page }) => {
    await requireToken(page)
    await page.goto('/#/travail')

    await expect(lockTitle(page)).toBeVisible()
    await expect(page.locator('code')).toHaveText('nexus-token issue loic --label navigateur')
    await expect(tokenField(page)).toHaveAttribute('type', 'password')
    await expect(tokenField(page)).toBeFocused()
    await expect(page.getByRole('navigation', { name: 'Vues' })).toHaveCount(0)
  })

  test('un jeton au mauvais format : erreur qui nomme le champ, sans le recopier, rien n’est stocké', async ({ page }) => {
    const seen = await requireToken(page)
    await page.goto('/#/travail')
    await expect(lockTitle(page)).toBeVisible()
    const before = seen.length

    await tokenField(page).fill('trop-court-CONFIDENTIEL')
    await page.keyboard.press('Enter')

    const alert = page.getByRole('alert')
    await expect(alert).toContainText('Jeton d’accès : format invalide')
    await expect(alert).not.toContainText('CONFIDENTIEL')
    await expect(tokenField(page)).toHaveAttribute('aria-invalid', 'true')
    expect(await stored(page)).toBeNull()
    expect(seen.length).toBe(before) // nothing was sent to the API
  })

  test('le vrai jeton déverrouille : les données se relisent avec Authorization et le temps réel est là', async ({ page }) => {
    const seen = await requireToken(page)
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
    await requireToken(page)
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
  await page.addInitScript(([key, token]) => localStorage.setItem(key, token), [TOKEN_KEY, OTHER_TOKEN])
  await page.route(
    (url) => url.pathname.startsWith('/api/') && url.pathname !== '/api/health',
    (route) => refuse(route, 'invalid_token'),
  )
  await page.goto('/#/travail')

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
