import clsx from 'clsx'
import { REFRESH_MS } from './freshness'
import type { LiveState } from './live'

function describe(state: LiveState): string {
  switch (state.status) {
    case 'connected':
      return 'Temps réel : connecté'
    case 'connecting':
      return 'Temps réel : connexion…'
    case 'reconnecting':
      return `Temps réel : reconnexion… (essai ${state.attempt})`
    case 'unknown':
      return `Temps réel : unknown — relecture toutes les ${REFRESH_MS.tasks / 1000} s`
  }
}

/** État du temps réel dans la barre du bas ; aucune animation, seul l'état change le texte. */
export function LiveStatus({ state }: { state: LiveState }) {
  return (
    <span className={clsx('shrink-0', state.status === 'unknown' ? 'text-attention' : 'text-muted')}>
      {describe(state)}
    </span>
  )
}
