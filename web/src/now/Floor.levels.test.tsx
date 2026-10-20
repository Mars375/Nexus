import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { Floor } from './Floor'
import { down, node, pickLabel, pip, setupFloorTest, snap, stageOf, twelve, up } from './floorSupport'

setupFloorTest()

test('le nom de la scène cite PageUp et PageDown seulement quand il y a plusieurs étages', () => {
  const { container, unmount } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  expect(stageOf(container).getAttribute('aria-label')).toMatch(/PageUp.*PageDown/)
  unmount()
  const four = render(<Floor snapshot={snap()} nodes={twelve().slice(0, 4)} />)
  expect(stageOf(four.container).getAttribute('aria-label')).not.toMatch(/Page/)
})

test('jusqu\'à 4 nœuds : pas de sélecteur d\'étage, l\'étage 1 est le bureau', () => {
  for (const n of [0, 1, 4]) {
    const { container, unmount } = render(<Floor snapshot={snap()} nodes={twelve().slice(0, n)} />)
    expect(screen.queryByRole('button', { name: /^Monter d'un étage/ })).toBeNull()
    expect(container.querySelector('[data-floor-count]')!.getAttribute('data-floor-count')).toBe('1')
    expect(container.querySelectorAll('.desk')).toHaveLength(3)
    unmount()
  }
})

test('à 12 nœuds : ▲ ▼ nommés, « Étage 1 / 3 », ▼ désactivé en bas', () => {
  render(<Floor snapshot={snap()} nodes={twelve()} />)
  expect(pickLabel()).toBe('Étage 1 / 3')
  expect(up()).not.toHaveAttribute('aria-disabled'); expect(down()).toHaveAttribute('aria-disabled', 'true'); expect(down()).not.toBeDisabled()
  expect(document.querySelector('[data-floor-label]')!.getAttribute('aria-live')).toBe('polite')
})

test('▲ affiche l\'étage 2 : quatre baies, aucun poste ni table, la table reste dans son coin, légende des nœuds de l\'étage', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up())
  expect(pickLabel()).toBe('Étage 2 / 3')
  expect([...container.querySelectorAll('g.rack')].map((r) => r.getAttribute('data-node'))).toEqual(expect.arrayContaining(['n5', 'n6', 'n7', 'n8']))
  expect(container.querySelectorAll('g.rack')).toHaveLength(4)
  expect(container.querySelectorAll('.desk')).toHaveLength(0)
  expect(container.querySelectorAll('g.dais')).toHaveLength(0)
  expect(container.querySelectorAll('[data-label]')).toHaveLength(0)
  expect(screen.getByText('TA TABLE')).toBeInTheDocument() // a request does not vanish because we look at the racks
  expect([...container.querySelectorAll('[data-legend] li')].map((li) => li.textContent)).toEqual(['N5 · en ligne · gardien : Aether', 'N6 · en ligne · gardien : Aether', 'N7 · en ligne · gardien : Aether', 'N8 · en ligne · gardien : Aether'])
  expect(container.querySelector('[data-stage]')!.getAttribute('data-floor')).toBe('2')
  expect(screen.getByRole('img', { name: 'Étage 2 de Nexus : salle des serveurs, 4 baies' })).toBeInTheDocument()
})

test('la dernière salle peut être incomplète : 12 nœuds donnent 4, 10 nœuds donnent 2 baies à l\'étage 3', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve().slice(0, 10)} />)
  fireEvent.click(up()); fireEvent.click(up())
  expect(pickLabel()).toBe('Étage 3 / 3')
  expect(container.querySelectorAll('g.rack')).toHaveLength(2)
  expect(screen.getByRole('img', { name: 'Étage 3 de Nexus : salle des serveurs, 2 baies' })).toBeInTheDocument()
  expect(up()).toHaveAttribute('aria-disabled', 'true')
})

test('l\'ordre reçu fixe les étages : ni l\'id ni le statut ne déplacent un nœud', () => {
  const received = ['zeta', 'alpha', 'mid', 'omega', 'beta']
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={received.map((id) => node(id, 'online'))} />)
  expect([...container.querySelectorAll('g.rack')].map((r) => r.getAttribute('data-node'))).toEqual(['zeta', 'alpha', 'mid', 'omega'])
  rerender(<Floor snapshot={snap()} nodes={received.map((id) => node(id, id === 'zeta' ? 'offline' : 'unknown'))} />)
  expect([...container.querySelectorAll('g.rack')].map((r) => r.getAttribute('data-node'))).toEqual(['zeta', 'alpha', 'mid', 'omega'])
})

