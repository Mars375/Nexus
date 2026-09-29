import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { Task } from '@/api'
import { TaskCardBody } from './TaskCard'

function task(overrides: Partial<Task>): Task {
  return {
    id: 'nx-task-1', title: 'Pont lecture', objective: 'Lire les runs', status: 'in_progress',
    human_owner: 'loic', lead_agent: null, collaborators: [], next_action: 'relever les tables',
    due_at: null, follow_up_at: null, block_cause: null, block_plan: null, drop_reason: null,
    expected_evidence: null, evidence: [], priority: 'normal', operation_role: null, origin: null,
    context: [], depends_on: [], created_by: 'loic', created_at: '2026-09-28T10:00:00+02:00',
    updated_at: '2026-09-28T10:00:00+02:00', source: 'nexus.db',
    measured_at: '2026-09-28T10:00:00+02:00', ...overrides,
  }
}

test('une opération auxiliaire en cours est marquée sur sa carte', () => {
  render(<TaskCardBody task={task({ operation_role: 'auxiliary' })} pendingDependencies={[]} now={0} />)
  expect(screen.getByText('Opération auxiliaire')).toBeInTheDocument()
})

test("une tâche en cours sans rôle ne porte aucun marqueur d'opération", () => {
  render(<TaskCardBody task={task({})} pendingDependencies={[]} now={0} />)
  expect(screen.queryByText(/^Opération/)).not.toBeInTheDocument()
})
