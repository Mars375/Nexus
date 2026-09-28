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

const ACTIVE: Status[] = ['todo', 'in_progress', 'blocked', 'review']

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
    nextAction: ACTIVE.includes(to) && !task.next_action?.trim(),
    block: to === 'blocked',
    reason: to === 'dropped',
    evidence: to === 'done' && !!task.expected_evidence?.trim() && task.evidence.length === 0,
  }
}

export function needsPrompt(needs: MoveNeeds): boolean {
  return needs.nextAction || needs.block || needs.reason || needs.evidence
}
