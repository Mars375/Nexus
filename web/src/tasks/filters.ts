import type { Actor, Priority, Role, Status, Task } from '@/api'
import { isOverdue } from '@/format'

export type Due = '' | 'overdue' | 'week'

export type Filters = {
  agent: Actor | ''
  status: Status | ''
  priority: Priority | ''
  role: Role | ''
  due: Due
  showDropped: boolean
}

export const NO_FILTER: Filters = {
  agent: '',
  status: '',
  priority: '',
  role: '',
  due: '',
  showDropped: false,
}

const WEEK = 7 * 24 * 3600 * 1000

/** Le statut ne filtre pas ici : il choisit les colonnes affichées. */
export function applyFilters(tasks: Task[], f: Filters, now: number): Task[] {
  return tasks.filter(
    (t) =>
      (!f.agent || t.lead_agent === f.agent || t.collaborators.includes(f.agent)) &&
      (!f.priority || t.priority === f.priority) &&
      // Même règle que le serveur : le rôle filtre aussi les tâches où il est seulement préparé.
      (!f.role || t.operation_role === f.role) &&
      (f.due !== 'overdue' || (isOverdue(t.due_at, now) && t.status !== 'done')) &&
      (f.due !== 'week' ||
        (t.due_at !== null &&
          new Date(t.due_at).getTime() >= now &&
          new Date(t.due_at).getTime() - now < WEEK)),
  )
}
