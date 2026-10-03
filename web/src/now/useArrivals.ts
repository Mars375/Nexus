import { useEffect, useLayoutEffect, useRef, useState } from 'react'

export const ARRIVAL_HOLD_MS = 1800

/**
 * Clés apparues depuis le rendu précédent, gardées `holdMs` le temps de leur animation.
 * Rien n'est « nouveau » au premier rendu : on n'anime que de vrais changements (#6).
 * `null` = pas encore chargé : on ne retient rien, pour que le premier vrai lot ne passe pas
 * pour une arrivée.
 */
export function useArrivals(keys: readonly string[] | null, holdMs = ARRIVAL_HOLD_MS): ReadonlySet<string> {
  const seen = useRef<Set<string> | null>(null)
  const timers = useRef<number[]>([])
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set())
  const signature = keys === null ? null : keys.join('\u0000')

  // Avant la peinture : une arrivée ne passe jamais une image à pleine opacité avant son fondu.
  useLayoutEffect(() => {
    if (signature === null) return
    const current = new Set(signature ? signature.split('\u0000') : [])
    const before = seen.current
    seen.current = current
    if (!before) return
    const added = [...current].filter((k) => !before.has(k))
    if (added.length === 0) return
    setFresh((f) => new Set([...f, ...added]))
    // Un minuteur écoulé quitte la liste : elle ne grandit pas sur un onglet ouvert des jours.
    const id = window.setTimeout(() => {
      timers.current = timers.current.filter((t) => t !== id)
      setFresh((f) => { const next = new Set(f); for (const k of added) next.delete(k); return next })
    }, holdMs)
    timers.current.push(id)
  }, [signature, holdMs])

  useEffect(() => () => { for (const t of timers.current) window.clearTimeout(t) }, [])
  return fresh
}
