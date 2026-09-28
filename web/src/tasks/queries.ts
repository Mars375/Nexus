import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  ApiError,
  tasksApi,
  type StatusChange,
  type Task,
  type TaskChanges,
  type TaskDraft,
} from '@/api'

export const tasksKey = ['tasks'] as const
export const taskDetailKey = (id: string, part: 'comments' | 'history') => ['tasks', id, part]

// Serveur local : toujours tenter la requête, jamais de pause « hors ligne ».
const local = { networkMode: 'always' } as const

function explain(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Le serveur Nexus ne répond pas.'
}

export function useTasks() {
  return useQuery({ queryKey: tasksKey, queryFn: tasksApi.list, ...local })
}

export function useComments(id: string) {
  return useQuery({ queryKey: taskDetailKey(id, 'comments'), queryFn: () => tasksApi.comments(id), ...local })
}

export function useHistory(id: string) {
  return useQuery({ queryKey: taskDetailKey(id, 'history'), queryFn: () => tasksApi.history(id), ...local })
}

function useRefresh() {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: tasksKey })
}

export function useCreateTask() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: (draft: TaskDraft) => tasksApi.create(draft),
    onSuccess: (task) => toast.success(`Tâche créée : ${task.title}`),
    onError: (error) => toast.error(explain(error)),
    onSettled: refresh,
    ...local,
  })
}

export function useUpdateTask() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: TaskChanges }) =>
      tasksApi.update(id, changes),
    onSuccess: () => toast.success('Modifications enregistrées'),
    onError: (error) => toast.error(explain(error)),
    onSettled: refresh,
    ...local,
  })
}

/**
 * Déplacement optimiste : la carte change de colonne tout de suite ; si le serveur refuse,
 * elle revient à sa place et la raison s'affiche.
 */
export function useMoveTask() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, change }: { id: string; change: StatusChange }) => tasksApi.move(id, change),
    onMutate: async ({ id, change }) => {
      await client.cancelQueries({ queryKey: tasksKey })
      const previous = client.getQueryData<Task[]>(tasksKey)
      client.setQueryData<Task[]>(tasksKey, (tasks) =>
        tasks?.map((t) => (t.id === id ? { ...t, status: change.status } : t)),
      )
      return { previous }
    },
    onSuccess: (task, { change }) => {
      if (task.status !== change.status) {
        toast.warning('Preuve attendue manquante : la tâche passe « À vérifier ».')
      }
    },
    onError: (error, _vars, context) => {
      if (context?.previous) client.setQueryData(tasksKey, context.previous)
      toast.error(explain(error))
    },
    onSettled: () => client.invalidateQueries({ queryKey: tasksKey }),
    ...local,
  })
}

export function useAddComment(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: string) => tasksApi.comment(id, body),
    onError: (error) => toast.error(explain(error)),
    onSettled: () => client.invalidateQueries({ queryKey: ['tasks', id] }),
    ...local,
  })
}

export function useLink(id: string) {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: ({ other, remove }: { other: string; remove?: boolean }) =>
      remove ? tasksApi.unlink(id, other) : tasksApi.link(id, other),
    onError: (error) => toast.error(explain(error)),
    onSettled: refresh,
    ...local,
  })
}
