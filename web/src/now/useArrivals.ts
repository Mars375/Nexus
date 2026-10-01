import { useEffect, useRef, useState } from 'react'

export const ARRIVAL_HOLD_MS = 1800

/**
 * Clés apparues depuis le rendu précédent, gardées `holdMs` le temps de leur animation.
 * Rien n'est « nouveau » au premier rendu : on n'anime que de vrais changements (#6).
 */
export function useArrivals(keys: readonly string[], holdMs = ARRIVAL_HOLD_MS): ReadonlySet<string> {
  const seen = useRef<Set<string> | null>(null)
  const timers = useRef<number[]>([])
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set())
  const signature = keys.join('\u0000')

  useEffect(() => {
    const current = new Set(signature ? signature.split('\u0000') : [])
    const before = seen.current
    seen.current = current
    if (!before) return
    const added = [...current].filter((k) => !before.has(k))
    if (added.length === 0) return
    setFresh((f) => new Set([...f, ...added]))
    timers.current.push(window.setTimeout(() => {
      setFresh((f) => { const next = new Set(f); for (const k of added) next.delete(k); return next })
    }, holdMs))
  }, [signature, holdMs])

  useEffect(() => () => { for (const t of timers.current) window.clearTimeout(t) }, [])
  return fresh
}
