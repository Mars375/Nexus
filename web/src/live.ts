/*
 * Temps réel (#5) : une connexion WebSocket vers /api/ws, avec reconnexion et rattrapage.
 * Le WebSocket est injecté (`open`) pour que la logique se teste sans réseau. Les messages
 * ne portent que des références : l'interface relit toujours les données par l'API REST.
 */
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
): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  const query = cursor ? `?history_after=${cursor.history}&events_after=${cursor.events}` : ''
  return `${scheme}://${location.host}/api/ws${query}`
}

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

  // Validate message has correct type, valid cursor with non-negative integers
  const isValidMessage = (data: unknown): data is LiveMessage => {
    if (!data || typeof data !== 'object') return false
    const msg = data as Record<string, unknown>
    const type = msg.type
    if (!['hello', 'task_changed', 'event', 'resync', 'ping'].includes(type as string)) return false
    const cursor = msg.cursor
    if (!cursor || typeof cursor !== 'object') return false
    const cursorObj = cursor as Record<string, unknown>
    const history = cursorObj.history
    const events = cursorObj.events
    return (
      Number.isInteger(history) && (history as number) >= 0 &&
      Number.isInteger(events) && (events as number) >= 0
    )
  }

  const connect = () => {
    const current = options.open(liveUrl(cursor))
    socket = current
    current.onopen = () => {
      if (stopped || socket !== current) return
      connected = true
      unknown = false
      clearTimeout(unknownTimer)
      armSilence()
      options.onState({ status: 'connected' })
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
      // First valid message of this connection: reset attempt counter
      attempt = 0
      cursor = message.cursor
      armSilence() // Only re-arm on valid messages
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
