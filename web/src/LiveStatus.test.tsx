import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { LiveStatus } from './LiveStatus'

test.each([
  [{ status: 'connected' } as const, 'Temps réel : connecté'],
  [{ status: 'connecting' } as const, 'Temps réel : connexion…'],
  [{ status: 'reconnecting', attempt: 3 } as const, 'Temps réel : reconnexion… (essai 3)'],
  [{ status: 'unknown', attempt: 5 } as const, 'Temps réel : unknown — relecture toutes les 10 s'],
])('affiche l’état %o', (state, text) => {
  render(<LiveStatus state={state} />)
  expect(screen.getByText(text)).toBeInTheDocument()
})

test('unknown est mis en évidence', () => {
  render(<LiveStatus state={{ status: 'unknown', attempt: 1 }} />)
  expect(screen.getByText(/unknown/)).toHaveClass('text-attention')
})
