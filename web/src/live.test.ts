import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError } from './api'
import {
  connectLive,
  liveUrl,
  reconnectDelay,
  SILENCE_MS,
  UNKNOWN_AFTER_MS,
  type LiveMessage,
  type LiveSocket,
  type LiveState,
} from './live'

type Fake = LiveSocket & { url: string; protocols: string[]; closed: boolean }

type HarnessOptions = {
  ticket?: (signal: AbortSignal) => Promise<string>
  locked?: boolean
  /** The app becomes locked while the first ticket request is in flight (a REST 401 elsewhere). */
  lockOnTicket?: boolean
}

/** A fresh, distinct ticket per call, built at runtime. */
function numberedTickets() {
  let count = 0
  return (_signal: AbortSignal) => Promise.resolve('nxw_' + String(++count).padStart(43, 'A'))
}

async function harness(options: HarnessOptions = {}) {
  const sockets: Fake[] = []
  const states: LiveState[] = []
  const messages: LiveMessage[] = []
  const signals: AbortSignal[] = []
  const unlockListeners = new Set<() => void>()
  const lock = { locked: options.locked ?? false }
  const issue = options.ticket ?? numberedTickets()
  const stop = connectLive({
    ticket: (signal) => {
      signals.push(signal)
      if (options.lockOnTicket && signals.length === 1) lock.locked = true // first request only
      return issue(signal)
    },
    isLocked: () => lock.locked,
    onUnlock: (listener) => {
      unlockListeners.add(listener)
      return () => unlockListeners.delete(listener)
    },
    open: (url, protocols) => {
      const socket: Fake = {
        url,
        protocols,
        closed: false,
        onopen: null,
        onmessage: null,
        onclose: null,
        close() {
          this.closed = true
        },
      }
      sockets.push(socket)
      return socket
    },
    onMessage: (m) => messages.push(m),
    onState: (s) => states.push(s),
    random: () => 0.5, // aléa neutre : attente exacte
  })
  await vi.advanceTimersByTimeAsync(0) // the first ticket request settles
  const last = () => sockets[sockets.length - 1]
  const open = () => last().onopen?.(new Event('open'))
  const send = (data: unknown) =>
    last().onmessage?.({ data: typeof data === 'string' ? data : JSON.stringify(data) } as MessageEvent)
  const drop = () => last().onclose?.({} as CloseEvent)
  // Connexion établie : la socket s'ouvre ET le serveur parle (premier message valide).
  const up = () => {
    open()
    send({ type: 'hello', cursor: { history: 0, events: 0 }, reset: false })
  }
  const unlock = async () => {
    lock.locked = false
    for (const listener of [...unlockListeners]) listener()
    await vi.advanceTimersByTimeAsync(0)
  }
  return { sockets, states, messages, signals, lock, stop, last, open, send, drop, up, unlock }
}

const INSTANCE_A = '0123456789abcdef'
const INSTANCE_B = 'fedcba9876543210'
const HELLO = { type: 'hello', cursor: { history: 3, events: 4 }, reset: false }

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('reconnectDelay', () => {
  test('double à chaque essai à partir de 0,5 s', async () => {
    expect([1, 2, 3].map((n) => reconnectDelay(n, () => 0.5))).toEqual([500, 1000, 2000])
  })
  test('plafonne à 10 s', async () => {
    expect(reconnectDelay(12, () => 0.5)).toBe(10_000)
  })
  test('ajoute un aléa de ±20 %', async () => {
    expect(reconnectDelay(1, () => 0)).toBe(400)
    expect(reconnectDelay(1, () => 1)).toBe(600)
  })
})

describe('liveUrl', () => {
  test('sans curseur, part de maintenant', async () => {
    expect(liveUrl(null, null, { protocol: 'http:', host: 'localhost:5173' })).toBe('ws://localhost:5173/api/ws')
  })
  test('avec curseur, demande le rattrapage ; https donne wss', async () => {
    expect(liveUrl({ history: 3, events: 4 }, null, { protocol: 'https:', host: 'nexus.local' })).toBe(
      'wss://nexus.local/api/ws?history_after=3&events_after=4',
    )
  })
  test('avec une base configurée, ignore la page : ws/wss suit la base', async () => {
    const page = { protocol: 'http:', host: 'tauri.localhost' }
    expect(liveUrl(null, null, page, 'http://127.0.0.1:8765')).toBe('ws://127.0.0.1:8765/api/ws')
    expect(liveUrl({ history: 3, events: 4 }, null, page, 'https://nexus.local')).toBe(
      'wss://nexus.local/api/ws?history_after=3&events_after=4',
    )
  })
})

