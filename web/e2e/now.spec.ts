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

const AGENTS = ['helios', 'mnema', 'aether', 'artemis', 'claude', 'codex', 'orca', 'hermes'] as const

async function seedAllAgents(request: import('@playwright/test').APIRequestContext) {
  // La moitié des agents travaillent (étiquette avec titre long et durée), les autres restent inactifs.
  for (const agent of AGENTS.slice(0, 5)) {
    const task = await (await request.post(`${API}/api/tasks`, { data: { title: `Tâche de ${agent} avec un titre assez long`, objective: 'Étiquettes', status: 'todo', next_action: 'x' } })).json()
    for (const [kind, extra] of [['claimed', {}], ['working', { payload: { run_ref: `session:lab-${agent}` } }]] as const) {
      const res = await request.post(`${API}/api/events`, { data: { id: `evt_lab_${agent}_${kind}_${Date.now()}`, at: AT, actor: agent, kind, subject: 's', task: task.id, ...extra } })
      expect(res.ok()).toBeTruthy()
    }
  }
}

async function expectNoLabelOverlap(page: import('@playwright/test').Page, when: string) {
  const boxes = await page.locator('[data-label]').evaluateAll((els) => els.map((e) => {
    const r = e.getBoundingClientRect()
    // le texte compte aussi : une ligne plus large que l'étiquette déborderait sur sa voisine
    const spans = [...e.querySelectorAll('span')].map((s) => { const range = document.createRange(); range.selectNodeContents(s); return range.getBoundingClientRect() }).filter((q) => q.width > 0)
    const left = Math.min(r.left, ...spans.map((q) => q.left)), right = Math.max(r.right, ...spans.map((q) => q.right))
    return { id: e.getAttribute('data-label'), left, right, top: r.top, bottom: r.bottom }
  }))
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j]
    const hit = a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
    expect(hit, `${when} : ${a.id} recouvre ${b.id} ${JSON.stringify([a, b])}`).toBe(false)
  }
  // ni le coin « TA TABLE », ni la légende des baies, ni les boutons de rotation
  const fixed = await page.locator('[data-table-corner], [data-legend], [data-stage] button, .floor-pick').evaluateAll((els) => els.map((e) => {
    const r = e.getBoundingClientRect()
    return { id: e.hasAttribute('data-table-corner') ? 'coin TA TABLE' : e.hasAttribute('data-legend') ? 'légende' : e.classList.contains('floor-pick') ? 'sélecteur d\'étage' : `bouton ${e.getAttribute('aria-label')}`, left: r.left, right: r.right, top: r.top, bottom: r.bottom }
  }))
  // table corner, legend, the rotation buttons, and with several floors the selector and its two buttons
  expect(fixed).toHaveLength(2 + (await page.locator('[data-stage] button').count()) + (await page.locator('.floor-pick').count()))
  for (const a of boxes) for (const b of fixed) {
    const hit = a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
    expect(hit, `${when} : ${a.id} recouvre ${b.id} ${JSON.stringify([a, b])}`).toBe(false)
  }
}

for (const width of [1440, 1101, 1100, 800, 761]) {
  test(`aucune étiquette de poste n'en recouvre une autre à ${width} px`, async ({ page, request }) => {
    await seedAllAgents(request)
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#/maintenant')
    await expect(page.locator('[data-label]')).toHaveCount(8)
    await expectNoLabelOverlap(page, '0°')
  })

  test(`après un glisser, l'angle se cale et aucune étiquette n'en recouvre une autre à ${width} px`, async ({ page, request }) => {
    await seedAllAgents(request)
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#/maintenant')
    const stage = page.locator('[data-stage]')
    await expect(page.locator('[data-label]')).toHaveCount(8)
    await expect(stage).toHaveAttribute('data-angle', '0')
    const box = (await stage.boundingBox())!
    const x = box.x + box.width / 2, y = box.y + box.height / 2
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x + 100, y, { steps: 5 })
    await page.mouse.move(x + 200, y, { steps: 5 }) // 80° : pas encore calé
    await page.mouse.up()
    await expect(stage).toHaveAttribute('data-angle', '90') // calé après l'animation
    await expectNoLabelOverlap(page, '90°')
    for (const quarter of ['180', '270', '360']) {
      await page.getByRole('button', { name: 'Tourner l\'étage vers la droite' }).click()
      await expect(stage).toHaveAttribute('data-angle', quarter)
      await expectNoLabelOverlap(page, `${quarter}°`)
    }
  })
}

