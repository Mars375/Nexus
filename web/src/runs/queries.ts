import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from '@/api'
import { getAuthState } from '@/auth'
import { REFRESH_MS } from '@/freshness'
import { runsApi, type RunDraft } from '@/runsApi'

/** Under `['tasks', id]` on purpose: a `task_changed` message refreshes the runs too. */
export const runsKey = (taskId: string) => ['tasks', taskId, 'runs'] as const
export const executorsKey = ['executors'] as const

// Serveur local : toujours tenter la requête, jamais de pause « hors ligne ».
const local = { networkMode: 'always' } as const

/** A 401 that locked the app is told by the lock screen, which covers the toasts. */
function notifyError(error: unknown) {
  if (error instanceof ApiError && error.status === 401 && getAuthState().locked) return
  toast.error(error instanceof ApiError ? error.message : 'Le serveur Nexus ne répond pas.')
}

/** The runs of a task, newest first; the periodic read stays the safety net of `run_changed`. */
export function useRuns(taskId: string) {
  return useQuery({
    queryKey: runsKey(taskId),
    queryFn: ({ signal }) => runsApi.forTask(taskId, signal),
    refetchInterval: REFRESH_MS.tasks,
    ...local,
  })
}

/** The proofs of a task's runs, read only once there is a run (they come from its events). */
export function useRunEvidence(taskId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['tasks', taskId, 'run-evidence'],
    queryFn: ({ signal }) => runsApi.evidence(taskId, signal),
    enabled,
    refetchInterval: REFRESH_MS.tasks,
    ...local,
  })
}

/** Which executors can take work now: read when the dialog opens, never cached for long. */
export function useExecutors(enabled: boolean) {
  return useQuery({
    queryKey: executorsKey,
    queryFn: ({ signal }) => runsApi.executors(signal),
    enabled,
    staleTime: 0,
    gcTime: 0,
    ...local,
  })
}

/** A key for one dialog: stable across clicks and resends, new for the next dialog. */
export function newClientKey(): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `ui-${random}`
}

/**
 * « Confier à » : the refusal stays in the mutation so that the dialog can say it under the form
 * and keep what was typed (no toast). The task, its history and its runs are read again.
 */
export function useDispatchRun(taskId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (draft: RunDraft) => runsApi.dispatch(taskId, draft),
    onSettled: () => client.invalidateQueries({ queryKey: ['tasks'] }),
    ...local,
  })
}

export function useCancelRun(taskId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) => runsApi.cancel(runId),
    onSuccess: () => toast.success('Annulation demandée'),
    onError: notifyError,
    onSettled: () => client.invalidateQueries({ queryKey: runsKey(taskId) }),
    ...local,
  })
}
