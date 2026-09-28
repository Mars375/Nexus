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
}

export function moveNeeds(task: Task, to: Status): MoveNeeds {
  return {
    nextAction: ACTIVE_STATUSES.includes(to) && !task.next_action?.trim(),
    block: to === 'blocked',
    reason: to === 'dropped',
    evidence: to === 'done' && !!task.expected_evidence?.trim() && task.evidence.length === 0,
  }
}

export function needsPrompt(needs: MoveNeeds): boolean {
  return needs.nextAction || needs.block || needs.reason || needs.evidence
}
