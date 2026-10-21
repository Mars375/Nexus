/*
 * Shared fixtures and DOM helpers for the Now floor tests: keeps each test
 * file focused on behavior instead of repeating snapshot and pointer setup.
 */
import { afterEach, beforeEach, vi } from 'vitest'
import { screen } from '@testing-library/react'
import type { NodeState, NowSnapshot } from '@/api'
import { resetFloorRotation } from './useFloorRotation'
import { resetFloorLevel } from './useFloorLevel'

export const snap = (over: Partial<NowSnapshot> = {}): NowSnapshot => ({
  source: 'nexus.db', measured_at: new Date().toISOString(), operation: null, auxiliaries: [],
  agents: [
    { agent: 'helios', state: 'run', task: 'nx-task-31', title: 'Refonte du pont', run: 's', since: new Date(Date.now() - 42 * 60_000).toISOString() },
    { agent: 'mnema', state: 'idle', task: null, title: null, run: null, since: null },
    { agent: 'artemis', state: 'idle', task: null, title: null, run: null, since: null },
  ],
  asks: [], blocks: [], done: [], ...over,
})
export const node = (id: string, status: NodeState['status']): NodeState => ({ id, kind: 'homelab', guardian_agent: 'aether', status, last_seen: null, detail: null, source: 'tailscale', measured_at: new Date().toISOString() })

class TestPointerEvent extends MouseEvent {
  pointerId: number
  constructor(type: string, init: PointerEventInit = {}) { super(type, init); this.pointerId = init.pointerId ?? 1 }
}
export const stageOf = (c: HTMLElement) => c.querySelector('[data-stage]') as HTMLElement
export const screens = (c: HTMLElement) => c.querySelectorAll('.desk .screen').length

export const setupFloorTest = () => {
  beforeEach(() => { resetFloorRotation(); resetFloorLevel(); vi.stubGlobal('PointerEvent', TestPointerEvent); vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q })) })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
}

export const twelve = (over: Record<string, NodeState['status']> = {}) => ['cortex', 'synapse', 'artemis', 'helios', 'n5', 'n6', 'n7', 'n8', 'n9', 'n10', 'n11', 'n12'].map((id) => node(id, over[id] ?? 'online'))
export const pickLabel = () => document.querySelector('[data-floor-label]')?.textContent
export const up = () => screen.getByRole('button', { name: /^Monter d'un étage/ })
export const down = () => screen.getByRole('button', { name: /^Descendre d'un étage/ })
export const pip = (c: HTMLElement, side: 'up' | 'down') => c.querySelector(`.floor-pip[data-side="${side}"]`)
