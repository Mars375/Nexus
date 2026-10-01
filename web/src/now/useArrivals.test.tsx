import { act, render, screen } from '@testing-library/react'
import { createRoot } from 'react-dom/client'
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

test('une arrivée n\'est jamais peinte une image sans son état « nouveau »', async () => {
  vi.useRealTimers()
  const g = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
  const prev = g.IS_REACT_ACT_ENVIRONMENT
  g.IS_REACT_ACT_ENVIRONMENT = false
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  function Both({ keys }: { keys: string[] }) { const fresh = useArrivals(keys, 1000); return <p>{keys.join(',')}|{[...fresh].join(',')}</p> }
  const painted: string[] = []
  new MutationObserver(() => painted.push(host.textContent ?? '')).observe(host, { childList: true, subtree: true, characterData: true })
  root.render(<Both keys={['a']} />)
  await new Promise((r) => setTimeout(r, 30))
  painted.length = 0
  root.render(<Both keys={['a', 'b']} />)
  await new Promise((r) => setTimeout(r, 30))
  expect(painted[0]).toBe('a,b|b')
  root.unmount()
  host.remove()
  g.IS_REACT_ACT_ENVIRONMENT = prev
})
