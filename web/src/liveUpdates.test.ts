import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import type { LiveMessage } from './live'
import { applyLiveMessage, createLiveBatcher, LIVE_BATCH_MS } from './liveUpdates'

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

describe('createLiveBatcher', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const task = (id: string): LiveMessage => ({ type: 'task_changed', task: id, cursor: CURSOR })
  const filters = (invalidate: ReturnType<typeof spyClient>['invalidate']) =>
    invalidate.mock.calls.map(([f]) => JSON.stringify(f))
  const count = (invalidate: ReturnType<typeof spyClient>['invalidate'], f?: object) =>
    filters(invalidate).filter((x) => x === JSON.stringify(f)).length

  test('LIVE_BATCH_MS vaut 50 ms', () => {
    expect(LIVE_BATCH_MS).toBe(50)
  })

  test('rien n\'est relu avant la fin de la fenêtre', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    batcher.push(task('nx-task-1'))
    vi.advanceTimersByTime(LIVE_BATCH_MS - 1)
    expect(invalidate).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(invalidate).toHaveBeenCalled()
  })

  test('une rafale sur 5 tâches relit chaque clé une seule fois', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    for (const id of ['nx-task-1', 'nx-task-2', 'nx-task-3', 'nx-task-4', 'nx-task-5']) batcher.push(task(id))
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    expect(invalidate).toHaveBeenCalledTimes(7) // liste + Maintenant + 5 détails
    expect(count(invalidate, { queryKey: ['tasks'], exact: true })).toBe(1)
    expect(count(invalidate, { queryKey: ['now'] })).toBe(1)
    for (const id of ['nx-task-1', 'nx-task-2', 'nx-task-3', 'nx-task-4', 'nx-task-5']) {
      expect(count(invalidate, { queryKey: ['tasks', id] })).toBe(1)
    }
  })

  test('deux changements de la même tâche relisent [tasks, id] une fois', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    batcher.push(task('nx-task-1'))
    batcher.push({ type: 'event', event: 'e1', task: 'nx-task-1', kind: 'done', cursor: CURSOR })
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    expect(count(invalidate, { queryKey: ['tasks', 'nx-task-1'] })).toBe(1)
    expect(count(invalidate, { queryKey: ['events'] })).toBe(1)
  })

  test('un resync dans la rafale absorbe tout : une seule relecture globale', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    batcher.push(task('nx-task-1'))
    batcher.push({ type: 'resync', cursor: CURSOR })
    batcher.push(task('nx-task-2'))
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    expect(invalidate).toHaveBeenCalledTimes(1)
    expect(invalidate).toHaveBeenCalledWith()
  })

  test('la fenêtre n\'est pas prolongée par les messages suivants', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    batcher.push(task('nx-task-1'))
    vi.advanceTimersByTime(LIVE_BATCH_MS - 10)
    batcher.push(task('nx-task-2'))
    vi.advanceTimersByTime(10)
    expect(count(invalidate, { queryKey: ['tasks', 'nx-task-1'] })).toBe(1)
    expect(count(invalidate, { queryKey: ['tasks', 'nx-task-2'] })).toBe(1)
  })

  test('un message après la relecture ouvre une nouvelle fenêtre', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    batcher.push(task('nx-task-1'))
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    invalidate.mockClear()
    batcher.push(task('nx-task-1'))
    expect(invalidate).not.toHaveBeenCalled()
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    expect(count(invalidate, { queryKey: ['tasks', 'nx-task-1'] })).toBe(1)
  })

  test('ping ne programme rien', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    batcher.push({ type: 'ping', cursor: CURSOR })
    expect(vi.getTimerCount()).toBe(0)
    vi.advanceTimersByTime(1000)
    expect(invalidate).not.toHaveBeenCalled()
  })

  test('le premier hello relit tout même sans reset', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    batcher.push({ type: 'hello', cursor: CURSOR, reset: false })
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    expect(invalidate).toHaveBeenCalledTimes(1)
    expect(invalidate).toHaveBeenCalledWith()
  })

  test('un hello de reconnexion sans reset ne relit rien, avec reset il relit tout', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    batcher.push({ type: 'hello', cursor: CURSOR, reset: false })
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    invalidate.mockClear()
    batcher.push({ type: 'hello', cursor: CURSOR, reset: false })
    expect(vi.getTimerCount()).toBe(0)
    vi.advanceTimersByTime(1000)
    expect(invalidate).not.toHaveBeenCalled()
    batcher.push({ type: 'hello', cursor: CURSOR, reset: true })
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    expect(invalidate).toHaveBeenCalledTimes(1)
    expect(invalidate).toHaveBeenCalledWith()
  })

  test('le « premier hello » est propre à chaque batcher', () => {
    const a = spyClient()
    const b = spyClient()
    createLiveBatcher(a.client).push({ type: 'hello', cursor: CURSOR, reset: false })
    createLiveBatcher(b.client).push({ type: 'hello', cursor: CURSOR, reset: false })
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    expect(a.invalidate).toHaveBeenCalledTimes(1)
    expect(b.invalidate).toHaveBeenCalledTimes(1)
  })

  test('dispose annule la relecture en attente', () => {
    const { client, invalidate } = spyClient()
    const batcher = createLiveBatcher(client)
    batcher.push(task('nx-task-1'))
    batcher.dispose()
    expect(vi.getTimerCount()).toBe(0)
    vi.advanceTimersByTime(1000)
    expect(invalidate).not.toHaveBeenCalled()
    batcher.push(task('nx-task-2')) // après dispose : ignoré
    vi.advanceTimersByTime(1000)
    expect(invalidate).not.toHaveBeenCalled()
  })

  describe('pendant un déplacement (mutation en cours)', () => {
    function startMutation(client: QueryClient) {
      let finish!: () => void
      const gate = new Promise<void>((resolve) => (finish = resolve))
      void client.getMutationCache().build(client, { mutationFn: () => gate }).execute(undefined)
      return finish
    }

    test('ne relit pas tant qu\'une mutation tourne, puis relit sans rien perdre', async () => {
      const { client, invalidate } = spyClient()
      const finish = startMutation(client)
      expect(client.isMutating()).toBe(1)
      const batcher = createLiveBatcher(client)
      batcher.push(task('nx-task-1'))
      vi.advanceTimersByTime(LIVE_BATCH_MS * 5)
      expect(invalidate).not.toHaveBeenCalled()
      batcher.push(task('nx-task-2')) // le lot en attente continue de s'enrichir
      vi.advanceTimersByTime(LIVE_BATCH_MS * 5)
      expect(invalidate).not.toHaveBeenCalled()
      finish()
      await vi.advanceTimersByTimeAsync(LIVE_BATCH_MS)
      expect(client.isMutating()).toBe(0)
      expect(count(invalidate, { queryKey: ['tasks', 'nx-task-1'] })).toBe(1)
      expect(count(invalidate, { queryKey: ['tasks', 'nx-task-2'] })).toBe(1)
    })

    test('dispose arrête aussi la relance en attente de fin de mutation', () => {
      const { client, invalidate } = spyClient()
      const finish = startMutation(client)
      const baseline = vi.getTimerCount() // timers owned by react-query itself
      const batcher = createLiveBatcher(client)
      batcher.push(task('nx-task-1'))
      vi.advanceTimersByTime(LIVE_BATCH_MS * 2)
      expect(vi.getTimerCount()).toBe(baseline + 1) // the re-armed flush
      batcher.dispose()
      expect(vi.getTimerCount()).toBe(baseline)
      finish()
      vi.advanceTimersByTime(1000)
      expect(invalidate).not.toHaveBeenCalled()
    })
  })
})
