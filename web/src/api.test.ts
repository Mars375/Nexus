import { afterEach, expect, test, vi } from 'vitest'
import { fetchHealth } from './api'

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
