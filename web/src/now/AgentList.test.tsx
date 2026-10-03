import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { NowSnapshot } from '@/api'
import { AgentList } from './AgentList'

const snap: NowSnapshot = {
  source: 'nexus.db', measured_at: new Date().toISOString(), operation: null, auxiliaries: [],
  agents: [{ agent: 'helios', state: 'run', task: 'nx-task-1', title: 'Pont', run: 's', since: new Date().toISOString() }],
  asks: [], blocks: [], done: [],
}
const media = (matches: boolean) => vi.stubGlobal('matchMedia', (query: string) => ({ matches, media: query, addEventListener() {}, removeEventListener() {} }))

afterEach(() => vi.unstubAllGlobals())

test('au-dessus de 760 px la liste n\'est que pour les lecteurs d\'écran : ses liens ne prennent pas le focus clavier', () => {
  media(true)
  render(<AgentList snapshot={snap} className="min-[760px]:sr-only" />)
  expect(screen.getByRole('link', { name: 'Pont' })).toHaveAttribute('tabindex', '-1')
})

test('sous 760 px la liste est l\'étage : ses liens se tabulent', () => {
  media(false)
  render(<AgentList snapshot={snap} className="min-[760px]:sr-only" />)
  expect(screen.getByRole('link', { name: 'Pont' })).not.toHaveAttribute('tabindex')
})
