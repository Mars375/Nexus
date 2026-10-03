import { expect, test } from 'vitest'
import type { NodeState, NowSnapshot } from '@/api'
import { RACKS_PER_FLOOR, floorAlert, floorAlertSides, nodeFloors, rackLabel, rackTone, seatModels } from './model'

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

const nodeOf = (id: string, status: NodeState['status'] = 'online'): NodeState => ({ id, kind: 'homelab', guardian_agent: 'aether', status, last_seen: null, detail: null, source: 'tailscale', measured_at: '2026-10-01T10:00:00+02:00' })
const many = (n: number) => Array.from({ length: n }, (_, i) => nodeOf(`n${i + 1}`))

test('étages : paquets de 4 dans l\'ordre reçu, au moins un étage', () => {
  expect(RACKS_PER_FLOOR).toBe(4)
  expect([0, 1, 4, 5, 8, 9, 12].map((n) => nodeFloors(many(n)).length)).toEqual([1, 1, 1, 2, 2, 3, 3])
  expect(nodeFloors(many(0))).toEqual([[]])
  expect(nodeFloors(undefined)).toEqual([[]])
  for (const f of nodeFloors(many(9))) expect(f.length).toBeLessThanOrEqual(4)
  expect(nodeFloors(many(9)).map((f) => f.map((n) => n.id))).toEqual([['n1', 'n2', 'n3', 'n4'], ['n5', 'n6', 'n7', 'n8'], ['n9']])
})

test('étages : l\'ordre reçu est gardé, jamais trié par id ni par statut', () => {
  const received = [nodeOf('cortex'), nodeOf('synapse'), nodeOf('artemis', 'offline-by-design'), nodeOf('helios'), nodeOf('zeta'), nodeOf('alpha')]
  expect(nodeFloors(received).map((f) => f.map((n) => n.id))).toEqual([['cortex', 'synapse', 'artemis', 'helios'], ['zeta', 'alpha']])
  const changed = received.map((n) => ({ ...n, status: n.id === 'cortex' ? 'offline' as const : 'unknown' as const }))
  expect(nodeFloors(changed).map((f) => f.map((n) => n.id))).toEqual(nodeFloors(received).map((f) => f.map((n) => n.id)))
})

test('alerte d\'étage : hors ligne rouge, inconnu ou périmé ambre, hors ligne prévu rien', () => {
  const fresh = () => false
  expect(floorAlert([nodeOf('a'), nodeOf('b', 'offline')], fresh)).toBe('off')
  expect(floorAlert([nodeOf('a', 'unknown')], fresh)).toBe('unknown')
  expect(floorAlert([nodeOf('a', 'offline'), nodeOf('b', 'unknown')], fresh)).toBe('off')
  expect(floorAlert([nodeOf('a', 'offline-by-design'), nodeOf('b')], fresh)).toBeNull()
  expect(floorAlert([nodeOf('a')], fresh)).toBeNull()
  // a stale offline node is not trusted: amber, not red
  expect(floorAlert([nodeOf('a', 'offline')], () => true)).toBe('unknown')
  expect(floorAlert([nodeOf('a')], (n) => n.id === 'a')).toBe('unknown')
  expect(floorAlert([], fresh)).toBeNull()
})

test('alertes autour de l\'étage affiché : jamais pour lui, la plus grave de chaque côté', () => {
  const alerts = [null, 'unknown', 'off', null] as const
  expect(floorAlertSides(alerts, 1)).toEqual({ above: 'off', below: null, others: [{ floor: 2, alert: 'unknown' }, { floor: 3, alert: 'off' }] })
  expect(floorAlertSides(alerts, 2)).toEqual({ above: 'off', below: null, others: [{ floor: 3, alert: 'off' }] })
  expect(floorAlertSides(alerts, 3)).toEqual({ above: null, below: 'unknown', others: [{ floor: 2, alert: 'unknown' }] })
  expect(floorAlertSides(alerts, 4)).toEqual({ above: null, below: 'off', others: [{ floor: 2, alert: 'unknown' }, { floor: 3, alert: 'off' }] })
  expect(floorAlertSides([null, null], 1)).toEqual({ above: null, below: null, others: [] })
  expect(floorAlertSides(['unknown', 'off', 'unknown'], 2)).toEqual({ above: 'unknown', below: 'unknown', others: [{ floor: 1, alert: 'unknown' }, { floor: 3, alert: 'unknown' }] })
})
