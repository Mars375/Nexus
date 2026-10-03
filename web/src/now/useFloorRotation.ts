import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from 'react'
import { nearestQuarter } from './iso'

const DEGREES_PER_PX = 0.4
const DRAG_THRESHOLD_PX = 4
const SETTLE_MS = 300

// Settled angle, kept for the page session only: no browser storage (ADR-017), nothing turns on its own.
let remembered = 0

/** Test helper: forget the angle kept for the session. */
export function resetFloorRotation(): void {
  remembered = 0
}

const prefersReducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
const easeOut = (k: number) => 1 - (1 - k) ** 3

export type FloorStage = {
  onPointerDown: (e: PointerEvent<HTMLElement>) => void
  onPointerMove: (e: PointerEvent<HTMLElement>) => void
  onPointerUp: (e: PointerEvent<HTMLElement>) => void
  onPointerCancel: (e: PointerEvent<HTMLElement>) => void
  onClickCapture: (e: MouseEvent<HTMLElement>) => void
  onKeyDown: (e: KeyboardEvent<HTMLElement>) => void
}

/** Angle of the floor with drag, keyboard and button rotation that always settles on a quarter turn. */
export function useFloorRotation(): { angle: number; rotateBy: (delta: number) => void; stage: FloorStage } {
  const [angle, setAngle] = useState(remembered)
  const current = useRef(remembered)
  const frame = useRef(0)
  const drag = useRef<{ id: number; startX: number; startAngle: number; active: boolean } | null>(null)
  const swallowClick = useRef(false)
  const clearSwallow = useRef(0)

  const apply = useCallback((a: number) => { current.current = a; setAngle(a) }, [])
  const stopAnimation = useCallback(() => { cancelAnimationFrame(frame.current); frame.current = 0 }, [])
  useEffect(() => () => { stopAnimation(); clearTimeout(clearSwallow.current) }, [stopAnimation])

  const settle = useCallback((target: number) => {
    stopAnimation()
    remembered = target
    if (prefersReducedMotion() || target === current.current) { apply(target); return }
    const from = current.current, start = performance.now()
    const step = (now: number) => {
      const k = Math.min(1, Math.max(0, (now - start) / SETTLE_MS))
      apply(k === 1 ? target : from + (target - from) * easeOut(k))
      if (k < 1) frame.current = requestAnimationFrame(step)
    }
    frame.current = requestAnimationFrame(step)
  }, [apply, stopAnimation])

  // Relative to the last settled angle, so quick presses add up instead of racing the animation.
  const rotateBy = useCallback((delta: number) => settle(remembered + delta), [settle])

  const finish = useCallback((e: PointerEvent<HTMLElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    drag.current = null
    if (!d.active) return
    try { e.currentTarget.releasePointerCapture?.(d.id) } catch { /* capture already gone */ }
    swallowClick.current = true
    clearTimeout(clearSwallow.current)
    clearSwallow.current = window.setTimeout(() => { swallowClick.current = false }, 0)
    settle(nearestQuarter(current.current))
  }, [settle])

  const stage: FloorStage = {
    onPointerDown: (e) => {
      if (e.button !== 0 || (e.target as Element).closest?.('button')) return
      // A second pointer never takes over a gesture already under way, even before it becomes a drag.
      // The same pointer may restart one (a mouse released outside the stage before the threshold).
      if (drag.current && drag.current.id !== e.pointerId) return
      swallowClick.current = false
      // The animation keeps running until the gesture really is a drag: a plain click must not freeze it mid-way.
      drag.current = { id: e.pointerId, startX: e.clientX, startAngle: current.current, active: false }
    },
    onPointerMove: (e) => {
      const d = drag.current
      if (!d || d.id !== e.pointerId) return
      const dx = e.clientX - d.startX
      if (!d.active) {
        if (Math.abs(dx) < DRAG_THRESHOLD_PX) return
        d.active = true
        stopAnimation()
        d.startAngle = current.current
        // Capture only once it is a drag, so a plain click still reaches the label under the pointer.
        try { e.currentTarget.setPointerCapture?.(d.id) } catch { /* pointer already released */ }
      }
      apply(d.startAngle + dx * DEGREES_PER_PX)
    },
    onPointerUp: finish,
    onPointerCancel: finish,
    onClickCapture: (e) => {
      if (!swallowClick.current) return
      swallowClick.current = false
      e.preventDefault(); e.stopPropagation()
    },
    onKeyDown: (e) => {
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
      e.preventDefault()
      rotateBy(e.key === 'ArrowRight' ? 90 : -90)
    },
  }
  return { angle, rotateBy, stage }
}