test('flèche gauche puis flèche droite : retour à l\'angle de départ', async ({ page }) => {
  await page.goto('/#/maintenant')
  const stage = page.locator('[data-stage]')
  await expect(stage).toHaveAttribute('data-angle', '0')
  await stage.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(stage).toHaveAttribute('data-angle', '-90')
  await page.keyboard.press('ArrowRight')
  await expect(stage).toHaveAttribute('data-angle', '0')
})

test('un glisser sur une étiquette de poste fait pivoter l\'étage sans ouvrir la tâche', async ({ page, request }) => {
  await seedAllAgents(request)
  await page.goto('/#/maintenant')
  const link = page.locator('a[data-label]').first()
  const b = (await link.boundingBox())!
  const x = b.x + b.width / 2, y = b.y + b.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + 120, y, { steps: 3 }) // 120 px = 48°
  await page.mouse.move(x + 200, y, { steps: 6 }) // 200 px = 80° : plus de 45°
  await page.mouse.up()
  await expect(page.locator('[data-stage]')).toHaveAttribute('data-angle', '90')
  expect(page.url()).toContain('#/maintenant')
})

test('mouvement réduit : une demande fraîche garde son fond ambre', async ({ page, request }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/#/maintenant')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  const res = await request.post(`${API}/api/events`, { data: { id: `evt_e2e_rm_${Date.now()}`, at: AT, actor: 'hermes', kind: 'question', subject: 'Question mouvement réduit', needs: ['loic'], payload: { options: ['a', 'b'] } } })
  expect(res.ok()).toBeTruthy()
  const row = page.locator('.now-fresh', { hasText: 'Question mouvement réduit' })
  await expect(row).toBeVisible()
  await expect(row).toHaveCSS('background-color', 'rgba(251, 146, 60, 0.05)')
})

// --- Étages de baies (#36) : le serveur ne connaît que 4 nœuds, la réponse en simule 12 (ou 10)
const NODE_IDS = ['cortex', 'synapse', 'artemis', 'helios', 'n5', 'n6', 'n7', 'n8', 'n9', 'n10', 'n11', 'n12']
async function serveNodes(page: import('@playwright/test').Page, count = 12, offline: string[] = []) {
  await page.route('**/api/nodes', (route) => route.fulfill({
    json: NODE_IDS.slice(0, count).map((id) => ({ id, kind: 'homelab', guardian_agent: 'aether', status: offline.includes(id) ? 'offline' : 'online', last_seen: null, detail: null, source: 'tailscale', measured_at: new Date().toISOString() })),
  }))
}

for (const width of [1440, 1100, 800]) {
  test(`12 nœuds : aucune étiquette ne recouvre une autre, un coin fixe ni le sélecteur d'étage à ${width} px`, async ({ page, request }) => {
    await seedAllAgents(request)
    await serveNodes(page)
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#/maintenant')
    await expect(page.locator('[data-label]')).toHaveCount(8)
    await expect(page.getByRole('button', { name: 'Monter d\'un étage' })).toBeVisible()
    await expectNoLabelOverlap(page, '0°')
    for (const quarter of ['90', '180', '270']) {
      await page.getByRole('button', { name: 'Tourner l\'étage vers la droite' }).click()
      await expect(page.locator('[data-stage]')).toHaveAttribute('data-angle', quarter)
      await expectNoLabelOverlap(page, `${quarter}°`)
    }
  })
}

