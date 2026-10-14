/*
 * Real time (#5): a WebSocket connection to /api/ws, with reconnection and catch-up.
 * The WebSocket is injected (`open`) so the logic can be tested without a network. Messages only
 * carry references: the UI always rereads data through the REST API.
 * Each connection (and reconnection) first asks for a fresh single-use ticket (#57), offered as a
 * subprotocol next to `nexus.live.v1`; it is never kept, logged or put in the URL.
 */
import { ApiError, LIVE_PROTOCOL } from './api'
import { API_BASE } from './apiBase'

export type Cursor = { history: number; events: number }

export type LiveMessage =
  | { type: 'hello'; cursor: Cursor; reset: boolean; instance?: string }
  | { type: 'task_changed'; task: string; cursor: Cursor }
  | { type: 'event'; event: string; task: string | null; kind: string; cursor: Cursor }
  | { type: 'resync'; cursor: Cursor }
  | { type: 'ping'; cursor: Cursor }

export type LiveState =
  | { status: 'connecting' }
  | { status: 'connected' }
  | { status: 'reconnecting'; attempt: number }
  | { status: 'unknown'; attempt: number }

export type LiveSocket = {
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  close(): void
}

export const RECONNECT_MIN_MS = 500
export const RECONNECT_MAX_MS = 10_000
export const UNKNOWN_AFTER_MS = 30_000
export const SILENCE_MS = 45_000

export function reconnectDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(RECONNECT_MAX_MS, RECONNECT_MIN_MS * 2 ** (attempt - 1))
  return Math.round(base * (0.8 + 0.4 * random()))
}

