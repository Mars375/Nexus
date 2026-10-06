import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
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

type Fake = LiveSocket & { url: string; closed: boolean }

function harness() {
  const sockets: Fake[] = []
  const states: LiveState[] = []
  const messages: LiveMessage[] = []
  const stop = connectLive({
    open: (url) => {
      const socket: Fake = {
        url,
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
  return { sockets, states, messages, stop, last, open, send, drop, up }
}

const INSTANCE_A = '0123456789abcdef'
const INSTANCE_B = 'fedcba9876543210'
const HELLO = { type: 'hello', cursor: { history: 3, events: 4 }, reset: false }

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('reconnectDelay', () => {
  test('double à chaque essai à partir de 0,5 s', () => {
    expect([1, 2, 3].map((n) => reconnectDelay(n, () => 0.5))).toEqual([500, 1000, 2000])
  })
  test('plafonne à 10 s', () => {
    expect(reconnectDelay(12, () => 0.5)).toBe(10_000)
  })
  test('ajoute un aléa de ±20 %', () => {
    expect(reconnectDelay(1, () => 0)).toBe(400)
    expect(reconnectDelay(1, () => 1)).toBe(600)
  })
})

describe('liveUrl', () => {
  test('sans curseur, part de maintenant', () => {
    expect(liveUrl(null, null, { protocol: 'http:', host: 'localhost:5173' })).toBe('ws://localhost:5173/api/ws')
  })
  test('avec curseur, demande le rattrapage ; https donne wss', () => {
    expect(liveUrl({ history: 3, events: 4 }, null, { protocol: 'https:', host: 'nexus.local' })).toBe(
      'wss://nexus.local/api/ws?history_after=3&events_after=4',
    )
  })
  test('avec une base configurée, ignore la page : ws/wss suit la base', () => {
    const page = { protocol: 'http:', host: 'tauri.localhost' }
    expect(liveUrl(null, null, page, 'http://127.0.0.1:8765')).toBe('ws://127.0.0.1:8765/api/ws')
    expect(liveUrl({ history: 3, events: 4 }, null, page, 'https://nexus.local')).toBe(
      'wss://nexus.local/api/ws?history_after=3&events_after=4',
    )
  })
})

describe('liveUrl avec instance', () => {
  const page = { protocol: 'http:', host: 'localhost:5173' }
  test("avec curseur et instance, ajoute l'instance", () => {
    expect(liveUrl({ history: 3, events: 4 }, INSTANCE_A, page)).toBe(
      `ws://localhost:5173/api/ws?history_after=3&events_after=4&instance=${INSTANCE_A}`,
    )
  })
  test("sans curseur, n'envoie jamais d'instance", () => {
    expect(liveUrl(null, INSTANCE_A, page)).toBe('ws://localhost:5173/api/ws')
  })
})

describe('connectLive', () => {
  test('connexion : connecting, puis connected au premier message valide seulement', () => {
    const h = harness()
    expect(h.states).toEqual([{ status: 'connecting' }])
    h.open()
    expect(h.states).toEqual([{ status: 'connecting' }])
    h.send(HELLO)
    expect(h.states.at(-1)).toEqual({ status: 'connected' })
  })

  test('un message invalide ne rend pas connecté', () => {
    const h = harness()
    h.open()
    h.send({ type: 'ping', cursor: { history: 'abc', events: 4 } })
    h.send('pas du json')
    expect(h.states.some((s) => s.status === 'connected')).toBe(false)
  })

  test('un serveur qui accepte puis ferme sans parler n\'est jamais connecté', () => {
    const h = harness()
    h.open()
    h.drop()
    expect(h.states.map((s) => s.status)).toEqual(['connecting', 'reconnecting'])
    vi.advanceTimersByTime(500)
    h.open()
    h.drop()
    expect(h.states.some((s) => s.status === 'connected')).toBe(false)
  })

  test("l'instance du dernier hello survit à plusieurs essais ratés d'affilée (redémarrage du serveur)", () => {
    const h = harness()
    h.open()
    h.send({ type: 'hello', cursor: { history: 3, events: 4 }, reset: false, instance: INSTANCE_A })
    h.drop()
    vi.advanceTimersByTime(500)
    h.drop() // serveur arrêté : l'essai échoue sans hello
    vi.advanceTimersByTime(1000)
    h.drop() // deuxième essai raté
    vi.advanceTimersByTime(2000)
    expect(h.last().url).toContain(`history_after=3&events_after=4&instance=${INSTANCE_A}`)
  })

  test('une connexion qui ne s\'ouvre jamais est fermée après 45 s puis relancée', () => {
    const h = harness()
    vi.advanceTimersByTime(SILENCE_MS - 1)
    expect(h.last().closed).toBe(false)
    vi.advanceTimersByTime(1)
    expect(h.sockets[0].closed).toBe(true)
    // 30 s sans connexion sont déjà passées : l'état est unknown, pas reconnecting.
    expect(h.states.at(-1)).toEqual({ status: 'unknown', attempt: 1 })
    vi.advanceTimersByTime(500)
    expect(h.sockets).toHaveLength(2)
  })

  test('transmet les messages et ignore un message illisible', () => {
    const h = harness()
    h.open()
    h.send(HELLO)
    h.send('pas du json')
    expect(h.messages).toEqual([HELLO])
  })

  test('après une coupure, attend puis se reconnecte avec le dernier curseur', () => {
    const h = harness()
    h.open()
    h.send(HELLO)
    h.drop()
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    vi.advanceTimersByTime(499)
    expect(h.sockets).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(h.sockets).toHaveLength(2)
    expect(h.last().url).toContain('history_after=3&events_after=4')
  })

  test('passe à unknown après 30 s sans connexion', () => {
    const h = harness()
    h.up()
    h.drop()
    vi.advanceTimersByTime(UNKNOWN_AFTER_MS - 1)
    expect(h.states.at(-1)?.status).not.toBe('unknown')
    vi.advanceTimersByTime(1)
    expect(h.states.at(-1)?.status).toBe('unknown')
  })

  test('unknown tient pendant les essais suivants', () => {
    const h = harness()
    h.up()
    h.drop()
    vi.advanceTimersByTime(UNKNOWN_AFTER_MS)
    h.drop() // un nouvel essai échoue
    expect(h.states.at(-1)?.status).toBe('unknown')
  })

  test('sans connexion depuis le chargement, unknown compte depuis le chargement', () => {
    const h = harness()
    vi.advanceTimersByTime(10_000)
    h.drop() // le premier essai échoue au bout de 10 s
    vi.advanceTimersByTime(UNKNOWN_AFTER_MS - 10_000)
    expect(h.states.at(-1)?.status).toBe('unknown')
  })

  test('une connexion rétablie efface unknown', () => {
    const h = harness()
    vi.advanceTimersByTime(UNKNOWN_AFTER_MS) // jamais connecté depuis le chargement
    expect(h.states.at(-1)?.status).toBe('unknown')
    h.open()
    expect(h.states.at(-1)?.status).toBe('unknown') // ouverte mais muette : pas encore rétablie
    h.send(HELLO)
    expect(h.states.at(-1)).toEqual({ status: 'connected' })
  })

  test('ferme une connexion restée muette 45 s', () => {
    const h = harness()
    h.open()
    vi.advanceTimersByTime(SILENCE_MS - 1)
    expect(h.last().closed).toBe(false)
    vi.advanceTimersByTime(1)
    expect(h.last().closed).toBe(true)
  })

  test('un message repousse le délai de silence', () => {
    const h = harness()
    h.open()
    vi.advanceTimersByTime(SILENCE_MS - 1)
    h.send({ type: 'ping', cursor: { history: 0, events: 0 } })
    vi.advanceTimersByTime(SILENCE_MS - 1)
    expect(h.last().closed).toBe(false)
  })

  test('stop ferme la connexion et ne reconnecte plus', () => {
    const h = harness()
    h.open()
    h.stop()
    expect(h.last().closed).toBe(true)
    h.drop()
    vi.advanceTimersByTime(60_000)
    expect(h.sockets).toHaveLength(1)
  })

  test('ignore les messages avec curseur invalide', () => {
    const h = harness()
    h.open()
    h.send(HELLO)
    h.send(null)
    h.send({ type: 'hello' })
    h.send({ type: 'ping', cursor: { history: 'abc', events: 4 } })
    expect(h.messages).toEqual([HELLO])
    h.drop()
    vi.advanceTimersByTime(500)
    expect(h.last().url).toContain('history_after=3&events_after=4') // curseur précédent conservé
  })

  test('message invalide ne réarme pas le silence', () => {
    const h = harness()
    h.open()
    h.send(HELLO)
    vi.advanceTimersByTime(SILENCE_MS - 1)
    h.send({ type: 'ping', cursor: { history: 'abc', events: 4 } }) // message invalide
    vi.advanceTimersByTime(1)
    expect(h.last().closed).toBe(true) // la socket s'est fermée, message invalide n'a pas réarmé
  })

  test('reset attempt sur le premier message valide, pas sur onopen', () => {
    const h = harness()
    h.open()
    h.drop() // premier essai échoue sans message
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    vi.advanceTimersByTime(500) // attente pour tentative 1
    expect(h.sockets).toHaveLength(2)
    h.open() // socket 2 établie, mais pas de message → pas de reset
    h.drop() // socket 2 échoue sans message → attempt reste 1, devient 2
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 2 })
    vi.advanceTimersByTime(999)
    expect(h.sockets).toHaveLength(2) // pas encore de troisième socket
    vi.advanceTimersByTime(1)
    expect(h.sockets).toHaveLength(3) // attente 1000 ms pour tentative 2 (pas reset sur onopen)
  })

  test('un premier message valide remet les essais à zéro pour la coupure suivante', () => {
    const h = harness()
    h.open()
    h.drop() // essai 1
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    vi.advanceTimersByTime(500)
    expect(h.sockets).toHaveLength(2)

    h.open()
    h.send(HELLO) // la connexion parle : le compteur repart de zéro
    expect(h.states.at(-1)).toEqual({ status: 'connected' })

    h.drop() // nouvelle coupure, indépendante de la première
    expect(h.states.at(-1)).toEqual({ status: 'reconnecting', attempt: 1 })
    vi.advanceTimersByTime(499)
    expect(h.sockets).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(h.sockets).toHaveLength(3)
  })

  test('stop en attente de reconnexion ne crée pas de socket et n\'émet pas unknown', () => {
    const h = harness()
    h.up()
    h.drop()
    h.stop()
    vi.advanceTimersByTime(UNKNOWN_AFTER_MS)
    const unknownStates = h.states.filter((s) => s.status === 'unknown')
    expect(unknownStates).toHaveLength(0)
    vi.advanceTimersByTime(60_000)
    expect(h.sockets).toHaveLength(1)
  })

  test('silence ouvre une deuxième socket et l\'onclose tardive ne crée pas de troisième', () => {
    const h = harness()
    h.open()
    const firstSocket = h.last()
    vi.advanceTimersByTime(SILENCE_MS)
    expect(firstSocket.closed).toBe(true)
    expect(h.sockets).toHaveLength(1) // socket fermée mais pas encore de tentative de reconnexion
    vi.advanceTimersByTime(500) // attente du premier reconnect (attempt 1)
    expect(h.sockets).toHaveLength(2)
    // Simuler une onclose tardive de la première socket
    firstSocket.onclose?.({} as CloseEvent)
    vi.advanceTimersByTime(SILENCE_MS - 1) // avant le délai de connexion de la deuxième socket
    expect(h.sockets).toHaveLength(2) // pas de troisième socket créée
  })

  test('un message tardif de la première socket après détachement ne remonte pas', () => {
    const h = harness()
    h.open()
    const firstSocket = h.last()
    vi.advanceTimersByTime(SILENCE_MS)
    expect(firstSocket.closed).toBe(true)
    vi.advanceTimersByTime(500)
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
    test.each(invalid)('%s : ignoré, curseur conservé, pas de connexion', (_name, bad) => {
      const h = harness()
      h.open()
      h.send(bad)
      expect(h.messages).toEqual([])
      expect(h.states.some((s) => s.status === 'connected')).toBe(false)
      h.send(HELLO)
      h.send(bad)
      expect(h.messages).toEqual([HELLO])
      h.drop()
      vi.advanceTimersByTime(500)
      expect(h.last().url).toContain('history_after=3&events_after=4')
    })

    test('un curseur de 12 chiffres (999999999999) est accepté et rejoué à la reconnexion', () => {
      const h = harness()
      h.open()
      const big = { type: 'ping', cursor: { history: 999999999999, events: 0 } }
      h.send(big)
      expect(h.messages).toEqual([big])
      h.send({ type: 'ping', cursor: { history: 1e13, events: 0 } }) // refused: last good cursor kept
      h.drop()
      vi.advanceTimersByTime(500)
      expect(h.last().url).toContain('history_after=999999999999&events_after=0')
    })

    test('les messages valides de chaque type passent', () => {
      const h = harness()
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
      open: (url) => {
        urls.push(url)
        return { onopen: null, onmessage: null, onclose: null, close() {} }
      },
      onMessage: () => {},
      onState: () => {},
    })
    stop()
    expect(urls).toEqual(['ws://127.0.0.1:8765/api/ws'])
  })
})

describe('instance du serveur', () => {
  const hello = (instance?: unknown) => ({ ...HELLO, ...(instance === undefined ? {} : { instance }) })
  const reconnect = (h: ReturnType<typeof harness>) => {
    h.drop()
    vi.advanceTimersByTime(500)
    return h.last().url
  }

  test("la reconnexion envoie le dernier curseur ET l'instance du dernier hello", () => {
    const h = harness()
    h.open()
    h.send(hello(INSTANCE_A))
    expect(reconnect(h)).toContain(`history_after=3&events_after=4&instance=${INSTANCE_A}`)
  })

  test('un second hello avec une autre instance remplace la précédente', () => {
    const h = harness()
    h.open()
    h.send(hello(INSTANCE_A))
    h.send(hello(INSTANCE_B))
    const url = reconnect(h)
    expect(url).toContain(`instance=${INSTANCE_B}`)
    expect(url).not.toContain(INSTANCE_A)
  })

  test.each([123, '', 'ABCDEF0123456789', '0123456789abcdef0', '0123456789abcde', null])(
    'un hello avec instance %j est ignoré : curseur conservé, pas connecté',
    (bad) => {
      const h = harness()
      h.open()
      h.send({ ...HELLO, cursor: { history: 1, events: 1 }, instance: bad })
      expect(h.states.some((s) => s.status === 'connected')).toBe(false)
      expect(h.messages).toEqual([])
      expect(reconnect(h)).toBe('ws://localhost:3000/api/ws')
    },
  )

  test('un hello invalide après un hello valide garde le curseur et l\'instance précédents', () => {
    const h = harness()
    h.open()
    h.send(hello(INSTANCE_A))
    h.send({ ...HELLO, cursor: { history: 9, events: 9 }, instance: 'X' })
    expect(reconnect(h)).toContain(`history_after=3&events_after=4&instance=${INSTANCE_A}`)
  })

  test("un hello sans instance (ancien serveur) est accepté et la reconnexion n'en envoie pas", () => {
    const h = harness()
    h.open()
    h.send(hello(INSTANCE_A))
    h.send(hello())
    expect(h.states.at(-1)).toEqual({ status: 'connected' })
    const url = reconnect(h)
    expect(url).toContain('history_after=3&events_after=4')
    expect(url).not.toContain('instance')
  })
})
