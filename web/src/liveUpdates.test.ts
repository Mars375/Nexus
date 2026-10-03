import { QueryClient } from '@tanstack/react-query'
import { describe, expect, test, vi } from 'vitest'
import { applyLiveMessage } from './liveUpdates'

const CURSOR = { history: 1, events: 1 }

function spyClient() {
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue(undefined)
  return { client, invalidate }
}

describe('applyLiveMessage', () => {
  test('une tâche changée relit la liste et le détail de cette tâche', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'task_changed', task: 'nx-task-3', cursor: CURSOR })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks'], exact: true })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks', 'nx-task-3'] })
  })

  test('un événement relit les événements et sa tâche', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'event', event: 'nx-evt-9', task: 'nx-task-3', kind: 'done', cursor: CURSOR })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['events'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks', 'nx-task-3'] })
  })

  test('un événement sans tâche relit les événements et Maintenant', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'event', event: 'nx-evt-9', task: null, kind: 'unknown', cursor: CURSOR })
    expect(invalidate).toHaveBeenCalledTimes(2)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['events'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['now'] })
  })

  test('resync ou reset relisent tout', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'resync', cursor: CURSOR })
    applyLiveMessage(client, { type: 'hello', cursor: CURSOR, reset: true })
    expect(invalidate).toHaveBeenCalledTimes(2)
    expect(invalidate).toHaveBeenNthCalledWith(1)
    expect(invalidate).toHaveBeenNthCalledWith(2)
  })

  test('hello ordinaire et ping ne relisent rien', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'hello', cursor: CURSOR, reset: false })
    applyLiveMessage(client, { type: 'ping', cursor: CURSOR })
    expect(invalidate).not.toHaveBeenCalled()
  })

  test('un changement de tâche ou un événement relit aussi Maintenant', () => {
    const { client, invalidate } = spyClient()
    applyLiveMessage(client, { type: 'task_changed', task: 'nx-task-3', cursor: CURSOR })
    applyLiveMessage(client, { type: 'event', event: 'nx-evt-9', task: null, kind: 'question', cursor: CURSOR })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['now'] })
    expect(invalidate.mock.calls.filter(([f]) => JSON.stringify(f) === JSON.stringify({ queryKey: ['now'] }))).toHaveLength(2)
  })
})