export function liveUrl(
  cursor: Cursor | null,
  instance: string | null = null,
  location: { protocol: string; host: string } = window.location,
  base: string = API_BASE,
): string {
  // The instance only makes sense next to the cursor it vouches for (the server refuses it alone).
  const query = cursor
    ? `?history_after=${cursor.history}&events_after=${cursor.events}${instance ? `&instance=${instance}` : ''}`
    : ''
  if (base) return `${base.replace(/^http/, 'ws')}/api/ws${query}`
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/api/ws${query}`
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const isNonEmptyString = (value: unknown): value is string => typeof value === 'string' && value !== ''

/** Server cursors are at most 12 ASCII digits (server/src/nexus/live.py). */
const MAX_CURSOR = 999_999_999_999

const isCursorValue = (value: unknown): boolean =>
  Number.isSafeInteger(value) && (value as number) >= 0 && (value as number) <= MAX_CURSOR

/** Server instance id: 16 lowercase hex digits (server/src/nexus/live.py). */
const isInstance = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{16}$/.test(value)

const isCursor = (value: unknown): value is Cursor =>
  isRecord(value) && isCursorValue(value.history) && isCursorValue(value.events)

export function connectLive(options: {
  /** A fresh single-use ticket; cancelled through the signal when the request is not needed. */
  ticket: (signal: AbortSignal) => Promise<string>
  /** Whether the app is locked (the server answered 401); read after a refused ticket request. */
  isLocked: () => boolean
  /** Calls the listener when the app is unlocked; returns the unsubscribe function. */
  onUnlock: (listener: () => void) => () => void
  open: (url: string, protocols: string[]) => LiveSocket
  onMessage: (message: LiveMessage) => void
  onState: (state: LiveState) => void
  random?: () => number
}): () => void {
  let cursor: Cursor | null = null
  let instance: string | null = null // that of the last valid hello; absent for an old server
  let socket: LiveSocket | null = null
  let attempt = 0
  let stopped = false
  let connected = false // une connexion est établie et pas encore perdue
  let unknown = false // plus de 30 s sans connexion : l'état reste tel jusqu'à la reconnexion
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined
  let silenceTimer: ReturnType<typeof setTimeout> | undefined
  let unknownTimer: ReturnType<typeof setTimeout> | undefined
  let pendingTicket: AbortController | undefined // the ticket request in flight
  let waitingUnlock = false // locked: no new attempt until the app is unlocked

  const armUnknown = () => {
    clearTimeout(unknownTimer)
    unknownTimer = setTimeout(() => {
      unknown = true
      options.onState({ status: 'unknown', attempt })
    }, UNKNOWN_AFTER_MS)
  }
  const armSilence = () => {
    clearTimeout(silenceTimer)
    silenceTimer = setTimeout(() => {
      // Mark socket as stale before handling loss (detach it so late onclose is ignored)
      const staleSocket = socket
      socket = null
      staleSocket?.close()
      pendingTicket?.abort() // a ticket request that never answers counts as a failed handshake
      pendingTicket = undefined
      handleLoss()
    }, SILENCE_MS)
  }

  // Factored loss handling: clear timers, update state, schedule reconnect
  const handleLoss = () => {
    if (stopped) return
    clearTimeout(silenceTimer)
    if (connected) {
      // Perte d'une connexion établie : les 30 s comptent d'ici. Sans connexion depuis le
      // chargement, elles comptent déjà depuis le chargement (on ne réarme pas).
      connected = false
      armUnknown()
    }
    attempt += 1
    options.onState(unknown ? { status: 'unknown', attempt } : { status: 'reconnecting', attempt })
    reconnectTimer = setTimeout(() => void connect(), reconnectDelay(attempt, options.random))
  }

  // Validate a pushed message per type before any state is touched (review checklist §2).
  const isValidMessage = (data: unknown): data is LiveMessage => {
    if (!isRecord(data)) return false
    if (!isCursor(data.cursor)) return false
    switch (data.type) {
      case 'hello':
        return typeof data.reset === 'boolean' && (data.instance === undefined || isInstance(data.instance))
      case 'task_changed':
        return isNonEmptyString(data.task)
      case 'event':
        return (
          isNonEmptyString(data.event) &&
          isNonEmptyString(data.kind) &&
          (data.task === null || isNonEmptyString(data.task))
        )
      case 'resync':
      case 'ping':
        return true
      default:
        return false
    }
  }

  const connect = async () => {
    if (options.isLocked()) {
      // Locked (the server refused our token): a ticket request would only repeat the 401.
      // Wait for the unlock.
      waitingUnlock = true
      return
    }
    // A handshake that never completes (ticket request included) is treated as silence (45 s),
    // then retried.
    armSilence()
    pendingTicket?.abort()
    const request = new AbortController()
    pendingTicket = request
    let ticket: string
    try {
      ticket = await options.ticket(request.signal)
    } catch (error) {
      if (stopped || pendingTicket !== request) return // stopped or superseded: nothing to do
      pendingTicket = undefined
      if (error instanceof ApiError && error.status === 401 && options.isLocked()) {
        // The server locked the app: retrying would only repeat the 401. Wait for the unlock.
        clearTimeout(silenceTimer)
        waitingUnlock = true
        return
      }
      handleLoss() // network error, timeout, 5xx, malformed answer, or a 401 that did not lock
      return
    }
    if (stopped || pendingTicket !== request) return // a late answer is ignored
    pendingTicket = undefined
    const current = options.open(liveUrl(cursor, instance), [LIVE_PROTOCOL, ticket])
    socket = current
    armSilence()
    current.onopen = () => {
      if (stopped || socket !== current) return
      armSilence() // « connecté » attend le premier message valide (ADR-005) : ici, on surveille seulement
    }
    current.onmessage = (event) => {
      if (stopped || socket !== current) return
      let message: LiveMessage
      try {
        message = JSON.parse(String(event.data)) as LiveMessage
      } catch {
        return // message illisible : ignoré, la relecture régulière reste le filet
      }
      if (!isValidMessage(message)) return // message invalide : ignoré, curseur précédent conservé
      // Premier message valide de la connexion : elle est établie (on ne se fie pas à onopen seul,
      // un serveur peut accepter puis fermer sans rien dire).
      attempt = 0
      cursor = message.cursor
      if (message.type === 'hello') instance = message.instance ?? null
      armSilence() // Only re-arm on valid messages
      if (!connected) {
        connected = true
        unknown = false
        clearTimeout(unknownTimer)
        options.onState({ status: 'connected' })
      }
      options.onMessage(message)
    }
    current.onclose = () => {
      if (stopped || socket !== current) return
      handleLoss()
    }
  }

  const unsubscribe = options.onUnlock(() => {
    if (stopped || !waitingUnlock) return
    waitingUnlock = false
    attempt = 0
    clearTimeout(reconnectTimer)
    void connect()
  })

  options.onState({ status: 'connecting' })
  armUnknown() // aucune connexion depuis le chargement de la page
  void connect()

  return () => {
    stopped = true
    unsubscribe()
    pendingTicket?.abort()
    clearTimeout(reconnectTimer)
    clearTimeout(silenceTimer)
    clearTimeout(unknownTimer)
    socket?.close()
  }
}
