import { expect, test, type Page } from '@playwright/test'

// Visual defects of #49: focus ring clipped, dialog opening jump, toast font and contrast.

async function createTask(page: Page, title: string) {
  await page.getByRole('button', { name: 'Nouvelle tâche' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Nouvelle tâche' })
  await dialog.getByLabel('Titre').fill(title)
  await dialog.getByLabel('Objectif').fill(`Objectif de ${title}`)
  await dialog.getByRole('button', { name: 'Créer la tâche' }).click()
  await expect(dialog).toBeHidden()
}

/** WCAG contrast ratio of two computed `rgb(…)` / `rgba(…)` colours (both opaque here). */
function contrast(a: string, b: string): number {
  const lum = (css: string) => {
    const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(css)
    if (!m) throw new Error(`unsupported colour: ${css}`)
    const [r, g, bl] = [m[1], m[2], m[3]].map((v) => {
      const c = Number(v) / 255
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl
  }
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

test('l’anneau de focus de la première carte est entièrement visible dans sa colonne', async ({ page }) => {
  await page.goto('/#/travail')
  await createTask(page, 'Carte du haut')
  await createTask(page, 'Carte du bas')
  // Newest first: take whichever card is the first of the column, not a given title.
  const first = page.locator('ul:has(button[aria-label^="Carte du haut"]) > li:first-child button')
  await page.keyboard.press('Tab') // keyboard modality: :focus-visible applies on focus()
  await first.focus()
  const geometry = await first.evaluate((el) => {
    const style = getComputedStyle(el)
    const grow = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset)
    const card = el.getBoundingClientRect()
    const list = el.closest('ul')!.getBoundingClientRect()
    return { outlineStyle: style.outlineStyle, ringTop: card.top - grow, ringBottom: card.bottom + grow, clipTop: list.top, clipBottom: list.bottom }
  })
  expect(geometry.outlineStyle).not.toBe('none')
  expect(geometry.ringTop).toBeGreaterThanOrEqual(geometry.clipTop)
  expect(geometry.ringBottom).toBeLessThanOrEqual(geometry.clipBottom)
})

const API = 'http://127.0.0.1:8799'
test('l’anneau de la première carte reste visible quand Shift+Tab la ramène dans une colonne défilée', async ({ page, request }) => {
  for (let i = 0; i < 14; i++) {
    const res = await request.post(`${API}/api/tasks`, { data: {
      title: `Défilement ${i}`, objective: `Objectif ${'x'.repeat(80)}`, status: 'todo',
      next_action: 'Suite assez longue pour tenir sur deux lignes dans la carte',
    } })
    expect(res.ok()).toBeTruthy()
  }
  await page.goto('/#/travail')
  const column = page.locator('section[aria-label="À faire"] ul')
  const cards = column.locator(':scope > li > button')
  await expect(cards.filter({ hasText: 'Défilement 13' })).toBeVisible()
  expect(await column.evaluate((ul) => ul.scrollHeight > ul.clientHeight), 'la colonne doit défiler').toBe(true)
  await page.keyboard.press('Tab') // keyboard modality: :focus-visible applies
  await cards.nth(1).focus()
  // Hide only the top half of the first card. Chrome brings a PARTLY hidden element to the nearest edge
  // (that is the clipping case); a fully hidden one is centred, which clamps to scrollTop 0 and hides the bug.
  await column.evaluate((ul) => {
    const first = ul.firstElementChild!.getBoundingClientRect()
    ul.scrollTop = first.top - ul.getBoundingClientRect().top + first.height / 2
  })
  await page.keyboard.press('Shift+Tab')
  await expect(cards.first()).toBeFocused()
  const r = await cards.first().evaluate((el) => {
    const s = getComputedStyle(el)
    const grow = parseFloat(s.outlineWidth) + parseFloat(s.outlineOffset)
    const ul = el.closest('ul')!
    return { outline: s.outlineStyle, ringTop: el.getBoundingClientRect().top - grow, clipTop: ul.getBoundingClientRect().top, scrollTop: ul.scrollTop }
  })
  expect(r.outline).not.toBe('none')
  expect(r.ringTop, JSON.stringify(r)).toBeGreaterThanOrEqual(r.clipTop - 0.5)
})

test('la boîte de dialogue reste centrée dès la première image de son animation', async ({ page }) => {
  await page.goto('/#/travail')
  // Pause the opening animation from its first frame: a slow machine must not see it already finished.
  await page.addStyleTag({ content: '[role=dialog]{animation-play-state:paused!important}' })
  await page.getByRole('button', { name: 'Nouvelle tâche' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Nouvelle tâche' })
  await expect(dialog).toBeVisible()
  const start = await dialog.evaluate((el) => {
    const animation = el.getAnimations().find((a) => (a as CSSAnimation).animationName === 'dialog-in')
    if (!animation) return null
    animation.pause()
    animation.currentTime = 0
    const box = el.getBoundingClientRect()
    return { x: box.left + box.width / 2, y: box.top + box.height / 2, w: innerWidth / 2, h: innerHeight / 2 }
  })
  expect(start, 'the dialog keeps an opening animation').not.toBeNull()
  // Horizontal centre is exact; vertically the 6 px rise of the animation is the only allowed offset.
  expect(Math.abs(start!.x - start!.w)).toBeLessThanOrEqual(1)
  expect(Math.abs(start!.y - start!.h)).toBeLessThanOrEqual(8)
})

test('les toasts utilisent la police du thème et un contraste d’au moins 4,5:1', async ({ page }) => {
  await page.goto('/#/travail')
  await createTask(page, 'Tâche à toaster')
  const toast = page.locator('[data-sonner-toast]').first()
  await expect(toast).toBeVisible()
  expect(await toast.evaluate((el) => getComputedStyle(el).fontFamily)).toMatch(/^"?Barlow"?,/)

  // Same element, same stylesheet: only the type changes, so every richColors pair is measured as rendered.
  const pairs = await toast.evaluate((el) => {
    const out: Record<string, { fg: string; bg: string }> = {}
    for (const type of ['success', 'error', 'info', 'warning']) {
      const clone = el.cloneNode(true) as HTMLElement
      clone.setAttribute('data-type', type)
      el.parentElement!.append(clone)
      const style = getComputedStyle(clone)
      out[type] = { fg: style.color, bg: style.backgroundColor }
      clone.remove()
    }
    return out
  })
  for (const [type, { fg, bg }] of Object.entries(pairs)) {
    expect(contrast(fg, bg), `${type}: ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5)
  }
})
