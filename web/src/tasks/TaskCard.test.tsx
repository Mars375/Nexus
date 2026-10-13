import { render, screen } from '@testing-library/react'
import { DndContext } from '@dnd-kit/core'
import { expect, test } from 'vitest'
import type { Task } from '@/api'
import { TaskCard, TaskCardBody } from './TaskCard'

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

test("l'agent principal est nommé en clair sur la carte, sans survol", () => {
  render(<TaskCardBody task={task({ lead_agent: 'helios' })} pendingDependencies={[]} now={0} />)
  // jsdom has no CSS: `toBeVisible` alone also passes on a `.sr-only` name, so check the class.
  const helios = screen.getByText('Helios')
  expect(helios).toBeVisible()
  expect(helios.closest('.sr-only')).toBeNull()
  render(<TaskCardBody task={task({ lead_agent: 'hermes' })} pendingDependencies={[]} now={0} />)
  const hermes = screen.getByText('Hermes')
  expect(hermes).toBeVisible()
  expect(hermes.closest('.sr-only')).toBeNull()
})

test('une tâche sans agent principal ne montre aucun nom d’agent', () => {
  render(<TaskCardBody task={task({ lead_agent: null })} pendingDependencies={[]} now={0} />)
  expect(screen.queryByText('Helios')).not.toBeInTheDocument()
})

test('un agent principal inconnu ne plante pas la carte', () => {
  const odd = 'inconnu' as unknown as Task['lead_agent']
  render(<TaskCardBody task={task({ lead_agent: odd })} pendingDependencies={[]} now={0} />)
  expect(screen.getByText('Agent inconnu')).toBeInTheDocument()
})

test('le nom accessible du bouton de la carte inclut l’agent principal', () => {
  render(
    <TaskCard task={task({ lead_agent: 'helios' })} pendingDependencies={[]} now={0} onOpen={() => {}} />,
    { wrapper: ({ children }) => <DndContext>{children}</DndContext> },
  )
  expect(screen.getByRole('button', { name: /agent principal Helios/ })).toBeInTheDocument()
})
