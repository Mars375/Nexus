import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import {
  liveUrl,
  reconnectDelay,
  SILENCE_MS,
  UNKNOWN_AFTER_MS,
} from './live'
import { harness, INSTANCE_A, HELLO } from './liveSupport'

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
