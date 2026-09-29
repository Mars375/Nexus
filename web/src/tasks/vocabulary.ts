import type { Actor, Priority, Role, Status } from '@/api'

/** Colonnes du tableau, dans l'ordre de lecture. `dropped` est masquée par défaut. */
export const BOARD_STATUSES: Status[] = ['backlog', 'todo', 'in_progress', 'blocked', 'review', 'done']

export const STATUS_LABEL: Record<Status, string> = {
  backlog: 'Plus tard',
  todo: 'À faire',
  in_progress: 'En cours',
  blocked: 'Bloqué',
  review: 'À vérifier',
  done: 'Terminé',
  dropped: 'Abandonné',
}

export const PRIORITY_LABEL: Record<Priority, string> = {
  low: 'Basse',
  normal: 'Normale',
  high: 'Haute',
  critical: 'Critique',
}

export const ROLE_LABEL: Record<Role, string> = {
  main: 'Opération principale',
  auxiliary: 'Auxiliaire',
}

export const ACTORS: Actor[] = [
  'loic',
  'helios',
  'mnema',
  'aether',
  'artemis',
  'claude',
  'codex',
  'orca',
  'hermes',
]

export const ACTOR_NAME: Record<Actor, string> = {
  loic: 'Loïc',
  helios: 'Helios',
  mnema: 'Mnēma',
  aether: 'Aether',
  artemis: 'Artémis',
  claude: 'Claude',
  codex: 'Codex',
  orca: 'Orca',
  hermes: 'Hermes',
}

const PRIORITY_RANK: Record<Priority, number> = { critical: 0, high: 1, normal: 2, low: 3 }

/** Ordre dans une colonne : opération principale, puis priorité, échéance, fraîcheur. */
export function compareTasks(
  a: { operation_role: Role | null; priority: Priority; due_at: string | null; updated_at: string },
  b: typeof a,
): number {
  const main = Number(b.operation_role === 'main') - Number(a.operation_role === 'main')
  if (main) return main
  const priority = PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority]
  if (priority) return priority
  // Instants, pas texte : deux dates de la même heure murale peuvent porter des décalages
  // différents (heure d'hiver).
  const dueA = a.due_at ? Date.parse(a.due_at) : null
  const dueB = b.due_at ? Date.parse(b.due_at) : null
  if (dueA !== dueB) {
    if (dueA === null) return 1
    if (dueB === null) return -1
    return dueA - dueB
  }
  return Date.parse(b.updated_at) - Date.parse(a.updated_at)
}
