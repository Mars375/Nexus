import { expect, test } from 'vitest'
import type { NodeState, NowSnapshot } from '@/api'
import { rackLabel, rackTone, seatModels } from './model'

const base: NowSnapshot = {
  source: 'nexus.db', measured_at: '2026-10-01T10:00:00+02:00', operation: null, auxiliaries: [],
  agents: [
    { agent: 'helios', state: 'run', task: 'nx-task-31', title: 'Refonte du pont', run: 'session:a', since: '2026-10-01T09:18:00+02:00' },
    { agent: 'mnema', state: 'idle', task: null, title: null, run: null, since: null },
    { agent: 'artemis', state: 'idle', task: null, title: null, run: null, since: null },
  ],
  asks: [
    { event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: 'nx-task-32', at: '2026-10-01T09:59:00+02:00', received_at: '2026-10-01T09:59:00+02:00' },
    { event: 'nx-evt-2', agent: 'mnema', kind: 'question', subject: 'Et aussi ?', task: null, at: '2026-10-01T09:59:30+02:00', received_at: '2026-10-01T09:59:30+02:00' },
  ],
  blocks: [{ task: 'nx-task-29', title: 'Sauvegarde', cause: 'hors ligne', since: '2026-09-29T10:00:00+02:00', follow_up_at: null, lead_agent: 'artemis' }],
  done: [],
}

test('un poste reflète run, demandes et blocage de son agent', () => {
  const [helios, mnema, artemis] = seatModels(base)
  expect(helios).toMatchObject({ agent: 'helios', run: true, wait: false, block: false, task: 'nx-task-31', asks: 0 })
  expect(mnema).toMatchObject({ run: false, wait: true, block: false, asks: 2 })
  expect(artemis).toMatchObject({ run: false, wait: false, block: true })
})

test('état des baies : jamais vert sans preuve', () => {
  const node = (status: NodeState['status']): NodeState => ({ id: 'synapse', kind: 'homelab', guardian_agent: 'aether', status, last_seen: null, detail: null, source: 'tailscale', measured_at: '2026-10-01T10:00:00+02:00' })
  expect(rackTone(node('online'))).toBe('ok')
  expect(rackTone(node('unknown'))).toBe('unknown')
  expect(rackTone(node('offline'))).toBe('off')
  expect(rackTone(node('offline-by-design'))).toBe('off')
  expect(rackLabel(node('offline-by-design'))).toBe('hors ligne, prévu')
  expect(rackLabel(node('unknown'))).toBe('unknown')
})
