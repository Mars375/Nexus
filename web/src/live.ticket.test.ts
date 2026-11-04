import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError } from './api'
import {
  SILENCE_MS,
} from './live'
import { harness, numberedTickets } from './liveSupport'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('ticket WebSocket (#57)', () => {
  const deferred = () => {
    let resolve!: (ticket: string) => void
    let reject!: (error: unknown) => void
    const promise = new Promise<string>((res, rej) => {
      resolve = res
      reject = rej
    })
    return { promise, resolve, reject }
  }
  const refused401 = () => new ApiError(401, 'invalid_token', 'refus')

  test('une demande de ticket précède chaque ouverture, reconnexions comprises, avec un ticket différent', async () => {
    const h = await harness()
    expect(h.signals).toHaveLength(1)
    h.up()
    h.drop()
    await vi.advanceTimersByTimeAsync(500)
    h.up()
    h.drop()
    await vi.advanceTimersByTimeAsync(500)
    expect(h.signals).toHaveLength(3)
    expect(h.sockets).toHaveLength(3)
    const tickets = h.sockets.map((socket) => socket.protocols[1])
    expect(new Set(tickets).size).toBe(3)
    for (const socket of h.sockets) {
      expect(socket.protocols).toHaveLength(2)
      expect(socket.protocols[0]).toBe('nexus.live.v1')
      expect(socket.protocols[1]).toMatch(/^nxw_/)
    }
  })

  test("aucune URL ne contient le ticket, ni le préfixe nxw_", async () => {
    const h = await harness()
    h.up()
    h.drop()
    await vi.advanceTimersByTimeAsync(500)
    for (const socket of h.sockets) {
      expect(socket.url).not.toContain('nxw_')
      expect(socket.url).not.toContain(socket.protocols[1])
    }
  })

  test("application déjà verrouillée : aucune demande de ticket, aucune socket, même longtemps après", async () => {
    const h = await harness({ locked: true })
    expect(h.signals).toHaveLength(0)
    expect(h.sockets).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(h.signals).toHaveLength(0)
    expect(h.sockets).toHaveLength(0)
  })

  test("verrouillée pendant la demande (401) : aucune socket, aucune nouvelle demande", async () => {
    const h = await harness({
      lockOnTicket: true,
      ticket: () => Promise.reject(refused401()),
    })
    expect(h.sockets).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(h.sockets).toHaveLength(0)
    expect(h.signals).toHaveLength(1)
  })

  test("verrouillée pendant la demande, ticket obtenu quand même : aucune socket ouverte avant le déverrouillage", async () => {
    const h = await harness({ lockOnTicket: true }) // the ticket request succeeds while a REST 401 locks the app
    expect(h.signals).toHaveLength(1)
    expect(h.sockets).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(h.sockets).toHaveLength(0)
    await h.unlock()
    expect(h.signals).toHaveLength(2) // a fresh ticket: the first one is never reused
    expect(h.sockets).toHaveLength(1)
    expect(h.sockets[0].protocols[1]).toBe('nxw_' + '2'.padStart(43, 'A'))
  })

  test("une perte de connexion alors que l'application est verrouillée : aucune demande avant le déverrouillage", async () => {
    const h = await harness()
    h.up()
    h.lock.locked = true // a REST call got its 401 and locked the app
    h.drop()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(h.signals).toHaveLength(1) // only the first connection's request
    expect(h.sockets).toHaveLength(1)
    await h.unlock()
    expect(h.signals).toHaveLength(2)
    expect(h.sockets).toHaveLength(2)
    // The unlock reset attempt (it was 1 after the drop): the next loss waits the first delay, not the second.
    h.drop()
    await vi.advanceTimersByTimeAsync(499)
    expect(h.sockets).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(h.sockets).toHaveLength(3)
  })

  test('au déverrouillage, une demande immédiate et les essais repartent de zéro', async () => {
    const h = await harness({ locked: true })
    expect(h.signals).toHaveLength(0)
    expect(h.sockets).toHaveLength(0)
    await h.unlock()
    expect(h.signals).toHaveLength(1)
    expect(h.sockets).toHaveLength(1)
    // the first fallback wait after the unlock is 500 ms with neutral random (the reset of attempt itself
    // is proven by the test above, where attempt is 1 before the unlock)
    h.drop()
    await vi.advanceTimersByTimeAsync(499)
    expect(h.sockets).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(h.sockets).toHaveLength(2)
  })

  test("un déverrouillage sans attente en cours ne demande rien", async () => {
    const h = await harness()
    await h.unlock()
    expect(h.signals).toHaveLength(1)
  })

  test("un 401 sans verrouillage (jeton changé entre-temps) : nouvelle demande après le repli, sans attendre le déverrouillage", async () => {
    let calls = 0
    const h = await harness({
      locked: false,
      ticket: (signal) => {
        calls += 1
        return calls === 1 ? Promise.reject(refused401()) : numberedTickets()(signal)
      },
    })
    expect(h.sockets).toHaveLength(0)
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    await vi.advanceTimersByTimeAsync(499)
    expect(h.signals).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(h.signals).toHaveLength(2)
    expect(h.sockets).toHaveLength(1)
  })

  test.each([
    ['erreur réseau', () => new TypeError('Failed to fetch')],
    ['délai dépassé', () => new DOMException('timeout', 'TimeoutError')],
    ['5xx', () => new ApiError(503, 'http_503', 'indisponible')],
    ['réponse mal formée', () => new Error('réponse de ticket inattendue')],
  ])('%s sur la demande : repli croissant, jamais de socket', async (_name, failure) => {
    const h = await harness({ ticket: () => Promise.reject(failure()) })
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    await vi.advanceTimersByTimeAsync(500)
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 2 })
    await vi.advanceTimersByTimeAsync(1000)
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 3 })
    expect(h.sockets).toHaveLength(0)
    expect(h.signals).toHaveLength(3)
  })

  test("stop() pendant la demande : signal annulé, aucune socket même si la promesse se résout ensuite", async () => {
    const pending = deferred()
    const h = await harness({ ticket: () => pending.promise })
    expect(h.signals[0].aborted).toBe(false)
    h.stop()
    expect(h.signals[0].aborted).toBe(true)
    pending.resolve('nxw_' + 'A'.repeat(43))
    await vi.advanceTimersByTimeAsync(60_000)
    expect(h.sockets).toHaveLength(0)
  })

  test("le délai de silence est armé avant la demande : une demande muette déclenche la perte, annule le signal et relance", async () => {
    let calls = 0
    const h = await harness({
      ticket: (signal) => {
        calls += 1
        return calls === 1 ? new Promise<string>(() => {}) : numberedTickets()(signal)
      },
    })
    await vi.advanceTimersByTimeAsync(SILENCE_MS - 1)
    expect(h.signals[0].aborted).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(h.signals[0].aborted).toBe(true)
    expect(h.states.at(-1)?.status).toBe('unknown') // 30 s already elapsed without a connection
    await vi.advanceTimersByTimeAsync(500)
    expect(h.signals).toHaveLength(2)
    expect(h.sockets).toHaveLength(1)
  })

  test("une réponse tardive après un silence de 45 s est ignorée", async () => {
    const late = deferred()
    let calls = 0
    const h = await harness({
      ticket: (signal) => {
        calls += 1
        return calls === 1 ? late.promise : numberedTickets()(signal)
      },
    })
    await vi.advanceTimersByTimeAsync(SILENCE_MS)
    late.resolve('nxw_' + 'L'.repeat(43))
    await vi.advanceTimersByTimeAsync(0)
    expect(h.sockets.some((socket) => socket.protocols[1] === 'nxw_' + 'L'.repeat(43))).toBe(false)
  })

  test('une fermeture 4401 suit le chemin de perte habituel, puis une nouvelle demande', async () => {
    const h = await harness()
    h.up()
    h.last().onclose?.({ code: 4401, reason: 'jeton révoqué' } as CloseEvent)
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    await vi.advanceTimersByTimeAsync(500)
    expect(h.signals).toHaveLength(2)
  })

  test('aucun appel console ne contient un ticket sur un cycle complet', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((name) => vi.spyOn(console, name))
    const h = await harness({ ticket: (signal) => (signal.aborted ? Promise.reject(new Error('x')) : numberedTickets()(signal)) })
    h.up()
    h.drop()
    await vi.advanceTimersByTimeAsync(500)
    h.stop()
    for (const spy of spies) {
      for (const call of spy.mock.calls) expect(JSON.stringify(call)).not.toContain('nxw_')
      spy.mockRestore()
    }
  })
})
