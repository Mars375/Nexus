import { expect, test } from '@playwright/test'
import { API, auth } from './api'

const AT = new Date().toISOString()

test('un agent qui commence un run allume son poste en moins d\'une seconde', async ({ page, request }) => {
  await page.goto('/#/maintenant')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  const task = await (await request.post(`${API}/api/tasks`, { headers: auth(), data: { title: 'Pont e2e', objective: 'Tester Maintenant', status: 'todo', next_action: 'x' } })).json()
  for (const [kind, extra] of [['claimed', {}], ['working', { payload: { run_ref: 'session:e2e' } }]] as const) {
    const res = await request.post(`${API}/api/events`, { headers: auth('codex'), data: { id: `evt_e2e_${kind}_${Date.now()}`, at: AT, actor: 'codex', kind, subject: 's', task: task.id, ...extra } })
    expect(res.ok()).toBeTruthy()
  }
  await expect(page.locator('[data-agent="codex"]')).toHaveAttribute('data-run', 'true', { timeout: 1000 })
})

test('une question pour Loïc arrive sur sa table et dans les demandes reçues', async ({ page, request }) => {
  await page.goto('/#/maintenant')
  await expect(page.getByText('Temps réel : connecté')).toBeVisible()
  const res = await request.post(`${API}/api/events`, { headers: auth('mnema'), data: { id: `evt_e2e_q_${Date.now()}`, at: AT, actor: 'mnema', kind: 'question', subject: 'Quelle version de Python cibler ?', needs: ['loic'], payload: { options: ['3.12', '3.13'] } } })
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
    const task = await (await request.post(`${API}/api/tasks`, { headers: auth(), data: { title: `Tâche de ${agent} avec un titre assez long`, objective: 'Étiquettes', status: 'todo', next_action: 'x' } })).json()
    for (const [kind, extra] of [['claimed', {}], ['working', { payload: { run_ref: `session:lab-${agent}` } }]] as const) {
      const res = await request.post(`${API}/api/events`, { headers: auth(agent), data: { id: `evt_lab_${agent}_${kind}_${Date.now()}`, at: AT, actor: agent, kind, subject: 's', task: task.id, ...extra } })
      expect(res.ok()).toBeTruthy()
    }
  }
}

async function expectNoLabelOverlap(page: import('@playwright/test').Page, when: string) {
  const boxes = await page.locator('[data-label], [data-rack-label]').evaluateAll((els) => els.map((e) => {
    const r = e.getBoundingClientRect()
    // le texte compte aussi : une ligne plus large que l'étiquette déborderait sur sa voisine
    const spans = [...e.querySelectorAll('span')].map((s) => { const range = document.createRange(); range.selectNodeContents(s); return range.getBoundingClientRect() }).filter((q) => q.width > 0)
    const left = Math.min(r.left, ...spans.map((q) => q.left)), right = Math.max(r.right, ...spans.map((q) => q.right))
    return { id: e.getAttribute('data-label') ?? e.getAttribute('data-rack-label'), left, right, top: r.top, bottom: r.bottom }
  }))
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j]
    const hit = a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
    expect(hit, `${when} : ${a.id} recouvre ${b.id} ${JSON.stringify([a, b])}`).toBe(false)
  }
  // ni le coin « TA TABLE », ni la légende des baies, ni les boutons de rotation
  const fixed = await page.locator('[data-table-corner], [data-legend], [data-legend-summary], [data-stage] button, .floor-pick').evaluateAll((els) => els.map((e) => {
    const r = e.getBoundingClientRect()
    return { id: e.hasAttribute('data-table-corner') ? 'coin TA TABLE' : e.hasAttribute('data-legend') ? 'légende' : e.hasAttribute('data-legend-summary') ? 'résumé de la légende' : e.classList.contains('floor-pick') ? 'sélecteur d\'étage' : `bouton ${e.getAttribute('aria-label')}`, left: r.left, right: r.right, top: r.top, bottom: r.bottom }
  }))
  // table corner, legend, the rotation buttons, and with several floors the selector and its two buttons
  expect(fixed).toHaveLength(2 + (await page.locator('[data-stage] button').count()) + (await page.locator('.floor-pick').count()) + (await page.locator('[data-legend-summary]').count()))
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
  const res = await request.post(`${API}/api/events`, { headers: auth('hermes'), data: { id: `evt_e2e_rm_${Date.now()}`, at: AT, actor: 'hermes', kind: 'question', subject: 'Question mouvement réduit', needs: ['loic'], payload: { options: ['a', 'b'] } } })
  expect(res.ok()).toBeTruthy()
  const row = page.locator('.now-fresh', { hasText: 'Question mouvement réduit' })
  await expect(row).toBeVisible()
  await expect(row).toHaveCSS('background-color', 'rgba(251, 146, 60, 0.05)')
})

