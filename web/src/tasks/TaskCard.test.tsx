import { fireEvent, render, screen } from '@testing-library/react'
import { DndContext } from '@dnd-kit/core'
import { expect, test, vi } from 'vitest'
import type { Task } from '@/api'
import { TaskCard, TaskCardBody } from './TaskCard'

function task(overrides: Partial<Task>): Task {
  return {
    id: 'nx-task-1', title: 'Pont lecture', objective: 'Lire les runs', status: 'in_progress',
    human_owner: 'loic', lead_agent: null, collaborators: [], next_action: 'relever les tables',
    due_at: null, follow_up_at: null, block_cause: null, block_plan: null, drop_reason: null,
    expected_evidence: null, evidence: [], priority: 'normal', operation_role: null, origin: null,
    context: [], depends_on: [], follows: null, created_by: 'loic', created_at: '2026-09-28T10:00:00+02:00',
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

test('le nom accessible d’une tâche de suite dit de quelle tâche, après le préfixe « Titre — »', () => {
  render(
    <TaskCard task={task({ follows: 'nx-task-7', lead_agent: 'helios' })} pendingDependencies={[]} now={0} onOpen={() => {}} />,
    { wrapper: ({ children }) => <DndContext>{children}</DndContext> },
  )
  const button = screen.getByRole('button', { name: /^Pont lecture — / })
  expect(button).toHaveAccessibleName(/\(agent principal Helios\) \(suite de nx-task-7\)$/)
})

const dnd = { wrapper: ({ children }: { children: React.ReactNode }) => <DndContext>{children}</DndContext> }

test('« Ensuite : » est masqué sur une tâche terminée ou abandonnée, malgré sa prochaine action', () => {
  for (const status of ['done', 'dropped'] as const) {
    const { unmount } = render(
      <TaskCardBody task={task({ status, next_action: 'relever les tables' })} pendingDependencies={[]} now={0} />,
    )
    expect(screen.queryByText(/Ensuite/)).not.toBeInTheDocument()
    expect(screen.queryByText('relever les tables')).not.toBeInTheDocument()
    unmount()
  }
  render(<TaskCardBody task={task({ status: 'todo' })} pendingDependencies={[]} now={0} />)
  expect(screen.getByText('relever les tables')).toBeInTheDocument()
})

test('une tâche de suite porte « Suite de #N » sur sa carte', () => {
  render(<TaskCardBody task={task({ follows: 'nx-task-7' })} pendingDependencies={[]} now={0} />)
  expect(screen.getByText('Suite de #7')).toBeInTheDocument()
})

test('une tâche sans lien ne montre pas « Suite de »', () => {
  render(<TaskCardBody task={task({})} pendingDependencies={[]} now={0} />)
  expect(screen.queryByText(/Suite de/)).not.toBeInTheDocument()
})

test('la carte d’une tâche terminée s’ouvre, sans rien promettre de déplaçable', () => {
  const onOpen = vi.fn()
  render(<TaskCard task={task({ status: 'done' })} pendingDependencies={[]} now={0} onOpen={onOpen} />, dnd)
  const button = screen.getByRole('button', { name: /— ouvrir$/ })
  expect(button).toBeEnabled()
  expect(button).not.toHaveAccessibleName(/déplacer/)
  expect(button).not.toHaveAttribute('aria-disabled')
  expect(button).not.toHaveAttribute('aria-roledescription')
  expect(button).not.toHaveAttribute('aria-describedby')
  expect(button).not.toHaveClass('cursor-grab')
  fireEvent.click(button)
  expect(onOpen).toHaveBeenCalledWith('nx-task-1')
})

test('la carte d’une tâche non terminée garde ses attributs de glisser', () => {
  render(<TaskCard task={task({ status: 'in_progress' })} pendingDependencies={[]} now={0} onOpen={() => {}} />, dnd)
  const button = screen.getByRole('button', { name: /— ouvrir ou déplacer/ })
  expect(button).toHaveAttribute('aria-roledescription', 'draggable')
  expect(button).toHaveClass('cursor-grab')
})

test('une tâche abandonnée reste déplaçable (reprise explicite)', () => {
  render(<TaskCard task={task({ status: 'dropped' })} pendingDependencies={[]} now={0} onOpen={() => {}} />, dnd)
  expect(screen.getByRole('button', { name: /— ouvrir ou déplacer/ })).toBeInTheDocument()
})
