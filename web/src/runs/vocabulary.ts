import { ApiError } from '@/api'
import type { RunStatus } from '@/runsApi'

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  dispatched: 'Confié',
  running: 'En cours',
  unknown: 'Suivi perdu',
  blocked: 'Bloqué',
  review: 'À vérifier',
  done: 'Terminé',
  failed: 'Échoué',
  cancelled: 'Annulé',
}

/** A task that ended (done) or was dropped cannot be handed over (the server says 409). */
export const HANDOVER_CLOSED: readonly string[] = ['done', 'dropped']

/** A run that still holds its agent: the one a human may cancel (server `ACTIVE`). */
export const CANCELLABLE: readonly RunStatus[] = ['dispatched', 'running', 'unknown']

/**
 * What a refusal of « Confier à » means for Loïc. The server already writes French messages;
 * these say what to do next. Any other code keeps the server's own message.
 */
const REFUSAL: Record<string, string> = {
  executor_unavailable:
    'Cet exécutant n’est pas configuré sur ce serveur : rien n’a été lancé. Il faut un binaire et un dépôt de travail déclarés (INTEGRATIONS §A.2).',
  executor_busy: 'Cet exécutant a déjà un run actif : annule-le ou attends sa fin.',
  run_already_active: 'Cet agent a déjà un run actif sur cette tâche : annule-le ou attends sa fin.',
  agent_not_for_executor: 'Cet exécutant ne travaille pas pour cet agent : choisis un autre couple.',
  transition_refused: 'Cette tâche a été abandonnée : reprends-la avant de la confier.',
  concurrent_update: 'La tâche vient d’être modifiée ailleurs : ferme ce dialogue, relis-la et réessaie.',
  task_done: 'Cette tâche est terminée : elle ne se modifie plus. Ouvre une tâche de suite.',
  next_action_required: 'Cette tâche n’a pas de prochaine action : ajoute-en une avant de la confier.',
  dependencies_pending: 'Cette tâche attend encore une dépendance : traite-la d’abord.',
  main_operation_taken: 'Une autre opération principale est déjà en cours pour toi.',
  client_key_reused: 'Cette demande a déjà servi pour un autre contenu : relance la confirmation.',
  secret_in_workdir: 'Le dossier de travail contient un secret : retire-le.',
  brief_required: 'Le brief ne contient rien de lisible une fois les secrets masqués.',
}

export function refusalText(error: unknown): string {
  if (error instanceof ApiError) return REFUSAL[error.code] ?? error.message
  return 'Le serveur Nexus ne répond pas : rien ne dit si le run a été créé. Relis la liste avant de réessayer.'
}
