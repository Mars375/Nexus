import { expect, test } from 'vitest'
import type { HistoryEntry } from '@/api'
import { describeHistory } from './history'

function entry(actor: string, changes: Record<string, unknown>, action = 'updated'): HistoryEntry {
  return {
    id: 1, task: 'nx-task-1', actor: actor as HistoryEntry['actor'], at: '2026-10-01T10:00:00+02:00',
    action, changes, source: 'nexus.db', measured_at: '2026-10-01T10:00:00+02:00',
  }
}

test('un agent qui devient lui-même agent principal', () => {
  expect(describeHistory(entry('helios', { lead_agent: [null, 'helios'] }))).toBe('est devenu agent principal')
})

test('quelqu’un confie la tâche à un autre', () => {
  expect(describeHistory(entry('loic', { lead_agent: ['helios', 'hermes'] }))).toBe('a confié la tâche à Hermes')
})

test('l’agent principal retiré', () => {
  expect(describeHistory(entry('loic', { lead_agent: ['helios', null] }))).toBe('a retiré l’agent principal')
})

test('un agent principal inconnu ne plante pas et n’est pas affiché tel quel', () => {
  expect(describeHistory(entry('loic', { lead_agent: [null, 'ghp_secret'] }))).toBe('a changé l’agent principal')
})

test('un champ modifié est nommé, sans sa valeur', () => {
  const text = describeHistory(entry('loic', { next_action: ['ancienne', 'token=[REDACTED]'] }))
  expect(text).toBe('a modifié la prochaine action')
  expect(text).not.toMatch(/REDACTED|ancienne/)
})

test.each([
  ['title', 'a modifié le titre'],
  ['objective', 'a modifié l’objectif'],
  ['human_owner', 'a modifié le propriétaire'],
  ['collaborators', 'a modifié les collaborateurs'],
  ['due_at', 'a modifié l’échéance'],
  ['follow_up_at', 'a modifié la relance'],
  ['expected_evidence', 'a modifié la preuve attendue'],
  ['priority', 'a modifié la priorité'],
  ['operation_role', 'a modifié le rôle d’opération'],
  ['origin', 'a modifié l’origine'],
  ['context', 'a modifié le contexte'],
])('libellé de %s', (field, expected) => {
  expect(describeHistory(entry('loic', { [field]: ['a', 'b'] }))).toBe(expected)
})

test('plusieurs champs courts sont listés', () => {
  expect(describeHistory(entry('loic', { title: ['a', 'b'], priority: ['x', 'y'] }))).toBe(
    'a modifié le titre et la priorité',
  )
})

test('trop de champs : plusieurs champs', () => {
  const changes = { title: [1, 2], priority: [1, 2], objective: [1, 2], due_at: [1, 2] }
  expect(describeHistory(entry('loic', changes))).toBe('a modifié plusieurs champs')
})

test('un champ inconnu reste générique, sans afficher son nom', () => {
  expect(describeHistory(entry('loic', { 'sk-abc': [1, 2] }))).toBe('a modifié un champ')
})

test('une forme inattendue de changements ne plante pas', () => {
  expect(describeHistory(entry('loic', { lead_agent: 'oops' }))).toBe('a changé l’agent principal')
})

test('les autres actions gardent leur libellé', () => {
  expect(describeHistory(entry('loic', {}, 'created'))).toBe('a créé la tâche')
})
