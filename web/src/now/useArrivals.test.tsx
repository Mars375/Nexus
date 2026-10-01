import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { useArrivals } from './useArrivals'

function Probe({ keys }: { keys: string[] }) {
  const fresh = useArrivals(keys, 1000)
  return <p>{[...fresh].sort().join(',') || 'aucune'}</p>
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

test('rien n\'est nouveau au premier rendu', () => {
  render(<Probe keys={['a', 'b']} />)
  expect(screen.getByText('aucune')).toBeInTheDocument()
})

test('une clé qui apparaît est nouvelle, puis ne l\'est plus après le délai', () => {
  const { rerender } = render(<Probe keys={['a']} />)
  rerender(<Probe keys={['a', 'b']} />)
  expect(screen.getByText('b')).toBeInTheDocument()
  act(() => vi.advanceTimersByTime(999))
  expect(screen.getByText('b')).toBeInTheDocument()
  act(() => vi.advanceTimersByTime(1))
  expect(screen.getByText('aucune')).toBeInTheDocument()
})

test('un nouveau rendu sans changement ne relance rien', () => {
  const { rerender } = render(<Probe keys={['a']} />)
  rerender(<Probe keys={['a']} />)
  expect(screen.getByText('aucune')).toBeInTheDocument()
})

test('une deuxième arrivée ne coupe pas la première avant son délai', () => {
  const { rerender } = render(<Probe keys={[]} />)
  rerender(<Probe keys={['a']} />)
  act(() => vi.advanceTimersByTime(600))
  rerender(<Probe keys={['a', 'b']} />)
  expect(screen.getByText('a,b')).toBeInTheDocument()
  act(() => vi.advanceTimersByTime(400))
  expect(screen.getByText('b')).toBeInTheDocument()
})
