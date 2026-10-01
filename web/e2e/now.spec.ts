import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8799'
const AT = new Date().toISOString()

test('un agent qui commence un run allume son poste en moins d\'une seconde', async ({ page, request }) => {
  await page.goto('/#/maintenant')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  const task = await (await request.post(`${API}/api/tasks`, { data: { title: 'Pont e2e', objective: 'Tester Maintenant', status: 'todo', next_action: 'x' } })).json()
  for (const [kind, extra] of [['claimed', {}], ['working', { payload: { run_ref: 'session:e2e' } }]] as const) {
    const res = await request.post(`${API}/api/events`, { data: { id: `evt_e2e_${kind}_${Date.now()}`, at: AT, actor: 'codex', kind, subject: 's', task: task.id, ...extra } })
    expect(res.ok()).toBeTruthy()
  }
  await expect(page.locator('[data-agent="codex"]')).toHaveAttribute('data-run', 'true', { timeout: 1000 })
})

test('une question pour Loïc arrive sur sa table et dans les demandes reçues', async ({ page, request }) => {
  await page.goto('/#/maintenant')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  const res = await request.post(`${API}/api/events`, { data: { id: `evt_e2e_q_${Date.now()}`, at: AT, actor: 'mnema', kind: 'question', subject: 'Quelle version de Python cibler ?', needs: ['loic'], payload: { options: ['3.12', '3.13'] } } })
  expect(res.ok()).toBeTruthy()
  const ref = (await res.json()).id as string
  await expect(page.locator(`[data-ticket="${ref}"]`)).toBeAttached({ timeout: 1000 })
  await expect(page.getByRole('complementary', { name: 'Système' }).getByText('Quelle version de Python cibler ?')).toBeVisible()
})

test('fenêtre étroite : la liste des agents remplace l\'étage', async ({ page }) => {
  await page.setViewportSize({ width: 720, height: 900 })
  await page.goto('/#/maintenant')
  await expect(page.getByRole('list', { name: 'Agents' })).toBeVisible()
  await expect(page.getByRole('img', { name: /Étage de Nexus/ })).toBeHidden()
})

test('à 760 px pile, l\'étage et la liste ne se montrent pas ensemble', async ({ page }) => {
  await page.setViewportSize({ width: 760, height: 900 })
  await page.goto('/#/maintenant')
  await expect(page.getByRole('img', { name: /Étage de Nexus/ })).toBeVisible()
  const list = await page.getByRole('list', { name: 'Agents' }).boundingBox()
  expect(list === null || list.width <= 1).toBeTruthy()
})