test('changer d\'étage garde l\'angle de la vue', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(screen.getByRole('button', { name: /vers la droite/ }))
  expect(stageOf(container).getAttribute('data-angle')).toBe('90')
  fireEvent.click(up())
  expect(stageOf(container).getAttribute('data-angle')).toBe('90')
  fireEvent.click(down())
  expect(stageOf(container).getAttribute('data-angle')).toBe('90')
})

test('data-floor-dir est absent au premier rendu, puis up, puis down', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  expect(stageOf(container).hasAttribute('data-floor-dir')).toBe(false)
  fireEvent.click(up())
  expect(stageOf(container).getAttribute('data-floor-dir')).toBe('up')
  fireEvent.click(down())
  expect(stageOf(container).getAttribute('data-floor-dir')).toBe('down')
})

test('PageUp et PageDown changent d\'étage sur la scène, les flèches tournent toujours', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  const stage = stageOf(container)
  expect(fireEvent.keyDown(stage, { key: 'PageUp' })).toBe(false) // preventDefault: the page does not scroll
  expect(stage.getAttribute('data-floor')).toBe('2')
  fireEvent.keyDown(stage, { key: 'PageUp' }); fireEvent.keyDown(stage, { key: 'PageUp' })
  expect(stage.getAttribute('data-floor')).toBe('3')
  fireEvent.keyDown(stage, { key: 'PageDown' })
  expect(stage.getAttribute('data-floor')).toBe('2')
  fireEvent.keyDown(stage, { key: 'ArrowRight' })
  expect(stage.getAttribute('data-angle')).toBe('90')
  expect(stage.getAttribute('data-floor')).toBe('2')
  expect(fireEvent.keyDown(stage, { key: 'PageUp', shiftKey: true })).toBe(true) // modifiers left to the browser
})

test('un nœud hors ligne à l\'étage 3 : pastille rouge sur ▲, texte dans le nom du bouton et dans l\'étiquette', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve({ n10: 'offline' })} />)
  expect(pip(container, 'up')!.getAttribute('data-alert')).toBe('off')
  expect(pip(container, 'down')).toBeNull()
  expect(up()).toHaveAccessibleName('Monter d\'un étage : un nœud hors ligne à l\'étage 3')
  expect(down()).toHaveAccessibleName('Descendre d\'un étage')
  expect(pickLabel()).toBe('Étage 1 / 3 · alerte : étage 3')
  expect(container.querySelector('[data-floor-marker]')).toBeNull() // the column of dots is gone
})

test('pastille sur ▼ pour un étage en dessous, la plus grave l\'emporte, aucune pour l\'étage affiché', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve({ cortex: 'unknown', n10: 'offline' })} />)
  expect(pip(container, 'up')!.getAttribute('data-alert')).toBe('off')
  fireEvent.click(up()); fireEvent.click(up()) // floor 3 holds the offline node: it is the floor shown
  expect(pip(container, 'up')).toBeNull()
  expect(pip(container, 'down')!.getAttribute('data-alert')).toBe('unknown')
  expect(down()).toHaveAccessibleName('Descendre d\'un étage : un nœud en état inconnu à l\'étage 1')
  expect(pickLabel()).toBe('Étage 3 / 3 · alerte : étage 1')
})

test('plusieurs étages en alerte : les deux textes, « alerte aux étages 1 et 3 »', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve({ n6: 'unknown', n10: 'offline' })} />)
  fireEvent.click(up())
  expect(pickLabel()).toBe('Étage 2 / 3 · alerte : étage 3') // the displayed floor 2 holds the unknown node
  fireEvent.click(down())
  expect(pickLabel()).toBe('Étage 1 / 3 · alerte : étages 2, 3')
  expect(up()).toHaveAccessibleName('Monter d\'un étage : un nœud en état inconnu à l\'étage 2, un nœud hors ligne à l\'étage 3')
  expect(pip(container, 'up')!.getAttribute('data-alert')).toBe('off')
})

