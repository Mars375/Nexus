import { useCallback, useEffect, useRef, useState } from 'react'

/** Duration of the lift transition (floor.css); a leaving floor stays mounted a little longer than that. */
export const LEVEL_MS = 350
const UNMOUNT_GRACE_MS = 50

// Floor asked for, kept for the page session only: no browser storage (ADR-017), nothing moves on its own.
let requested = 1

/** Test helper: forget the floor kept for the session. */
export function resetFloorLevel(): void {
  requested = 1
}

const prefersReducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

/**
 * One mounted floor. `from` is the side the last move came from (`above` when going up), for the
 * floor arriving and for the one leaving alike: the CSS slides them in opposite directions from it.
 */
export type FloorLayer = { floor: number; role: 'current' | 'leaving'; from: 'above' | 'below' }
type Leaving = { id: number; floor: number; from: FloorLayer['from'] }

export type FloorLevel = {
  floor: number
  count: number
  /** Moves `delta` floors from the floor asked for last (not the one still on screen), within [1, count]. */
  go: (delta: number) => void
  /** Direction of the last move; absent until the first one. */
  dir: 'up' | 'down' | undefined
  /** The floor shown, preceded by the floors still leaving (never any under reduced motion). */
  layers: FloorLayer[]
}

/** Which of `count` floors is shown, with the layers the lift animation needs mounted. */
export function useFloorLevel(count: number, { loaded }: { loaded: boolean }): FloorLevel {
  const [target, setTarget] = useState(requested)
  const [motion, setMotion] = useState<{ dir: 'up' | 'down' | undefined; from: FloorLayer['from']; leaving: Leaving[] }>({ dir: undefined, from: 'above', leaving: [] })
  const asked = useRef(target)
  const countRef = useRef(count)
  const shown = useRef(Math.min(target, count))
  const nextId = useRef(0)
  const timers = useRef<number[]>([])
  const floor = Math.min(target, count)

  // A floor that no longer exists: fall back at once (not an action, so no lift)...
  if (loaded && target > count) setTarget(count)
  useEffect(() => { countRef.current = count; shown.current = floor })
  useEffect(() => () => { for (const t of timers.current) window.clearTimeout(t) }, [])
  // ...and remember it only once the nodes were really read, so a read still in flight on remount does not erase floor 3.
  useEffect(() => {
    if (!loaded) return
    asked.current = floor
    requested = floor
  }, [loaded, floor])

  const go = useCallback((delta: number) => {
    const base = Math.min(asked.current, countRef.current)
    const next = Math.min(Math.max(base + delta, 1), countRef.current)
    if (next === base) return
    asked.current = next
    requested = next
    setTarget(next)
    const dir = next > base ? 'up' : 'down', from = dir === 'up' ? 'above' : 'below'
    if (prefersReducedMotion()) { setMotion({ dir, from, leaving: [] }); return }
    // A floor never shown (a second quick press) has nothing to slide out; one coming back stops leaving.
    const leaves = base === shown.current
    const id = nextId.current++
    setMotion((m) => ({ dir, from, leaving: [...m.leaving.filter((l) => l.floor !== next && l.floor !== base), ...(leaves ? [{ id, floor: base, from } as Leaving] : [])] }))
    if (leaves) {
      const t = window.setTimeout(() => {
        timers.current = timers.current.filter((x) => x !== t)
        setMotion((m) => ({ ...m, leaving: m.leaving.filter((l) => l.id !== id) }))
      }, LEVEL_MS + UNMOUNT_GRACE_MS)
      timers.current.push(t)
    }
  }, [])

  const layers: FloorLayer[] = [
    ...motion.leaving.filter((l) => l.floor !== floor).map((l): FloorLayer => ({ floor: l.floor, role: 'leaving', from: l.from })),
    { floor, role: 'current', from: motion.from },
  ]
  return { floor, count, go, dir: motion.dir, layers }
}
