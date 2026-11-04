import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { harness, INSTANCE_A, INSTANCE_B, HELLO } from './liveSupport'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('connectLive avec VITE_NEXUS_API_URL', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })
  test("ouvre le WebSocket sur l'API configurée, pas sur la page", async () => {
    vi.stubEnv('VITE_NEXUS_API_URL', 'http://127.0.0.1:8765')
    vi.resetModules()
    const live = await import('./live')
    const urls: string[] = []
    const stop = live.connectLive({
      ticket: () => Promise.resolve('nxw_' + 'A'.repeat(43)),
      isLocked: () => false,
      onUnlock: () => () => {},
      open: (url) => {
        urls.push(url)
        return { onopen: null, onmessage: null, onclose: null, close() {} }
      },
      onMessage: () => {},
      onState: () => {},
    })
    await vi.advanceTimersByTimeAsync(0)
    stop()
    expect(urls).toEqual(['ws://127.0.0.1:8765/api/ws'])
  })
})

describe('instance du serveur', () => {
  const hello = (instance?: unknown) => ({ ...HELLO, ...(instance === undefined ? {} : { instance }) })
  const reconnect = async (h: Awaited<ReturnType<typeof harness>>) => {
    h.drop()
    await vi.advanceTimersByTimeAsync(500)
    return h.last().url
  }

  test("la reconnexion envoie le dernier curseur ET l'instance du dernier hello", async () => {
    const h = await harness()
    h.open()
    h.send(hello(INSTANCE_A))
    expect(await reconnect(h)).toContain(`history_after=3&events_after=4&instance=${INSTANCE_A}`)
  })

  test('un second hello avec une autre instance remplace la précédente', async () => {
    const h = await harness()
    h.open()
    h.send(hello(INSTANCE_A))
    h.send(hello(INSTANCE_B))
    const url = await reconnect(h)
    expect(url).toContain(`instance=${INSTANCE_B}`)
    expect(url).not.toContain(INSTANCE_A)
  })

  test.each([123, '', 'ABCDEF0123456789', '0123456789abcdef0', '0123456789abcde', null])(
    'un hello avec instance %j est ignoré : curseur conservé, pas connecté',
    async (bad) => {
      const h = await harness()
      h.open()
      h.send({ ...HELLO, cursor: { history: 1, events: 1 }, instance: bad })
      expect(h.states.some((s) => s.status === 'connected')).toBe(false)
      expect(h.messages).toEqual([])
      expect(await reconnect(h)).toBe('ws://localhost:3000/api/ws')
    },
  )

  test('un hello invalide après un hello valide garde le curseur et l\'instance précédents', async () => {
    const h = await harness()
    h.open()
    h.send(hello(INSTANCE_A))
    h.send({ ...HELLO, cursor: { history: 9, events: 9 }, instance: 'X' })
    expect(await reconnect(h)).toContain(`history_after=3&events_after=4&instance=${INSTANCE_A}`)
  })

  test("un hello sans instance (ancien serveur) est accepté et la reconnexion n'en envoie pas", async () => {
    const h = await harness()
    h.open()
    h.send(hello(INSTANCE_A))
    h.send(hello())
    expect(h.states.at(-1)).toEqual({ status: 'connected' })
    const url = await reconnect(h)
    expect(url).toContain('history_after=3&events_after=4')
    expect(url).not.toContain('instance')
  })
})
