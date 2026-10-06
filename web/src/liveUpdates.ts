import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { connectLive, type LiveMessage, type LiveState } from './live'
import { tasksKey } from './tasks/queries'
import { nowKey } from './now/queries'

type InvalidateFilters = { queryKey: readonly unknown[]; exact?: boolean }
/** What a message asks to refetch: `'all'` absorbs every other request. */
type Invalidation = 'all' | InvalidateFilters

/** A burst of messages is flushed once, this long after its first message. */
export const LIVE_BATCH_MS = 50

/** Un message ne fait que dire quoi relire : les données passent toujours par l'API REST. */
function invalidationsFor(message: LiveMessage): Invalidation[] {
  switch (message.type) {
    case 'task_changed':
      return [{ queryKey: tasksKey, exact: true }, { queryKey: ['tasks', message.task] }, { queryKey: nowKey }]
    case 'event':
      return [
        { queryKey: ['events'] },
        ...(message.task ? [{ queryKey: ['tasks', message.task] }] : []),
        { queryKey: nowKey },
      ]
    case 'resync':
      return ['all']
    case 'hello':
      return message.reset ? ['all'] : []
    case 'ping':
      return []
  }
}

/** Immediate application of one message (no batching); the hook uses `createLiveBatcher`. */
export function applyLiveMessage(client: QueryClient, message: LiveMessage): void {
  for (const invalidation of invalidationsFor(message)) {
    if (invalidation === 'all') void client.invalidateQueries()
    else void client.invalidateQueries(invalidation)
  }
}

/**
 * Collects the invalidations of a burst and flushes them once, LIVE_BATCH_MS after the first
 * message (the window is not extended, so a steady stream still flushes every window).
 * While a mutation runs (a drag-move PATCH) the flush is postponed so a refetch cannot
 * overwrite the optimistic card; the pending set is kept. The first `hello` of a batcher
 * invalidates everything: the server starts from "now", so a change committed between the
 * first REST read and that `hello` would otherwise wait for the 10 s refetch.
 */
export function createLiveBatcher(client: QueryClient): {
  push: (message: LiveMessage) => void
  dispose: () => void
} {
  let seenHello = false
  let disposed = false
  let all = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const pending = new Map<string, InvalidateFilters>()

  const flush = () => {
    timer = undefined
    if (disposed) return
    if (client.isMutating() > 0) {
      timer = setTimeout(flush, LIVE_BATCH_MS)
      return
    }
    const wasAll = all
    const filters = [...pending.values()]
    all = false
    pending.clear()
    if (wasAll) void client.invalidateQueries()
    else for (const f of filters) void client.invalidateQueries(f)
  }

  return {
    push(message) {
      if (disposed) return
      const requests = invalidationsFor(message)
      if (message.type === 'hello' && !seenHello) requests.push('all')
      if (message.type === 'hello') seenHello = true
      if (requests.length === 0) return
      for (const request of requests) {
        if (request === 'all') all = true
        else pending.set(JSON.stringify(request), request)
      }
      timer ??= setTimeout(flush, LIVE_BATCH_MS)
    },
    dispose() {
      disposed = true
      clearTimeout(timer)
      timer = undefined
      pending.clear()
    },
  }
}

/** Connexion temps réel de l'application ; la relecture toutes les 10 s reste le filet. */
export function useLiveUpdates(): LiveState {
  const client = useQueryClient()
  const [state, setState] = useState<LiveState>({ status: 'connecting' })
  useEffect(() => {
    const batcher = createLiveBatcher(client) // per effect run: remounts start fresh
    const stop = connectLive({
      open: (url) => new WebSocket(url),
      onMessage: batcher.push,
      onState: setState,
    })
    return () => {
      stop()
      batcher.dispose()
    }
  }, [client])
  return state
}