test('un nœud inconnu, périmé ou une relecture en échec donne l\'ambre ; hors ligne prévu ne donne rien', () => {
  const old = new Date(Date.now() - 10 * 60_000).toISOString()
  const a = render(<Floor snapshot={snap()} nodes={twelve({ n6: 'unknown' })} />)
  expect(pip(a.container, 'up')!.getAttribute('data-alert')).toBe('unknown')
  a.unmount()
  const b = render(<Floor snapshot={snap()} nodes={twelve().map((n) => n.id === 'n11' ? { ...n, measured_at: old } : n)} />)
  expect(pip(b.container, 'up')!.getAttribute('data-alert')).toBe('unknown')
  b.unmount()
  const c = render(<Floor snapshot={snap()} nodes={twelve()} nodesFailed />)
  expect(pip(c.container, 'up')!.getAttribute('data-alert')).toBe('unknown') // amber everywhere: floors 2 and 3 are above
  expect(pickLabel()).toBe('Étage 1 / 3 · alerte : étages 2, 3')
  c.unmount()
  const d = render(<Floor snapshot={snap()} nodes={twelve({ artemis: 'offline-by-design' })} />)
  expect(pip(d.container, 'up')).toBeNull(); expect(pickLabel()).toBe('Étage 1 / 3')
  fireEvent.click(up()); fireEvent.click(down())
  expect(d.container.querySelector('[data-node="artemis"]')!.getAttribute('data-tone')).toBe('off') // its rack stays shown, off
})

test('moins de nœuds qu\'avant : l\'étage disparu laisse la place au dernier, sans erreur', () => {
  const { container, rerender } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up())
  rerender(<Floor snapshot={snap()} nodes={twelve().slice(0, 6)} />)
  expect(pickLabel()).toBe('Étage 2 / 2')
  expect(container.querySelectorAll('g.rack')).toHaveLength(2)
})

test('au dernier étage, ▲ garde le focus (aria-disabled, pas disabled) et PageDown fonctionne toujours', () => {
  const { container } = render(<Floor snapshot={snap()} nodes={twelve()} />)
  fireEvent.click(up()); fireEvent.click(up())
  up().focus()
  expect(up()).toHaveFocus()
  fireEvent.click(up()) // at the limit: ignored
  expect(up()).toHaveFocus()
  expect(stageOf(container).getAttribute('data-floor')).toBe('3')
  fireEvent.keyDown(stageOf(container), { key: 'PageUp' })
  expect(stageOf(container).getAttribute('data-floor')).toBe('3')
  fireEvent.keyDown(stageOf(container), { key: 'PageDown' })
  expect(stageOf(container).getAttribute('data-floor')).toBe('2')
})

test('plusieurs nœuds en alerte sur un étage : le nombre est dit, au pluriel', () => {
  const a = render(<Floor snapshot={snap()} nodes={twelve({ n9: 'offline', n10: 'offline', n11: 'unknown' })} />)
  expect(up()).toHaveAccessibleName('Monter d\'un étage : 2 nœuds hors ligne à l\'étage 3')
  a.unmount()
  const b = render(<Floor snapshot={snap()} nodes={twelve({ n6: 'unknown', n7: 'unknown', n8: 'unknown' })} />)
  expect(up()).toHaveAccessibleName('Monter d\'un étage : 3 nœuds en état inconnu à l\'étage 2')
  b.unmount()
  render(<Floor snapshot={snap()} nodes={twelve({ n9: 'offline' })} />)
  expect(up()).toHaveAccessibleName('Monter d\'un étage : un nœud hors ligne à l\'étage 3')
})

test('étiquette du sélecteur : largeur bornée, deux lignes d\'alerte au plus, texte complet pour les lecteurs d\'écran et en infobulle', () => {
  const many = Array.from({ length: 20 }, (_, i) => node(`s${i + 1}`, [5, 9, 13, 17].includes(i + 1) ? 'offline' : 'online')) // floors 2, 3, 4, 5 in alert
  render(<Floor snapshot={snap()} nodes={many} />)
  const label = document.querySelector('[data-floor-label]') as HTMLElement
  expect(label.className).toContain('w-[130px]'); expect(label.className).toContain('min-w-0')
  const alert = label.querySelector('[data-alert-line]') as HTMLElement
  expect(alert.className).toContain('line-clamp-2')
  expect(label.textContent).toBe('Étage 1 / 5 · alerte : étages 2, 3, 4, 5') // the full list, whatever is clipped on screen
  expect(label.getAttribute('title')).toBe('Étage 1 / 5 · alerte : étages 2, 3, 4, 5')
  expect(up()).toHaveAccessibleName('Monter d\'un étage : un nœud hors ligne à l\'étage 2, un nœud hors ligne à l\'étage 3, un nœud hors ligne à l\'étage 4, un nœud hors ligne à l\'étage 5')
})
