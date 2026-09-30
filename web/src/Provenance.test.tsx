import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { Provenance } from './Provenance'

const T0 = Date.parse('2026-09-29T10:00:00+02:00')

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(T0)
})
afterEach(() => vi.useRealTimers())

test('affiche la source et l\'âge, sans mention périmée tant que la donnée est fraîche', () => {
  render(<Provenance source="nexus.db" measuredAt={new Date(T0 - 5_000).toISOString()} kind="tasks" />)
  expect(screen.getByText(/^source : nexus\.db · mesuré il y a 5 s/)).toBeInTheDocument()
  expect(screen.queryByText('périmée')).not.toBeInTheDocument()
})

test('passe à « périmée » quand l\'horloge dépasse 3 × la cadence, sans nouvelle lecture', () => {
  render(<Provenance source="nexus.db" measuredAt={new Date(T0 - 29_000).toISOString()} kind="tasks" />)
  expect(screen.queryByText('périmée')).not.toBeInTheDocument()
  act(() => vi.advanceTimersByTime(2_000))
  expect(screen.getByText('périmée')).toBeInTheDocument()
})

test('une date illisible est dite illisible et périmée', () => {
  render(<Provenance source="nexus.db" measuredAt="pas une date" kind="tasks" />)
  expect(screen.getByText(/date de mesure illisible/)).toBeInTheDocument()
  expect(screen.getByText('périmée')).toBeInTheDocument()
})

test('le lien « ouvrir » n\'apparaît que pour une adresse https', () => {
  const { rerender } = render(
    <Provenance source="telegram" measuredAt={new Date(T0).toISOString()} kind="tasks" url="https://t.me/c/1/2" />,
  )
  const link = screen.getByRole('link', { name: 'ouvrir' })
  expect(link).toHaveAttribute('href', 'https://t.me/c/1/2')
  expect(link).toHaveAttribute('rel', 'noreferrer')
  rerender(<Provenance source="telegram" measuredAt={new Date(T0).toISOString()} kind="tasks" url="javascript:alert(1)" />)
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})
