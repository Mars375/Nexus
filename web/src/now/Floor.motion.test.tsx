import { act, fireEvent, render } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { Floor } from './Floor'
import { approval } from './fixtures'
import { down, pickLabel, pip, setupFloorTest, snap, twelve, up } from './floorSupport'

setupFloorTest()

const motion = () => vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q }))
const animated = (c: HTMLElement) => c.querySelectorAll('[data-arriving], [data-role="leaving"], [data-from], .is-fresh, [data-roll]')

test('aucun mouvement au premier rendu', () => {
  const { container } = render(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString(), received_at: new Date().toISOString(), body: null, options: [], consequence: null, approval: approval() }],
  })} nodes={[]} />)
  expect(container.querySelector('.is-fresh')).toBeNull()
})

test('une demande qui arrive déclenche le mouvement de son fil', () => {
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={[]} />)
  rerender(<Floor snapshot={snap({
    asks: [{ event: 'nx-evt-7', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null, at: new Date().toISOString(), received_at: new Date().toISOString(), body: null, options: [], consequence: null, approval: approval() }],
  })} nodes={[]} />)
  expect(container.querySelector('[data-route="mnema"].is-fresh')).not.toBeNull()
})

test('aucun attribut ni classe d\'animation au premier rendu, même avec 12 nœuds et une alerte', () => {
  motion()
  const { container } = render(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />)
  expect(animated(container)).toHaveLength(0)
})

test('arriver sur une salle : data-arriving sur sa couche, --i sur ses baies, la couche de départ est marquée', () => {
  motion()
  vi.useFakeTimers()
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up())
  const layers = [...container.querySelectorAll('.level')]
  expect(layers.map((e) => [e.getAttribute('data-level'), e.getAttribute('data-role')])).toEqual([['1', 'leaving'], ['2', 'current']])
  const room = container.querySelector('.level[data-level="2"]')!
  expect(room.hasAttribute('data-arriving')).toBe(true)
  expect(room.getAttribute('data-from')).toBe('above')
  expect([...room.querySelectorAll('g.rack')].map((r) => (r as unknown as SVGElement).style.getPropertyValue('--i'))).toEqual(expect.arrayContaining(['0', '1', '2', '3']))
  const leaving = container.querySelector('.level[data-level="1"]')!
  expect(leaving.hasAttribute('inert')).toBe(true); expect(leaving.getAttribute('aria-hidden')).toBe('true')
  expect(leaving.getAttribute('data-from')).toBe('above')
  act(() => { vi.advanceTimersByTime(600) })
  expect(container.querySelectorAll('.level')).toHaveLength(1)
  expect(container.querySelector('[data-arriving]')).toBeNull()
  vi.useRealTimers()
})

test('le numéro d\'étage roule une fois, dans le sens du mouvement', () => {
  motion()
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  expect(container.querySelector('[data-roll]')).toBeNull()
  fireEvent.click(up())
  expect(container.querySelector('[data-roll]')!.getAttribute('data-roll')).toBe('up')
  fireEvent.click(down())
  expect(container.querySelector('[data-roll]')!.getAttribute('data-roll')).toBe('down')
})

test('une alerte qui apparaît sur un autre étage fait pulser la pastille du côté concerné, jamais pour l\'étage affiché', () => {
  motion()
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  expect(container.querySelector('.is-fresh')).toBeNull()
  rerender(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />)
  expect(pip(container, 'up')!.classList.contains('is-fresh')).toBe(true)
  expect(container.querySelectorAll('.is-fresh')).toHaveLength(1)
})

test('une alerte NOUVELLE sur l\'étage affiché n\'a ni pastille, ni texte d\'étiquette, ni nom de bouton, ni pulsation', () => {
  motion()
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up()) // floor 3, no alert there yet
  rerender(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />) // a brand new alert appears on the floor shown
  expect(pickLabel()).toBe('Étage 3 / 3')
  expect(pip(container, 'up')).toBeNull(); expect(pip(container, 'down')).toBeNull()
  expect(down()).toHaveAccessibleName('Descendre d\'un étage')
  expect(container.querySelector('.is-fresh')).toBeNull()
  fireEvent.click(down()); fireEvent.click(down()) // leave it: now it is out of sight and counts
  expect(pickLabel()).toBe('Étage 1 / 3 · alerte : étage 3')
})

test('mouvement réduit : ni couche qui part, ni data-arriving, ni is-fresh, ni numéro qui roule', () => {
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />) // beforeEach: reduced motion
  fireEvent.click(up())
  expect(container.querySelectorAll('.level')).toHaveLength(1)
  rerender(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />)
  expect(container.querySelectorAll('[data-arriving], [data-role="leaving"], .is-fresh, [data-roll]')).toHaveLength(0)
})

test('repli quand l\'étage disparaît après un mouvement : instantané, sans numéro qui roule ni couche qui glisse', () => {
  motion()
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up())
  rerender(<Floor snapshot={snap()} nodes={twelve().slice(0, 6)} />)
  expect(pickLabel()).toBe('Étage 2 / 2')
  expect(container.querySelectorAll('[data-roll], [data-from], [data-arriving], [data-role="leaving"]')).toHaveLength(0)
  expect(container.querySelectorAll('.level')).toHaveLength(1)
})

test('aller-retour rapide 1 → 2 → 1 : les couches gardent leur ordre dans le DOM, aucune n\'est détachée puis rattachée', () => {
  motion()
  vi.useFakeTimers()
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  const stage = container.querySelector('.levels')!
  const office = container.querySelector('.level[data-level="1"]')
  const watch = new MutationObserver(() => {}); watch.observe(stage, { childList: true })
  fireEvent.click(up())
  expect([...container.querySelectorAll('.level')].map((e) => e.getAttribute('data-level'))).toEqual(['1', '2'])
  fireEvent.click(down())
  expect([...container.querySelectorAll('.level')].map((e) => e.getAttribute('data-level'))).toEqual(['1', '2'])
  expect(container.querySelector('.level[data-level="1"]')).toBe(office)
  expect(container.querySelector('.level[data-level="1"]')!.getAttribute('data-role')).toBe('current')
  // a node moved by insertBefore shows up as removed and re-added
  expect(watch.takeRecords().flatMap((r) => [...r.removedNodes]).filter((n) => n === office)).toHaveLength(0)
  watch.disconnect()
  vi.useRealTimers()
})

test('repli pendant l\'ascenseur : les couches reçoivent data-snap (aucune transition) tant qu\'aucun mouvement ne suit', () => {
  motion()
  vi.useFakeTimers()
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up())
  expect(container.querySelector('[data-snap]')).toBeNull()
  rerender(<Floor snapshot={snap()} nodes={twelve().slice(0, 6)} />)
  expect([...container.querySelectorAll('.level')].map((e) => e.hasAttribute('data-snap'))).toEqual([true])
  fireEvent.click(down())
  expect(container.querySelector('[data-snap]')).toBeNull()
  vi.useRealTimers()
})