describe('liveUrl avec instance', () => {
  const page = { protocol: 'http:', host: 'localhost:5173' }
  test("avec curseur et instance, ajoute l'instance", async () => {
    expect(liveUrl({ history: 3, events: 4 }, INSTANCE_A, page)).toBe(
      `ws://localhost:5173/api/ws?history_after=3&events_after=4&instance=${INSTANCE_A}`,
    )
  })
  test("sans curseur, n'envoie jamais d'instance", async () => {
    expect(liveUrl(null, INSTANCE_A, page)).toBe('ws://localhost:5173/api/ws')
  })
})

describe('connectLive', () => {
  test('connexion : connecting, puis connected au premier message valide seulement', async () => {
    const h = await harness()
    expect(h.states).toEqual([{ status: 'connecting' }])
    h.open()
    expect(h.states).toEqual([{ status: 'connecting' }])
    h.send(HELLO)
    expect(h.states.at(-1)).toEqual({ status: 'connected' })
  })

  test('un message invalide ne rend pas connecté', async () => {
    const h = await harness()
    h.open()
    h.send({ type: 'ping', cursor: { history: 'abc', events: 4 } })
    h.send('pas du json')
    expect(h.states.some((s) => s.status === 'connected')).toBe(false)
  })

  test('un serveur qui accepte puis ferme sans parler n\'est jamais connecté', async () => {
    const h = await harness()
    h.open()
    h.drop()
    expect(h.states.map((s) => s.status)).toEqual(['connecting', 'reconnecting'])
    await vi.advanceTimersByTimeAsync(500)
    h.open()
    h.drop()
    expect(h.states.some((s) => s.status === 'connected')).toBe(false)
  })

  test("l'instance du dernier hello survit à plusieurs essais ratés d'affilée (redémarrage du serveur)", async () => {
    const h = await harness()
    h.open()
    h.send({ type: 'hello', cursor: { history: 3, events: 4 }, reset: false, instance: INSTANCE_A })
    h.drop()
    await vi.advanceTimersByTimeAsync(500)
    h.drop() // serveur arrêté : l'essai échoue sans hello
    await vi.advanceTimersByTimeAsync(1000)
    h.drop() // deuxième essai raté
    await vi.advanceTimersByTimeAsync(2000)
    expect(h.last().url).toContain(`history_after=3&events_after=4&instance=${INSTANCE_A}`)
  })

  test('une connexion qui ne s\'ouvre jamais est fermée après 45 s puis relancée', async () => {
    const h = await harness()
    await vi.advanceTimersByTimeAsync(SILENCE_MS - 1)
    expect(h.last().closed).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(h.sockets[0].closed).toBe(true)
    // 30 s sans connexion sont déjà passées : l'état est unknown, pas reconnecting.
    expect(h.states.at(-1)).toEqual({ status: 'unknown', attempt: 1 })
    await vi.advanceTimersByTimeAsync(500)
    expect(h.sockets).toHaveLength(2)
  })

  test('transmet les messages et ignore un message illisible', async () => {
    const h = await harness()
    h.open()
    h.send(HELLO)
    h.send('pas du json')
    expect(h.messages).toEqual([HELLO])
  })

  test('après une coupure, attend puis se reconnecte avec le dernier curseur', async () => {
    const h = await harness()
    h.open()
    h.send(HELLO)
    h.drop()
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    await vi.advanceTimersByTimeAsync(499)
    expect(h.sockets).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(h.sockets).toHaveLength(2)
    expect(h.last().url).toContain('history_after=3&events_after=4')
  })

  test('passe à unknown après 30 s sans connexion', async () => {
    const h = await harness()
    h.up()
    h.drop()
    await vi.advanceTimersByTimeAsync(UNKNOWN_AFTER_MS - 1)
    expect(h.states.at(-1)?.status).not.toBe('unknown')
    await vi.advanceTimersByTimeAsync(1)
    expect(h.states.at(-1)?.status).toBe('unknown')
  })

  test('unknown tient pendant les essais suivants', async () => {
    const h = await harness()
    h.up()
    h.drop()
    await vi.advanceTimersByTimeAsync(UNKNOWN_AFTER_MS)
    h.drop() // un nouvel essai échoue
    expect(h.states.at(-1)?.status).toBe('unknown')
  })

  test('sans connexion depuis le chargement, unknown compte depuis le chargement', async () => {
    const h = await harness()
    await vi.advanceTimersByTimeAsync(10_000)
    h.drop() // le premier essai échoue au bout de 10 s
    await vi.advanceTimersByTimeAsync(UNKNOWN_AFTER_MS - 10_000)
    expect(h.states.at(-1)?.status).toBe('unknown')
  })

  test('une connexion rétablie efface unknown', async () => {
    const h = await harness()
    await vi.advanceTimersByTimeAsync(UNKNOWN_AFTER_MS) // jamais connecté depuis le chargement
    expect(h.states.at(-1)?.status).toBe('unknown')
    h.open()
    expect(h.states.at(-1)?.status).toBe('unknown') // ouverte mais muette : pas encore rétablie
    h.send(HELLO)
    expect(h.states.at(-1)).toEqual({ status: 'connected' })
  })

  test('ferme une connexion restée muette 45 s', async () => {
    const h = await harness()
    h.open()
    await vi.advanceTimersByTimeAsync(SILENCE_MS - 1)
    expect(h.last().closed).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(h.last().closed).toBe(true)
  })

  test('un message repousse le délai de silence', async () => {
    const h = await harness()
    h.open()
    await vi.advanceTimersByTimeAsync(SILENCE_MS - 1)
    h.send({ type: 'ping', cursor: { history: 0, events: 0 } })
    await vi.advanceTimersByTimeAsync(SILENCE_MS - 1)
    expect(h.last().closed).toBe(false)
  })

  test('stop ferme la connexion et ne reconnecte plus', async () => {
    const h = await harness()
    h.open()
    h.stop()
    expect(h.last().closed).toBe(true)
    h.drop()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(h.sockets).toHaveLength(1)
  })

  test('ignore les messages avec curseur invalide', async () => {
    const h = await harness()
    h.open()
    h.send(HELLO)
    h.send(null)
    h.send({ type: 'hello' })
    h.send({ type: 'ping', cursor: { history: 'abc', events: 4 } })
    expect(h.messages).toEqual([HELLO])
    h.drop()
    await vi.advanceTimersByTimeAsync(500)
    expect(h.last().url).toContain('history_after=3&events_after=4') // curseur précédent conservé
  })

  test('message invalide ne réarme pas le silence', async () => {
    const h = await harness()
    h.open()
    h.send(HELLO)
    await vi.advanceTimersByTimeAsync(SILENCE_MS - 1)
    h.send({ type: 'ping', cursor: { history: 'abc', events: 4 } }) // message invalide
    await vi.advanceTimersByTimeAsync(1)
    expect(h.last().closed).toBe(true) // la socket s'est fermée, message invalide n'a pas réarmé
  })

  test('reset attempt sur le premier message valide, pas sur onopen', async () => {
    const h = await harness()
    h.open()
    h.drop() // premier essai échoue sans message
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    await vi.advanceTimersByTimeAsync(500) // attente pour tentative 1
    expect(h.sockets).toHaveLength(2)
    h.open() // socket 2 établie, mais pas de message → pas de reset
    h.drop() // socket 2 échoue sans message → attempt reste 1, devient 2
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 2 })
    await vi.advanceTimersByTimeAsync(999)
    expect(h.sockets).toHaveLength(2) // pas encore de troisième socket
    await vi.advanceTimersByTimeAsync(1)
    expect(h.sockets).toHaveLength(3) // attente 1000 ms pour tentative 2 (pas reset sur onopen)
  })

  test('un premier message valide remet les essais à zéro pour la coupure suivante', async () => {
    const h = await harness()
    h.open()
    h.drop() // essai 1
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    await vi.advanceTimersByTimeAsync(500)
    expect(h.sockets).toHaveLength(2)

    h.open()
    h.send(HELLO) // la connexion parle : le compteur repart de zéro
    expect(h.states.at(-1)).toEqual({ status: 'connected' })

    h.drop() // nouvelle coupure, indépendante de la première
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    await vi.advanceTimersByTimeAsync(499)
    expect(h.sockets).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(h.sockets).toHaveLength(3)
  })

  test('stop en attente de reconnexion ne crée pas de socket et n\'émet pas unknown', async () => {
    const h = await harness()
    h.up()
    h.drop()
    h.stop()
    await vi.advanceTimersByTimeAsync(UNKNOWN_AFTER_MS)
    const unknownStates = h.states.filter((s) => s.status === 'unknown')
    expect(unknownStates).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(h.sockets).toHaveLength(1)
  })

  test('silence ouvre une deuxième socket et l\'onclose tardive ne crée pas de troisième', async () => {
    const h = await harness()
    h.open()
    const firstSocket = h.last()
    await vi.advanceTimersByTimeAsync(SILENCE_MS)
    expect(firstSocket.closed).toBe(true)
    expect(h.sockets).toHaveLength(1) // socket fermée mais pas encore de tentative de reconnexion
    await vi.advanceTimersByTimeAsync(500) // attente du premier reconnect (attempt 1)
    expect(h.sockets).toHaveLength(2)
    // Simuler une onclose tardive de la première socket
    firstSocket.onclose?.({} as CloseEvent)
    await vi.advanceTimersByTimeAsync(SILENCE_MS - 1) // avant le délai de connexion de la deuxième socket
    expect(h.sockets).toHaveLength(2) // pas de troisième socket créée
  })

  test('un message tardif de la première socket après détachement ne remonte pas', async () => {
    const h = await harness()
    h.open()
    const firstSocket = h.last()
    await vi.advanceTimersByTimeAsync(SILENCE_MS)
    expect(firstSocket.closed).toBe(true)
    await vi.advanceTimersByTimeAsync(500)
    expect(h.sockets).toHaveLength(2)
    const secondSocket = h.last()
    h.open() // ouvre la deuxième socket
    // Simuler un message tardif de la première socket
    firstSocket.onmessage?.({ data: JSON.stringify({ type: 'ping', cursor: { history: 0, events: 0 } }) } as MessageEvent)
    expect(h.messages).toHaveLength(0) // le message tardif est ignoré
    // Vérifier que la deuxième socket fonctionne normalement
    secondSocket.onmessage?.({ data: JSON.stringify({ type: 'ping', cursor: { history: 0, events: 0 } }) } as MessageEvent)
    expect(h.messages).toHaveLength(1) // le message de la bonne socket est reçu
  })

  describe('validation par type de message (#25)', () => {
    const C = { history: 9, events: 9 }
    const invalid: [string, unknown][] = [
      ['hello sans reset', { type: 'hello', cursor: C }],
      ['hello avec reset non booléen', { type: 'hello', cursor: C, reset: 'true' }],
      ['task_changed sans task', { type: 'task_changed', cursor: C }],
      ['task_changed avec task vide', { type: 'task_changed', cursor: C, task: '' }],
      ['task_changed avec task numérique', { type: 'task_changed', cursor: C, task: 3 }],
      ['event sans event', { type: 'event', cursor: C, kind: 'done', task: null }],
      ['event avec event vide', { type: 'event', cursor: C, event: '', kind: 'done', task: null }],
      ['event sans kind', { type: 'event', cursor: C, event: 'e1', task: null }],
      ['event avec kind vide', { type: 'event', cursor: C, event: 'e1', kind: '', task: null }],
      ['event sans task (undefined)', { type: 'event', cursor: C, event: 'e1', kind: 'done' }],
      ['event avec task numérique', { type: 'event', cursor: C, event: 'e1', kind: 'done', task: 4 }],
      ['event avec task vide', { type: 'event', cursor: C, event: 'e1', kind: 'done', task: '' }],
      ['curseur au-delà de 12 chiffres (1e13)', { type: 'ping', cursor: { history: 1e13, events: 1 } }],
      ['curseur flottant 1e21', { type: 'ping', cursor: { history: 1, events: 1e21 } }],
      ['curseur 2**53 non sûr', { type: 'ping', cursor: { history: 2 ** 53, events: 1 } }],
    ]
    test.each(invalid)('%s : ignoré, curseur conservé, pas de connexion', async (_name, bad) => {
      const h = await harness()
      h.open()
      h.send(bad)
      expect(h.messages).toEqual([])
      expect(h.states.some((s) => s.status === 'connected')).toBe(false)
      h.send(HELLO)
      h.send(bad)
      expect(h.messages).toEqual([HELLO])
      h.drop()
      await vi.advanceTimersByTimeAsync(500)
      expect(h.last().url).toContain('history_after=3&events_after=4')
    })

    test('un curseur de 12 chiffres (999999999999) est accepté et rejoué à la reconnexion', async () => {
      const h = await harness()
      h.open()
      const big = { type: 'ping', cursor: { history: 999999999999, events: 0 } }
      h.send(big)
      expect(h.messages).toEqual([big])
      h.send({ type: 'ping', cursor: { history: 1e13, events: 0 } }) // refused: last good cursor kept
      h.drop()
      await vi.advanceTimersByTimeAsync(500)
      expect(h.last().url).toContain('history_after=999999999999&events_after=0')
    })

    test('les messages valides de chaque type passent', async () => {
      const h = await harness()
      h.open()
      const valid = [
        { type: 'hello', cursor: C, reset: true },
        { type: 'task_changed', cursor: C, task: 'nx-task-1' },
        { type: 'event', cursor: C, event: 'e1', kind: 'done', task: null },
        { type: 'event', cursor: C, event: 'e1', kind: 'done', task: 'nx-task-1' },
        { type: 'resync', cursor: C },
        { type: 'ping', cursor: C },
      ]
      for (const m of valid) h.send(m)
      expect(h.messages).toEqual(valid)
    })
  })
})

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
