/*
 * Temps réel (#5) : une connexion WebSocket vers /api/ws, avec reconnexion et rattrapage.
 * Le WebSocket est injecté (`open`) pour que la logique se teste sans réseau. Les messages
 * ne portent que des références : l'interface relit toujours les données par l'API REST.
 */
import { API_BASE } from './apiBase'

export type Cursor = { history: number; events: number }

export type LiveMessage =
  | { type: 'hello'; cursor: Cursor; reset: boolean }
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
  location: { protocol: string; host: string } = window.location,
  base: string = API_BASE,
): string {
  const query = cursor ? `?history_after=${cursor.history}&events_after=${cursor.events}` : ''
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

const isCursor = (value: unknown): value is Cursor =>
  isRecord(value) && isCursorValue(value.history) && isCursorValue(value.events)

export function connectLive(options: {
  open: (url: string) => LiveSocket
  onMessage: (message: LiveMessage) => void
  onState: (state: LiveState) => void
  random?: () => number
}): () => void {
  let cursor: Cursor | null = null
  let socket: LiveSocket | null = null
  let attempt = 0
  let stopped = false
  let connected = false // une connexion est établie et pas encore perdue
  let unknown = false // plus de 30 s sans connexion : l'état reste tel jusqu'à la reconnexion
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined
  let silenceTimer: ReturnType<typeof setTimeout> | undefined
  let unknownTimer: ReturnType<typeof setTimeout> | undefined

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
    reconnectTimer = setTimeout(connect, reconnectDelay(attempt, options.random))
  }

  // Validate a pushed message per type before any state is touched (review checklist §2).
  const isValidMessage = (data: unknown): data is LiveMessage => {
    if (!isRecord(data)) return false
    if (!isCursor(data.cursor)) return false
    switch (data.type) {
      case 'hello':
        return typeof data.reset === 'boolean'
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

  const connect = () => {
    const current = options.open(liveUrl(cursor))
    socket = current
    // Une poignée de main qui n'aboutit jamais est traitée comme un silence (45 s), puis relancée.
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

  options.onState({ status: 'connecting' })
  armUnknown() // aucune connexion depuis le chargement de la page
  connect()

  return () => {
    stopped = true
    clearTimeout(reconnectTimer)
    clearTimeout(silenceTimer)
    clearTimeout(unknownTimer)
    socket?.close()
  }
}
