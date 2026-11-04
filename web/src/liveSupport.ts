/*
 * Shared harness for the live connection test files split by theme (#39): a fake socket, the
 * `connectLive` wiring with fake timers, and the instance ids. Kept out of the specs so each file
 * stays about its own subject.
 */
import { vi } from 'vitest'
import {
  connectLive,
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
export function numberedTickets() {
  let count = 0
  return (_signal: AbortSignal) => Promise.resolve('nxw_' + String(++count).padStart(43, 'A'))
}

export async function harness(options: HarnessOptions = {}) {
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

export const INSTANCE_A = '0123456789abcdef'
export const INSTANCE_B = 'fedcba9876543210'
export const HELLO = { type: 'hello', cursor: { history: 3, events: 4 }, reset: false }
