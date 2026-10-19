import { act, fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { Floor } from './Floor'
import { screens, setupFloorTest, snap, stageOf } from './floorSupport'

setupFloorTest()

test('la scène est focalisable et porte un nom accessible', () => {
  render(<Floor snapshot={snap()} nodes={[]} />)
  const stage = screen.getByRole('group', { name: /pivoter/i })
  expect(stage.getAttribute('tabindex')).toBe('0')
  expect(stage.hasAttribute('data-stage')).toBe(true)
})

test('deux vrais boutons font tourner l\'étage d\'un quart de tour', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  const left = screen.getByRole('button', { name: 'Tourner l\'étage vers la gauche' })
  const right = screen.getByRole('button', { name: 'Tourner l\'étage vers la droite' })
  expect(left.tagName).toBe('BUTTON'); expect(left.getAttribute('type')).toBe('button')
  expect(screens(container)).toBe(3) // 0°
  fireEvent.click(right) // mouvement réduit : immédiat → 90°, écrans cachés
  expect(screens(container)).toBe(0)
  fireEvent.click(left)
  expect(screens(container)).toBe(3)
})

test('flèches gauche et droite tournent l\'étage, et reviennent', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  fireEvent.keyDown(stageOf(container), { key: 'ArrowRight' })
  expect(screens(container)).toBe(0)
  fireEvent.keyDown(stageOf(container), { key: 'ArrowLeft' })
  expect(screens(container)).toBe(3)
})

test('glisser fait pivoter puis cale sur un quart de tour', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  const stage = stageOf(container)
  fireEvent.pointerDown(stage, { clientX: 0, button: 0 })
  fireEvent.pointerMove(stage, { clientX: 100 }) // 40°
  fireEvent.pointerUp(stage, { clientX: 100 })
  expect(screens(container)).toBe(3) // 40° → 0°
  fireEvent.pointerDown(stage, { clientX: 0, button: 0 })
  fireEvent.pointerMove(stage, { clientX: 200 }) // 80°
  fireEvent.pointerUp(stage, { clientX: 200 })
  expect(screens(container)).toBe(0) // → 90°
})

test('un clic sur une étiquette après un glisser n\'ouvre pas la tâche, un clic simple oui', async () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  const link = screen.getByRole('link', { name: /Helios/ })
  const stage = stageOf(container)
  const clicked = vi.fn((e: Event) => e.preventDefault())
  link.addEventListener('click', clicked)
  fireEvent.pointerDown(link, { clientX: 0, button: 0 })
  fireEvent.pointerMove(link, { clientX: 120 })
  fireEvent.pointerUp(link, { clientX: 120 })
  fireEvent.click(link)
  expect(clicked).not.toHaveBeenCalled()
  await act(async () => { await new Promise((r) => setTimeout(r, 5)) })
  fireEvent.pointerDown(stage, { clientX: 0, button: 0 })
  fireEvent.pointerUp(stage, { clientX: 0 })
  fireEvent.click(link)
  expect(clicked).toHaveBeenCalledTimes(1)
})

test('l\'angle survit au remontage de la vue', () => {
  const first = render(<Floor snapshot={snap()} nodes={[]} />)
  fireEvent.click(screen.getByRole('button', { name: /vers la droite/ }))
  first.unmount()
  const second = render(<Floor snapshot={snap()} nodes={[]} />)
  expect(screens(second.container)).toBe(0)
})

test('la scène expose son angle courant', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  expect(stageOf(container).getAttribute('data-angle')).toBe('0')
  fireEvent.click(screen.getByRole('button', { name: /vers la gauche/ }))
  expect(stageOf(container).getAttribute('data-angle')).toBe('-90')
})

test('les liens des étiquettes ne se laissent pas glisser par le navigateur', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={[]} />)
  for (const a of container.querySelectorAll('a[data-label]')) expect(a.getAttribute('draggable')).toBe('false')
  const notCancelled = fireEvent.dragStart(screen.getByRole('link', { name: /Helios/ }))
  expect(notCancelled).toBe(false) // dragstart annulé : le glisser reste un glisser de pointeur
})
