import { act, renderHook } from '@testing-library/react'
import type { KeyboardEvent, PointerEvent as ReactPointerEvent } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { resetFloorRotation, useFloorRotation } from './useFloorRotation'

const pointer = (clientX: number, over: Record<string, unknown> = {}) => ({
  clientX, pointerId: 1, button: 0, target: document.body, currentTarget: document.body, ...over,
}) as unknown as ReactPointerEvent<HTMLElement>
const key = (k: string, over: Record<string, unknown> = {}) => ({ key: k, preventDefault: vi.fn(), ...over }) as unknown as KeyboardEvent<HTMLElement>
const reducedMotion = (on: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({ matches: on && q.includes('reduce'), media: q }))

beforeEach(() => { resetFloorRotation(); vi.useFakeTimers(); reducedMotion(false) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

const drag = (r: { current: ReturnType<typeof useFloorRotation> }, from: number, to: number) => {
  act(() => r.current.stage.onPointerDown(pointer(from)))
  act(() => r.current.stage.onPointerMove(pointer(to)))
}

test('démarre à 0°, rien ne tourne tout seul', () => {
  const { result } = renderHook(() => useFloorRotation())
  expect(result.current.angle).toBe(0)
  act(() => { vi.advanceTimersByTime(5000) })
  expect(result.current.angle).toBe(0)
})

test('glisser suit le pointeur à 0,4° par pixel', () => {
  const { result } = renderHook(() => useFloorRotation())
  drag(result, 100, 200)
  expect(result.current.angle).toBeCloseTo(40)
  act(() => result.current.stage.onPointerMove(pointer(50)))
  expect(result.current.angle).toBeCloseTo(-20)
})

test('un mouvement sous le seuil n\'est pas un glisser', () => {
  const { result } = renderHook(() => useFloorRotation())
  drag(result, 100, 102)
  expect(result.current.angle).toBe(0)
  act(() => result.current.stage.onPointerUp(pointer(102)))
  const click = { preventDefault: vi.fn(), stopPropagation: vi.fn() }
  act(() => result.current.stage.onClickCapture(click as never))
  expect(click.preventDefault).not.toHaveBeenCalled()
})

test('au relâchement, l\'angle se cale en ~300 ms sur le quart de tour le plus proche', () => {
  const { result } = renderHook(() => useFloorRotation())
  drag(result, 0, 200) // 80°
  act(() => result.current.stage.onPointerUp(pointer(200)))
  expect(result.current.angle).toBeCloseTo(80) // l'animation n'a pas encore avancé
  act(() => { vi.advanceTimersByTime(150) })
  expect(result.current.angle).toBeGreaterThan(80); expect(result.current.angle).toBeLessThan(90)
  act(() => { vi.advanceTimersByTime(400) })
  expect(result.current.angle).toBe(90)
})

test('mouvement réduit : calage immédiat, sans animation', () => {
  reducedMotion(true)
  const { result } = renderHook(() => useFloorRotation())
  drag(result, 0, 200)
  act(() => result.current.stage.onPointerUp(pointer(200)))
  expect(result.current.angle).toBe(90)
})

test('le clic qui suit un glisser est avalé, pas le suivant', () => {
  const { result } = renderHook(() => useFloorRotation())
  drag(result, 0, 100)
  act(() => result.current.stage.onPointerUp(pointer(100)))
  const first = { preventDefault: vi.fn(), stopPropagation: vi.fn() }
  act(() => result.current.stage.onClickCapture(first as never))
  expect(first.preventDefault).toHaveBeenCalled(); expect(first.stopPropagation).toHaveBeenCalled()
  const second = { preventDefault: vi.fn(), stopPropagation: vi.fn() }
  act(() => result.current.stage.onClickCapture(second as never))
  expect(second.preventDefault).not.toHaveBeenCalled()
})

test('un clic qui n\'arrive jamais ne bloque pas le clic d\'un utilisateur au clavier', () => {
  const { result } = renderHook(() => useFloorRotation())
  drag(result, 0, 100)
  act(() => result.current.stage.onPointerUp(pointer(100)))
  act(() => { vi.advanceTimersByTime(50) })
  const click = { preventDefault: vi.fn(), stopPropagation: vi.fn() }
  act(() => result.current.stage.onClickCapture(click as never))
  expect(click.preventDefault).not.toHaveBeenCalled()
})

test('un glisser commencé sur un bouton ou avec un autre bouton de souris est ignoré', () => {
  const { result } = renderHook(() => useFloorRotation())
  const btn = document.createElement('button')
  act(() => result.current.stage.onPointerDown(pointer(0, { target: btn })))
  act(() => result.current.stage.onPointerMove(pointer(200)))
  expect(result.current.angle).toBe(0)
  act(() => result.current.stage.onPointerDown(pointer(0, { button: 2 })))
  act(() => result.current.stage.onPointerMove(pointer(200)))
  expect(result.current.angle).toBe(0)
})

test('annuler le pointeur cale aussi', () => {
  reducedMotion(true)
  const { result } = renderHook(() => useFloorRotation())
  drag(result, 0, 150) // 60°
  act(() => result.current.stage.onPointerCancel(pointer(150)))
  expect(result.current.angle).toBe(90)
})

test('flèches : ± 90°, animés ; les autres touches et les combinaisons sont ignorées', () => {
  const { result } = renderHook(() => useFloorRotation())
  const right = key('ArrowRight')
  act(() => result.current.stage.onKeyDown(right))
  expect(right.preventDefault).toHaveBeenCalled()
  act(() => { vi.advanceTimersByTime(500) })
  expect(result.current.angle).toBe(90)
  act(() => result.current.stage.onKeyDown(key('ArrowLeft')))
  act(() => { vi.advanceTimersByTime(500) })
  expect(result.current.angle).toBe(0)
  const other = key('a'), meta = key('ArrowRight', { metaKey: true })
  act(() => { result.current.stage.onKeyDown(other); result.current.stage.onKeyDown(meta) })
  act(() => { vi.advanceTimersByTime(500) })
  expect(result.current.angle).toBe(0)
  expect(other.preventDefault).not.toHaveBeenCalled(); expect(meta.preventDefault).not.toHaveBeenCalled()
})

test('des appuis rapprochés s\'additionnent sans perdre un quart de tour', () => {
  const { result } = renderHook(() => useFloorRotation())
  act(() => { result.current.rotateBy(90); vi.advanceTimersByTime(100); result.current.rotateBy(90) })
  act(() => { vi.advanceTimersByTime(600) })
  expect(result.current.angle).toBe(180)
})

test('l\'angle est gardé pendant la session de la page, pas dans le stockage du navigateur', () => {
  const first = renderHook(() => useFloorRotation())
  act(() => first.result.current.rotateBy(90))
  act(() => { vi.advanceTimersByTime(500) })
  first.unmount()
  const second = renderHook(() => useFloorRotation())
  expect(second.result.current.angle).toBe(90)
  expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0)
})

test('démonter en pleine animation ne laisse aucun rappel', () => {
  const { result, unmount } = renderHook(() => useFloorRotation())
  act(() => result.current.rotateBy(90))
  unmount()
  expect(() => act(() => { vi.advanceTimersByTime(500) })).not.toThrow()
})

test('un simple clic pendant l\'animation ne fige pas l\'étage à un angle intermédiaire', () => {
  const { result } = renderHook(() => useFloorRotation())
  act(() => result.current.rotateBy(90))
  act(() => { vi.advanceTimersByTime(100) })
  act(() => result.current.stage.onPointerDown(pointer(50)))
  act(() => result.current.stage.onPointerUp(pointer(50)))
  act(() => { vi.advanceTimersByTime(600) })
  expect(result.current.angle).toBe(90)
})

test('un second pointeur qui se pose et se lève ne fait pas perdre le calage du premier', () => {
  const { result } = renderHook(() => useFloorRotation())
  act(() => result.current.stage.onPointerDown(pointer(0, { pointerId: 1 })))
  act(() => result.current.stage.onPointerMove(pointer(100, { pointerId: 1 }))) // 40°
  act(() => result.current.stage.onPointerDown(pointer(300, { pointerId: 2 })))
  act(() => result.current.stage.onPointerUp(pointer(300, { pointerId: 2 })))
  act(() => result.current.stage.onPointerUp(pointer(100, { pointerId: 1 })))
  act(() => { vi.advanceTimersByTime(600) })
  expect(result.current.angle % 90).toBe(0)
})
