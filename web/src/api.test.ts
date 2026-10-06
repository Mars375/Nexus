import { afterEach, expect, test, vi } from 'vitest'
import { fetchHealth, request, tasksApi } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

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

test("avec VITE_NEXUS_API_URL, les requêtes REST et le contrôle de santé visent l'API configurée", async () => {
  vi.stubEnv('VITE_NEXUS_API_URL', 'http://127.0.0.1:8765/')
  vi.resetModules()
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url)
      return new Response('[]', { status: 200 })
    }),
  )
  const api = await import('./api')

  await api.tasksApi.list()
  await api.fetchHealth()

  expect(calls).toEqual(['http://127.0.0.1:8765/api/tasks', 'http://127.0.0.1:8765/api/health'])
  vi.unstubAllEnvs()
  vi.resetModules()
})
