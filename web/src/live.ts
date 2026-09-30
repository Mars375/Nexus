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
    silenceTimer = setTimeout(() => socket?.close(), SILENCE_MS) // la fermeture relance la reconnexion
  }

  const connect = () => {
    const current = options.open(liveUrl(cursor))
    socket = current
    current.onopen = () => {
      if (stopped) return
      attempt = 0
      connected = true
      unknown = false
      clearTimeout(unknownTimer)
      armSilence()
      options.onState({ status: 'connected' })
    }
    current.onmessage = (event) => {
      if (stopped) return
      armSilence()
      let message: LiveMessage
      try {
        message = JSON.parse(String(event.data)) as LiveMessage
      } catch {
        return // message illisible : ignoré, la relecture régulière reste le filet
      }
      cursor = message.cursor
      options.onMessage(message)
    }
    current.onclose = () => {
      if (stopped || socket !== current) return
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
