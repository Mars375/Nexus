import { afterEach, expect, test, vi } from 'vitest'
import { fetchHealth, request, tasksApi } from './api'

afterEach(() => vi.unstubAllGlobals())

test("un contrôle sans réponse échoue au bout du délai au lieu d'attendre indéfiniment", async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))
        }),
    ),
  )

  await expect(fetchHealth(undefined, 20)).rejects.toThrow()
})

function hangingFetch() {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))
      }),
  )
}

test("une requête de tâches sans réponse échoue au bout du délai au lieu d'attendre indéfiniment", async () => {
  vi.stubGlobal('fetch', hangingFetch())

  await expect(request('/api/tasks', undefined, 20)).rejects.toThrow()
})

test("l'annulation demandée par TanStack Query est transmise à la requête", async () => {
  vi.stubGlobal('fetch', hangingFetch())
  const controller = new AbortController()

  const pending = tasksApi.list(controller.signal)
  controller.abort()

  await expect(pending).rejects.toThrow()
})
