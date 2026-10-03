import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ARRIVE_MS, LEVEL_MS, resetFloorLevel, useFloorLevel } from './useFloorLevel'

const reducedMotion = (on: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({ matches: on && q.includes('reduce'), media: q }))

beforeEach(() => { resetFloorLevel(); vi.useFakeTimers(); reducedMotion(false) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

const setup = (count: number, loaded = true) => renderHook((p: { count: number; loaded: boolean }) => useFloorLevel(p.count, { loaded: p.loaded }), { initialProps: { count, loaded } })

test('démarre à l\'étage 1, sans direction ni couche qui part', () => {
  const { result } = setup(3)
  expect(result.current).toMatchObject({ floor: 1, count: 3, dir: undefined })
  expect(result.current.layers).toEqual([{ floor: 1, role: 'current', from: 'above' }])
})

test('go est borné à [1, count]', () => {
  const { result } = setup(3)
  act(() => result.current.go(-1))
  expect(result.current.floor).toBe(1)
  act(() => result.current.go(1)); act(() => result.current.go(1)); act(() => result.current.go(1))
  expect(result.current.floor).toBe(3)
})

test('deux go(+1) rapides dans le même rendu donnent l\'étage 3 : on part de la cible', () => {
  const { result } = setup(3)
  act(() => { result.current.go(1); result.current.go(1) })
  expect(result.current.floor).toBe(3)
})

test('dir suit le dernier mouvement', () => {
  const { result } = setup(3)
  act(() => result.current.go(1))
  expect(result.current.dir).toBe('up')
  act(() => result.current.go(-1))
  expect(result.current.dir).toBe('down')
})

test('l\'étage demandé est gardé au remontage, pour la session de la page', () => {
  const first = setup(3)
  act(() => first.result.current.go(1)); act(() => first.result.current.go(1))
  first.unmount()
  const again = setup(3)
  expect(again.result.current.floor).toBe(3)
  expect(again.result.current.dir).toBeUndefined()
  expect(again.result.current.layers).toHaveLength(1)
})

test('moins d\'étages : repli instantané sur le dernier, sans couche ni direction, mémorisé seulement une fois lu', () => {
  const first = setup(3)
  act(() => { first.result.current.go(1); first.result.current.go(1) })
  act(() => { vi.advanceTimersByTime(LEVEL_MS + 100) })
  first.rerender({ count: 2, loaded: true })
  expect(first.result.current.floor).toBe(2)
  expect(first.result.current.layers).toEqual([{ floor: 2, role: 'current', from: 'above' }])
  first.unmount()
  expect(setup(3).result.current.floor).toBe(2) // la repli a été écrit : l'étage 3 n'est pas ressuscité
})

test('pendant une lecture en cours (loaded faux), le repli n\'efface pas l\'étage demandé', () => {
  const first = setup(3)
  act(() => { first.result.current.go(1); first.result.current.go(1) })
  first.unmount()
  const during = setup(1, false) // nodes pas encore lus : un seul étage affiché
  expect(during.result.current.floor).toBe(1)
  during.unmount()
  expect(setup(3).result.current.floor).toBe(3)
})

test('l\'étage qui part reste monté LEVEL_MS + 50 ms puis disparaît', () => {
  const { result } = setup(3)
  act(() => result.current.go(1))
  expect(result.current.layers).toEqual([{ floor: 1, role: 'leaving', from: 'above' }, { floor: 2, role: 'current', from: 'above' }])
  act(() => { vi.advanceTimersByTime(LEVEL_MS + 49) })
  expect(result.current.layers).toHaveLength(2)
  act(() => { vi.advanceTimersByTime(1) })
  expect(result.current.layers).toEqual([{ floor: 2, role: 'current', from: 'above' }])
})

test('en descendant, la couche qui arrive vient d\'en dessous', () => {
  const { result } = setup(3)
  act(() => { result.current.go(1); result.current.go(1) })
  act(() => { vi.advanceTimersByTime(LEVEL_MS + 100) })
  act(() => result.current.go(-1))
  expect(result.current.layers.at(-1)).toEqual({ floor: 2, role: 'current', from: 'below' })
  expect(result.current.layers[0]).toMatchObject({ floor: 3, role: 'leaving' })
})

test('un retour pendant l\'animation reprend la couche au lieu de la dupliquer', () => {
  const { result } = setup(3)
  act(() => result.current.go(1))
  act(() => result.current.go(-1))
  const floors = result.current.layers.map((l) => l.floor)
  expect(new Set(floors).size).toBe(floors.length)
  expect(result.current.layers.filter((l) => l.role === 'current').map((l) => l.floor)).toEqual([1])
})

test('mouvement réduit : jamais de couche qui part', () => {
  reducedMotion(true)
  const { result } = setup(3)
  act(() => result.current.go(1))
  expect(result.current.floor).toBe(2)
  expect(result.current.layers).toEqual([{ floor: 2, role: 'current', from: 'above' }])
})

test('les minuteurs sont nettoyés au démontage', () => {
  const { result, unmount } = setup(3)
  act(() => result.current.go(1))
  unmount()
  expect(vi.getTimerCount()).toBe(0)
})

test('arriving : seulement après un mouvement vers une salle, retiré après la cascade', () => {
  const { result } = setup(3)
  expect(result.current.arriving).toBeUndefined()
  expect(result.current.lifted).toBeUndefined()
  act(() => result.current.go(1))
  expect(result.current.arriving).toBe(2)
  expect(result.current.lifted).toBe(2)
  act(() => { vi.advanceTimersByTime(ARRIVE_MS - 1) })
  expect(result.current.arriving).toBe(2)
  act(() => { vi.advanceTimersByTime(1) })
  expect(result.current.arriving).toBeUndefined()
  expect(result.current.lifted).toBe(2) // the lift itself stays the last move
  act(() => result.current.go(-1)) // back to the office: no racks to cascade
  expect(result.current.arriving).toBeUndefined()
  expect(result.current.lifted).toBe(1)
})

test('arriving : ni au remontage, ni au repli, ni sous mouvement réduit', () => {
  const first = setup(3)
  act(() => { first.result.current.go(1); first.result.current.go(1) })
  act(() => { vi.advanceTimersByTime(ARRIVE_MS) })
  first.unmount()
  const again = setup(3)
  expect(again.result.current).toMatchObject({ arriving: undefined, lifted: undefined })
  again.rerender({ count: 2, loaded: true })
  expect(again.result.current).toMatchObject({ floor: 2, arriving: undefined, lifted: undefined })
  again.unmount()
  reducedMotion(true)
  const calm = setup(3)
  act(() => calm.result.current.go(1))
  expect(calm.result.current.arriving).toBeUndefined()
})
