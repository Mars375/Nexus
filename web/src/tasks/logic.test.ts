import { describe, expect, test } from 'vitest'
import type { Task } from '@/api'
import { applyFilters, NO_FILTER } from './filters'
import { canMove, dependencyBlock, moveNeeds, needsPrompt } from './moves'
import { compareTasks } from './vocabulary'

const NOW = new Date('2026-09-28T12:00:00+02:00').getTime()

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: 'nx-task-1',
    title: 'Pont lecture',
    objective: 'Lire les runs',
    status: 'todo',
    human_owner: 'loic',
    lead_agent: null,
    collaborators: [],
    next_action: 'relever les tables',
    due_at: null,
    follow_up_at: null,
    block_cause: null,
    block_plan: null,
    drop_reason: null,
    expected_evidence: null,
    evidence: [],
    priority: 'normal',
    operation_role: null,
    origin: null,
    context: [],
    depends_on: [],
    created_by: 'loic',
    created_at: '2026-09-28T10:00:00+02:00',
    updated_at: '2026-09-28T10:00:00+02:00',
    source: 'nexus.db',
    measured_at: '2026-09-28T10:00:00+02:00',
    ...overrides,
  }
}

describe('déplacements', () => {
  test('suit la table de transitions du serveur', () => {
    expect(canMove('todo', 'in_progress')).toBe(true)
    expect(canMove('backlog', 'review')).toBe(false)
    expect(canMove('done', 'in_progress')).toBe(true)
    expect(canMove('dropped', 'todo')).toBe(false)
  })

  test('demande la prochaine action pour activer une tâche qui n’en a pas', () => {
    const needs = moveNeeds(task({ status: 'backlog', next_action: null }), 'todo')
    expect(needs.nextAction).toBe(true)
    expect(needsPrompt(needs)).toBe(true)
  })

  test('un déplacement simple part sans question', () => {
    expect(needsPrompt(moveNeeds(task(), 'in_progress'))).toBe(false)
  })

  test('bloquer et abandonner demandent toujours des précisions', () => {
    expect(moveNeeds(task({ status: 'in_progress' }), 'blocked').block).toBe(true)
    expect(moveNeeds(task(), 'dropped').reason).toBe(true)
  })

  test('clore une tâche qui attend une preuve le signale', () => {
    const t = task({ status: 'in_progress', expected_evidence: 'commit' })
    expect(moveNeeds(t, 'done').evidence).toBe(true)
    expect(moveNeeds({ ...t, evidence: ['commit:a1b2c3d'] }, 'done').evidence).toBe(false)
  })
})

describe('filtres', () => {
  const tasks = [
    task({ id: 'a', lead_agent: 'helios', priority: 'high' }),
    task({ id: 'b', collaborators: ['helios'], due_at: '2026-09-27T09:00:00+02:00' }),
    task({ id: 'c', due_at: '2026-10-01T09:00:00+02:00', status: 'in_progress', operation_role: 'main' }),
    task({ id: 'd', due_at: '2026-12-01T09:00:00+02:00' }),
  ]
  const ids = (list: Task[]) => list.map((t) => t.id)

  test("l'agent couvre agent principal et collaborateurs", () => {
    expect(ids(applyFilters(tasks, { ...NO_FILTER, agent: 'helios' }, NOW))).toEqual(['a', 'b'])
  })

  test('priorité, rôle et échéances', () => {
    expect(ids(applyFilters(tasks, { ...NO_FILTER, priority: 'high' }, NOW))).toEqual(['a'])
    expect(ids(applyFilters(tasks, { ...NO_FILTER, role: 'main' }, NOW))).toEqual(['c'])
    const prepared = [...tasks, task({ id: 'e', status: 'todo', operation_role: 'auxiliary' })]
    expect(ids(applyFilters(prepared, { ...NO_FILTER, role: 'auxiliary' }, NOW))).toEqual(['e'])
    expect(ids(applyFilters(tasks, { ...NO_FILTER, due: 'overdue' }, NOW))).toEqual(['b'])
    expect(ids(applyFilters(tasks, { ...NO_FILTER, due: 'week' }, NOW))).toEqual(['c'])
  })
})

test("l'opération principale passe en tête, puis priorité puis échéance", () => {
  const sorted = [
    task({ id: 'low', priority: 'low' }),
    task({ id: 'due-late', due_at: '2026-10-10T00:00:00Z' }),
    task({ id: 'due-soon', due_at: '2026-10-01T00:00:00Z' }),
    task({ id: 'critical', priority: 'critical' }),
    task({ id: 'main', operation_role: 'main', priority: 'low' }),
  ].sort(compareTasks)
  expect(sorted.map((t) => t.id)).toEqual(['main', 'critical', 'due-soon', 'due-late', 'low'])
})

describe('dépendances', () => {
  const prereq = task({ id: 'p', title: 'Prérequis', status: 'todo' })
  const dependent = task({ id: 'd', depends_on: ['p'] })

  test('une dépendance non traitée bloque les passages concernés', () => {
    expect(dependencyBlock(dependent, 'in_progress', [prereq, dependent])).toBe(
      'En attente de : Prérequis.',
    )
    expect(dependencyBlock(dependent, 'backlog', [prereq, dependent])).toBeNull()
  })

  test("rouvrir un prérequis dont une dépendante a avancé est bloqué", () => {
    const done = task({ id: 'p', title: 'Prérequis', status: 'done' })
    const advanced = task({ id: 'd', title: 'Dépendante', status: 'in_progress', depends_on: ['p'] })
    expect(dependencyBlock(done, 'in_progress', [done, advanced])).toBe(
      'Impossible de rouvrir : Dépendante en dépend et a déjà avancé.',
    )
    const waiting = { ...advanced, status: 'todo' as const }
    expect(dependencyBlock(done, 'in_progress', [done, waiting])).toBeNull()
  })

  test('une dépendance terminée ou abandonnée ne bloque plus', () => {
    for (const status of ['done', 'dropped'] as const) {
      expect(dependencyBlock(dependent, 'in_progress', [{ ...prereq, status }, dependent])).toBeNull()
    }
  })
})

describe('opération principale', () => {
  const running = task({ id: 'm', status: 'in_progress', operation_role: 'main' })
  const prepared = task({ id: 'p', status: 'todo', operation_role: 'main' })

  test('démarrer une tâche préparée « principale » quand une autre tourne demande confirmation', () => {
    const needs = moveNeeds(prepared, 'in_progress', [running, prepared])
    expect(needs.mainTaken).toBe(true)
    expect(needsPrompt(needs)).toBe(true)
  })

  test('sans autre principale en cours, rien à demander', () => {
    expect(moveNeeds(prepared, 'in_progress', [prepared]).mainTaken).toBe(false)
    expect(moveNeeds({ ...prepared, operation_role: null }, 'in_progress', [running]).mainTaken).toBe(false)
  })
})
