/*
 * Miroir des règles serveur (server/src/nexus/tasks/rules.py), pour guider avant d'envoyer.
 * Le serveur reste l'autorité : un refus de sa part est toujours affiché tel quel.
 */
import type { Status, Task } from '@/api'

export const TRANSITIONS: Record<Status, Status[]> = {
  backlog: ['todo', 'in_progress', 'dropped'],
  todo: ['backlog', 'in_progress', 'dropped'],
  in_progress: ['todo', 'blocked', 'review', 'done', 'dropped'],
  blocked: ['todo', 'in_progress', 'dropped'],
  review: ['in_progress', 'done', 'dropped'],
  done: ['in_progress'],
  dropped: ['backlog'],
}

/** Tâche active : elle doit toujours porter une prochaine action. */
export const ACTIVE_STATUSES: Status[] = ['todo', 'in_progress', 'blocked', 'review']

const GATED_BY_DEPENDENCIES: Status[] = ['in_progress', 'review', 'done']
const DEPENDENCY_RESOLVED: Status[] = ['done', 'dropped']

/** Si des dépendances non traitées interdisent ce passage, la raison ; sinon null. */
export function dependencyBlock(task: Task, to: Status, all: Task[]): string | null {
  // Rouvrir un prérequis traité laisserait ses dépendantes avancées sans prérequis (serveur :
  // reopen_with_advanced_dependents).
  if (DEPENDENCY_RESOLVED.includes(task.status) && !DEPENDENCY_RESOLVED.includes(to)) {
    const advanced = all.filter(
      (t) => t.depends_on.includes(task.id) && GATED_BY_DEPENDENCIES.includes(t.status),
    )
    if (advanced.length) {
      const names = advanced.map((t) => t.title).join(', ')
      const verbs = advanced.length > 1 ? 'en dépendent et ont' : 'en dépend et a'
      return `Impossible de rouvrir : ${names} ${verbs} déjà avancé.`
    }
  }
  if (!GATED_BY_DEPENDENCIES.includes(to)) return null
  const pending = task.depends_on
    .map((id) => all.find((t) => t.id === id))
    .filter((t): t is Task => !!t && !DEPENDENCY_RESOLVED.includes(t.status))
  return pending.length ? `En attente de : ${pending.map((t) => t.title).join(', ')}.` : null
}

/**
 * Pourquoi `task` ne peut pas dépendre de `otherId`, selon les mêmes règles que le serveur ;
 * null si c'est possible. Sert à filtrer les candidats et à expliquer un choix devenu invalide.
 */
export function dependencyRefusal(task: Task, otherId: string, all: Task[]): string | null {
  return refusalWith(task, otherId, dependencyContext(task, all))
}

/** Tâches que `task` peut accepter comme nouvelle dépendance. */
export function dependencyCandidates(task: Task, all: Task[]): Task[] {
  // Contexte calculé une fois pour tout le tableau : linéaire, même sur un grand board.
  const context = dependencyContext(task, all)
  return all.filter((t) => refusalWith(task, t.id, context) === null)
}

type DependencyContext = { byId: Map<string, Task>; reachesTask: Set<string> }

/** Index des tâches, et tâches qui dépendent déjà (transitivement) de `task`. */
function dependencyContext(task: Task, all: Task[]): DependencyContext {
  const byId = new Map(all.map((t) => [t.id, t]))
  const dependents = new Map<string, string[]>()
  for (const t of all) {
    for (const id of t.depends_on) {
      const list = dependents.get(id)
      if (list) list.push(t.id)
      else dependents.set(id, [t.id])
    }
  }
  // Remonter le graphe depuis `task` : en dépendre créerait un cycle.
  const reachesTask = new Set<string>([task.id])
  const stack = [task.id]
  while (stack.length) {
    for (const id of dependents.get(stack.pop()!) ?? []) {
      if (!reachesTask.has(id)) {
        reachesTask.add(id)
        stack.push(id)
      }
    }
  }
  return { byId, reachesTask }
}

function refusalWith(task: Task, otherId: string, { byId, reachesTask }: DependencyContext): string | null {
  const other = byId.get(otherId)
  if (!other) return 'Cette tâche n’existe plus.'
  if (other.id === task.id) return 'Une tâche ne peut pas dépendre d’elle-même.'
  if (task.depends_on.includes(other.id)) return 'Cette dépendance est déjà posée.'
  if (GATED_BY_DEPENDENCIES.includes(task.status) && !DEPENDENCY_RESOLVED.includes(other.status)) {
    return `« ${other.title} » n’est pas encore traitée : une tâche déjà avancée ne peut plus l’attendre.`
  }
  if (reachesTask.has(other.id)) return `« ${other.title} » dépend déjà de cette tâche : cycle refusé.`
  return null
}

export function canMove(from: Status, to: Status): boolean {
  return TRANSITIONS[from].includes(to)
}

/** Ce qu'il faut demander à Loïc avant d'envoyer le déplacement. */
export type MoveNeeds = {
  nextAction: boolean
  block: boolean
  reason: boolean
  /** Une preuve est attendue et aucune n'est jointe : sans preuve, la tâche ira « À vérifier ». */
  evidence: boolean
  /** Préparée « principale » alors qu'une autre l'est déjà en cours : démarrer en auxiliaire ? */
  mainTaken: boolean
}

export function moveNeeds(task: Task, to: Status, all: Task[] = []): MoveNeeds {
  return {
    mainTaken:
      to === 'in_progress' &&
      task.operation_role === 'main' &&
      all.some(
        (t) =>
          t.id !== task.id &&
          t.status === 'in_progress' &&
          t.operation_role === 'main' &&
          t.human_owner === task.human_owner,
      ),
    nextAction: ACTIVE_STATUSES.includes(to) && !task.next_action?.trim(),
    block: to === 'blocked',
    reason: to === 'dropped',
    evidence: to === 'done' && !!task.expected_evidence?.trim() && task.evidence.length === 0,
  }
}

export function needsPrompt(needs: MoveNeeds): boolean {
  return needs.nextAction || needs.block || needs.reason || needs.evidence || needs.mainTaken
}
