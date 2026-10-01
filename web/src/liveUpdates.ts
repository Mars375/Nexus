import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { connectLive, type LiveMessage, type LiveState } from './live'
import { tasksKey } from './tasks/queries'
import { nowKey } from './now/queries'

/** Un message ne fait que dire quoi relire : les données passent toujours par l'API REST. */
export function applyLiveMessage(client: QueryClient, message: LiveMessage): void {
  switch (message.type) {
    case 'task_changed':
      void client.invalidateQueries({ queryKey: tasksKey, exact: true })
      void client.invalidateQueries({ queryKey: ['tasks', message.task] })
      void client.invalidateQueries({ queryKey: nowKey })
      return
    case 'event':
      void client.invalidateQueries({ queryKey: ['events'] })
      if (message.task) void client.invalidateQueries({ queryKey: ['tasks', message.task] })
      void client.invalidateQueries({ queryKey: nowKey })
      return
    case 'resync':
      void client.invalidateQueries()
      return
    case 'hello':
      if (message.reset) void client.invalidateQueries()
      return
    case 'ping':
      return
  }
}

/** Connexion temps réel de l'application ; la relecture toutes les 10 s reste le filet. */
export function useLiveUpdates(): LiveState {
  const client = useQueryClient()
  const [state, setState] = useState<LiveState>({ status: 'connecting' })
  useEffect(
    () =>
      connectLive({
        open: (url) => new WebSocket(url),
        onMessage: (message) => applyLiveMessage(client, message),
        onState: setState,
      }),
    [client],
  )
  return state
}