// --- Étages de baies (#36) : le serveur ne connaît que 4 nœuds, la réponse en simule 12 (ou 10)
const NODE_IDS = ['cortex', 'synapse', 'artemis', 'helios', 'n5', 'n6', 'n7', 'n8', 'n9', 'n10', 'n11', 'n12', 'n13', 'n14', 'n15', 'n16', 'n17', 'n18', 'n19', 'n20']
async function serveNodes(page: import('@playwright/test').Page, count = 12, offline: string[] = [], unknown: string[] = []) {
  // Offline and unknown nodes carry a last sighting, so their room labels really have three lines with « vu il y a ».
  const seen = new Date(Date.now() - 3 * 3_600_000).toISOString()
  await page.route('**/api/nodes', (route) => route.fulfill({
    json: NODE_IDS.slice(0, count).map((id) => ({ id, kind: 'homelab', guardian_agent: 'aether', status: offline.includes(id) ? 'offline' : unknown.includes(id) ? 'unknown' : 'online', last_seen: offline.includes(id) || unknown.includes(id) ? seen : null, detail: null, source: 'tailscale', measured_at: new Date().toISOString() })),
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

test('un nœud de l\'étage 3 hors ligne : la pastille de ▲ est rouge et l\'étiquette le dit', async ({ page }) => {
  await serveNodes(page, 12, ['n10'])
  await page.goto('/#/maintenant')
  const pip = page.locator('.floor-pip[data-side="up"]')
  await expect(pip).toBeVisible()
  await expect(pip).toHaveAttribute('data-alert', 'off')
  await expect(pip).toHaveCSS('background-color', 'rgb(248, 113, 113)')
  await expect(page.locator('[data-floor-label]')).toHaveText('Étage 1 / 3 · alerte : étage 3')
  await expect(page.getByRole('button', { name: 'Monter d\'un étage : un nœud hors ligne à l\'étage 3' })).toBeVisible()
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

test('▲ puis ▼ presque aussitôt : la couche de l\'étage 1 reste le même nœud, sa reprise remonte sans repli jusqu\'au plein opaque', async ({ page }) => {
  await serveNodes(page)
  await page.goto('/#/maintenant')
  const upButton = page.getByRole('button', { name: /^Monter d'un étage/ })
  await expect(upButton).toBeVisible()
  // Tag the very element, then sample it on every frame: a node moved or replaced loses the tag and replays its entry from opacity 0.
  // The click can be processed before the probe's first frame, so the pre-click
  // baseline is captured synchronously here instead of read back from samples[0]
  // (one less paint-vs-click race in the test itself).
  const baseline = await page.evaluate(() => {
    type Probe = { samples: { same: boolean; opacity: number; role: string | null; animation: boolean; transitionFrom: number | null }[]; run: boolean }
    const w = window as unknown as { __probe: Probe; __layer: Element }
    w.__layer = document.querySelector('.level[data-level="1"]')!
    w.__layer.setAttribute('data-probe', '1')
    w.__probe = { samples: [], run: true }
    const tick = () => {
      const el = document.querySelector('.level[data-level="1"]')
      if (el) {
        // A fade transition carries the opacity it starts from: a replay from 0 through a transition
        // is invisible to the CSSAnimation flag, so its start value is sampled too.
        const fade = el.getAnimations().find((a): a is CSSTransition => a instanceof CSSTransition && a.transitionProperty === 'opacity')
        const start = fade ? (fade.effect as KeyframeEffect | null)?.getKeyframes()[0]?.opacity : undefined
        w.__probe.samples.push({ same: el === w.__layer && w.__layer.isConnected, opacity: Number(getComputedStyle(el).opacity), role: el.getAttribute('data-role'), animation: el.getAnimations().some((a) => !(a instanceof CSSTransition)), transitionFrom: start == null ? null : Number(start) })
      }
      if (w.__probe.run) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
    return Number(getComputedStyle(w.__layer).opacity)
  })
  await upButton.click()
  await expect(page.locator('[data-stage]')).toHaveAttribute('data-floor', '2')
  await page.waitForTimeout(40)
  await page.getByRole('button', { name: /^Descendre d'un étage/ }).click()
  await expect(page.locator('[data-stage]')).toHaveAttribute('data-floor', '1')
  await page.waitForTimeout(600)
  const samples = await page.evaluate(() => { const w = window as unknown as { __probe: { samples: { same: boolean; opacity: number; role: string | null; animation: boolean; transitionFrom: number | null }[]; run: boolean } }; w.__probe.run = false; return w.__probe.samples })
  expect(samples.length).toBeGreaterThan(20)
  expect(samples.every((q) => q.same), 'le nœud de l\'étage 1 a été remplacé').toBe(true)
  expect(baseline, 'avant le mouvement, la couche est opaque').toBe(1)
  // How deep the leaving fade gets depends on when the return click lands (timing, not design: the
  // "never under 0.3" threshold of the first version drifted, and "never 0" failed as soon as the
  // leaving ran to the end — issue #59). What holds at any speed: the layer stays the same node, the
  // reprise never drops, and it ends opaque.
  // The reprise is read from the first sample after the last "leaving" one. The transition reverses
  // from the value it had reached at the switch, one frame after the last "leaving" sample, so the first
  // reprise frame sits below it by about one frame of the fade: with `ease` over 350 ms the fade drops
  // up to ~0.11 per 16.7 ms frame, ~0.22 over two frames (one normal frame plus one skipped on a loaded
  // CI), hence the 0.25 tolerance. The return click is sent 40 ms after the lift, and measured runs put
  // the last leaving sample between 0.34 and 0.62, so a restart from 0 fails the opacity assertion.
  // The tolerance cannot catch a replay from 0 once the leaving got low (a slow machine: threshold
  // <= 0), so two direct guards run alongside it, independent of that depth. No animation other than a
  // CSS transition may run on the layer during the reprise (issue #109): a CSS animation replaying a
  // keyframe entry, or one started through `element.animate()`. And no fade transition may start below
  // the in-flight value, nor at exactly 0 while the leaving was still visible (above `visible`: the fade
  // tail is positive but invisible, and a healthy switch landing there legitimately starts from 0).
  // Being the same node forbids none of these: an @starting-style or an inline opacity reset followed
  // by the `.level` transition produces a CSSTransition, which the animation flag never sees.
  const tolerance = 0.25
  const visible = 0.05
  const dernierDepart = samples.findLastIndex((q) => q.role === 'leaving')
  expect(dernierDepart, 'l\'étage 1 est passé par l\'état leaving').toBeGreaterThanOrEqual(0)
  const reprise = samples.slice(dernierDepart + 1)
  expect(reprise.length, 'la reprise a été vue').toBeGreaterThanOrEqual(2)
  const laisse = samples[dernierDepart].opacity
  expect(reprise.every((q) => !q.animation), 'la reprise rejoue une animation CSS sur le même nœud').toBe(true)
  expect(reprise.every((q) => q.transitionFrom === null || (q.transitionFrom >= laisse - tolerance && !(q.transitionFrom === 0 && laisse > visible))), 'la reprise rejoue son entrée depuis zéro par une transition').toBe(true)
  expect(reprise[0].opacity, 'la reprise repart de zéro').toBeGreaterThanOrEqual(laisse - tolerance)
  for (let i = 1; i < reprise.length; i++) {
    expect(reprise[i].opacity, 'la reprise replonge au lieu de remonter').toBeGreaterThanOrEqual(reprise[i - 1].opacity)
  }
  expect(reprise[reprise.length - 1].opacity, 'la reprise finit opaque').toBe(1)
  await expect(page.locator('.level')).toHaveCount(1)
  await expect(page.locator('.level')).toHaveCSS('opacity', '1')
  await expect(page.locator('.level')).toHaveCSS('transform', 'none')
})

test('un étage disparaît pendant l\'ascenseur : le repli est instantané, la couche reprise ne glisse ni ne fond', async ({ page }) => {
  let count = 12
  await page.route('**/api/nodes', (route) => route.fulfill({
    json: NODE_IDS.slice(0, count).map((id) => ({ id, kind: 'homelab', guardian_agent: 'aether', status: 'online', last_seen: null, detail: null, source: 'tailscale', measured_at: new Date().toISOString() })),
  }))
  await page.goto('/#/maintenant')
  const upButton = page.getByRole('button', { name: /^Monter d'un étage/ })
  await expect(upButton).toBeVisible()
  await page.evaluate(() => {
    const w = window as unknown as { __snap: { opacity: number; transform: string }[]; __run: boolean }
    w.__snap = []; w.__run = true
    const tick = () => {
      const el = document.querySelector('.level[data-level="2"][data-role="current"]')
      if (el && document.querySelector('[data-stage]')!.getAttribute('data-floor-count') === '2') w.__snap.push({ opacity: Number(getComputedStyle(el).opacity), transform: getComputedStyle(el).transform })
      if (w.__run) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
  await upButton.click(); await page.waitForTimeout(40); await upButton.click() // 1 → 2 → 3, floor 2 is leaving
  await page.waitForTimeout(150)
  count = 6 // floor 3 disappears: the read that says so arrives within the lift
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange', { bubbles: true })))
  await expect(page.locator('[data-stage]')).toHaveAttribute('data-floor-count', '2')
  await page.waitForTimeout(500)
  const snaps = await page.evaluate(() => { const w = window as unknown as { __snap: { opacity: number; transform: string }[]; __run: boolean }; w.__run = false; return w.__snap })
  expect(snaps.length).toBeGreaterThan(5)
  expect(snaps.filter((q) => q.opacity !== 1 || q.transform !== 'none'), 'la couche de l\'étage 2 a glissé ou fondu après le repli').toHaveLength(0)
  await expect(page.locator('[data-stage]')).toHaveAttribute('data-floor', '2')
  await expect(page.locator('.level')).toHaveCount(1)
})

for (const width of [1440, 1400, 1366, 1100]) for (const [count, floor] of [[12, 2], [10, 3]] as const) {
  test(`salle des serveurs (étage ${floor}, ${count} nœuds) : aucune étiquette de baie n'en recouvre une autre ni un coin fixe, avant et après un glisser, à ${width} px`, async ({ page }) => {
    await serveNodes(page, count, ['n6', 'n10'], ['n7'])
    await page.setViewportSize({ width, height: width === 1366 ? 768 : width === 1400 ? 600 : 900 })
    await page.goto('/#/maintenant')
    const stage = page.locator('[data-stage]')
    await expect(page.getByRole('button', { name: /^Monter d'un étage/ })).toBeVisible()
    for (let i = 1; i < floor; i++) await page.getByRole('button', { name: /^Monter d'un étage/ }).click()
    await expect(stage).toHaveAttribute('data-floor', String(floor))
    await page.waitForTimeout(500)
    await expect(page.locator('[data-rack-label]')).toHaveCount(floor === 3 ? count - 8 : 4)
    // the labels measured are the real three-line ones
    await expect(page.locator('[data-rack-label]').filter({ hasText: 'vu il y a' }).first()).toBeVisible()
    await expectNoLabelOverlap(page, `étage ${floor} à 0°`)
    const box = (await stage.boundingBox())!
    const x = box.x + box.width / 2, y = box.y + box.height * 0.8
    await page.mouse.move(x, y); await page.mouse.down()
    await page.mouse.move(x + 100, y, { steps: 5 }); await page.mouse.move(x + 200, y, { steps: 5 })
    await page.mouse.up()
    await expect(stage).toHaveAttribute('data-angle', '90')
    await expectNoLabelOverlap(page, `étage ${floor} à 90° après un glisser`)
    for (const quarter of ['180', '270', '360']) {
      await page.getByRole('button', { name: 'Tourner l\'étage vers la droite' }).click()
      await expect(stage).toHaveAttribute('data-angle', quarter)
      await expectNoLabelOverlap(page, `étage ${floor} à ${quarter}°`)
    }
  })
}

for (const width of [800, 1440]) {
  test(`20 nœuds, alertes sur 4 étages cachés : l'étiquette du sélecteur reste dans sa zone et ne recouvre aucune étiquette, avant et après un glisser, à ${width} px`, async ({ page, request }) => {
    await seedAllAgents(request)
    await serveNodes(page, 20, ['n6', 'n14'], ['n10', 'n18'])
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/#/maintenant')
    const stage = page.locator('[data-stage]'), label = page.locator('[data-floor-label]')
    await expect(label).toHaveText('Étage 1 / 5 · alerte : étages 2, 3, 4, 5')
    await expect(page.locator('[data-label]')).toHaveCount(8)
    const insideZone = async (when: string) => {
      const s = (await stage.boundingBox())!, l = (await label.boundingBox())!
      // the reserved zone: 210 px wide, 40 px high, right under the rotation buttons (which stand 40 px tall)
      expect(l.x, `${when} : à gauche`).toBeGreaterThanOrEqual(s.x - 1); expect(l.x + l.width, `${when} : à droite`).toBeLessThanOrEqual(s.x + 210 + 1)
      expect(l.y, `${when} : en haut`).toBeGreaterThanOrEqual(s.y + 40 - 1); expect(l.y + l.height, `${when} : en bas`).toBeLessThanOrEqual(s.y + 80 + 1)
      await expectNoLabelOverlap(page, when)
    }
    await insideZone('0°')
    const box = (await stage.boundingBox())!
    const x = box.x + box.width / 2, y = box.y + box.height / 2
    await page.mouse.move(x, y); await page.mouse.down()
    await page.mouse.move(x + 100, y, { steps: 5 }); await page.mouse.move(x + 200, y, { steps: 5 })
    await page.mouse.up()
    await expect(stage).toHaveAttribute('data-angle', '90')
    await insideZone('90° après un glisser')
    for (const quarter of ['180', '270']) {
      await page.getByRole('button', { name: 'Tourner l\'étage vers la droite' }).click()
      await expect(stage).toHaveAttribute('data-angle', quarter)
      await insideZone(`${quarter}°`)
    }
  })
}