test('étage 1 à 3 au clavier (PageUp) puis retour aux boutons', async ({ page }) => {
  await serveNodes(page)
  await page.goto('/#/maintenant')
  const stage = page.locator('[data-stage]')
  await expect(page.getByRole('button', { name: 'Monter d\'un étage' })).toBeVisible()
  await stage.focus()
  await page.keyboard.press('PageUp')
  await page.keyboard.press('PageUp')
  await expect(stage).toHaveAttribute('data-floor', '3')
  await expect(page.locator('.level')).toHaveCount(1)
  await expect(page.locator('g.rack')).toHaveCount(4)
  await expect(page.getByText('TA TABLE')).toBeVisible()
  await page.getByRole('button', { name: 'Descendre d\'un étage' }).click()
  await page.getByRole('button', { name: 'Descendre d\'un étage' }).click()
  await expect(stage).toHaveAttribute('data-floor', '1')
  await expect(page.locator('.desk').first()).toBeVisible()
})

test('un nœud de l\'étage 3 hors ligne : le repère de l\'étage 3 est visible et alerte', async ({ page }) => {
  await serveNodes(page, 12, ['n10'])
  await page.goto('/#/maintenant')
  const marker = page.locator('[data-floor-marker="3"]')
  await expect(marker).toBeVisible()
  await expect(marker).toHaveAttribute('data-alert', 'off')
  await expect(marker).toHaveCSS('background-color', 'rgb(248, 113, 113)')
})

test('deux clics rapides sur ▲ : étage 3, puis une seule couche pleinement opaque, rien de figé', async ({ page }) => {
  await serveNodes(page)
  await page.goto('/#/maintenant')
  const upButton = page.getByRole('button', { name: 'Monter d\'un étage' })
  await expect(upButton).toBeVisible()
  await upButton.click({ clickCount: 2, delay: 20 })
  const stage = page.locator('[data-stage]')
  await expect(stage).toHaveAttribute('data-floor', '3')
  await page.waitForTimeout(400)
  await expect(page.locator('.level')).toHaveCount(1)
  await expect(page.locator('.level')).toHaveCSS('opacity', '1')
  await expect(page.locator('.level')).toHaveCSS('transform', 'none')
})

test('▲ puis ▼ presque aussitôt : retour à l\'étage 1, une seule couche pleine, aucune image à opacité nulle', async ({ page }) => {
  await serveNodes(page)
  await page.goto('/#/maintenant')
  const upButton = page.getByRole('button', { name: 'Monter d\'un étage' })
  await expect(upButton).toBeVisible()
  await page.evaluate(() => {
    const w = window as unknown as { __opacities: number[]; __sampling: boolean }
    w.__opacities = []; w.__sampling = true
    const tick = () => { const el = document.querySelector('.level[data-level="1"]'); if (el) w.__opacities.push(Number(getComputedStyle(el).opacity)); if (w.__sampling) requestAnimationFrame(tick) }
    requestAnimationFrame(tick)
  })
  await upButton.click()
  await page.waitForTimeout(60)
  await page.getByRole('button', { name: 'Descendre d\'un étage' }).click()
  await expect(page.locator('[data-stage]')).toHaveAttribute('data-floor', '1')
  await page.waitForTimeout(500)
  const seen = await page.evaluate(() => { const w = window as unknown as { __opacities: number[]; __sampling: boolean }; w.__sampling = false; return w.__opacities })
  expect(seen.length).toBeGreaterThan(10)
  expect(Math.min(...seen)).toBeGreaterThan(0.3)
  await expect(page.locator('.level')).toHaveCount(1)
  await expect(page.locator('.level')).toHaveCSS('opacity', '1')
  await expect(page.locator('.level')).toHaveCSS('transform', 'none')
})
