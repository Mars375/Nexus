import { QueryClient, QueryObserver } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import type { LiveMessage } from './live'
import { tasksKey } from './tasks/queries'
import { createLiveBatcher, LIVE_BATCH_MS, LIVE_MAX_DEFERRALS } from './liveUpdates'

const CURSOR = { history: 1, events: 1 }

function spyClient() {
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue(undefined)
  return { client, invalidate }
}

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

  describe('invalidations par type de message', () => {
    const run = (message: LiveMessage[]) => {
      const { client, invalidate } = spyClient()
      const batcher = createLiveBatcher(client)
      for (const m of message) batcher.push(m)
      vi.advanceTimersByTime(LIVE_BATCH_MS)
      return invalidate
    }

    test('une tâche changée relit la liste et le détail de cette tâche', () => {
      const invalidate = run([task('nx-task-3')])
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks'], exact: true })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks', 'nx-task-3'] })
    })

    test('un événement relit les événements et sa tâche', () => {
      const invalidate = run([{ type: 'event', event: 'nx-evt-9', task: 'nx-task-3', kind: 'done', cursor: CURSOR }])
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['events'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks', 'nx-task-3'] })
    })

    test('un événement answer (réponse ou décision de Loïc) relit Maintenant', () => {
      const invalidate = run([{ type: 'event', event: 'nx-evt-12', task: 'nx-task-3', kind: 'answer', cursor: CURSOR }])
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['now'] })
    })

    test('un événement sans tâche relit seulement les événements et Maintenant', () => {
      const invalidate = run([{ type: 'event', event: 'nx-evt-9', task: null, kind: 'unknown', cursor: CURSOR }])
      expect(invalidate).toHaveBeenCalledTimes(2)
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['events'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['now'] })
      expect(filters(invalidate).some((f) => f.includes('"tasks"'))).toBe(false)
    })

    test('resync ou reset relisent tout, en une seule relecture', () => {
      const invalidate = run([
        { type: 'resync', cursor: CURSOR },
        { type: 'hello', cursor: CURSOR, reset: true },
      ])
      expect(invalidate).toHaveBeenCalledTimes(1)
      expect(invalidate).toHaveBeenCalledWith()
    })

    test('ping ne relit rien', () => {
      const invalidate = run([{ type: 'ping', cursor: CURSOR }])
      expect(invalidate).not.toHaveBeenCalled()
    })
  })

  describe('pendant une première lecture (requête sans données)', () => {
    test('retarde la relecture, puis relit quand la première lecture a abouti', async () => {
      const client = new QueryClient()
      const resolvers: ((v: string) => void)[] = []
      const queryFn = vi.fn(() => new Promise<string>((resolve) => resolvers.push(resolve)))
      const observer = new QueryObserver(client, { queryKey: tasksKey, queryFn })
      const unsubscribe = observer.subscribe(() => {})
      expect(queryFn).toHaveBeenCalledTimes(1)

      const batcher = createLiveBatcher(client)
      batcher.push({ type: 'hello', cursor: CURSOR, reset: false }) // first hello => 'all'
      await vi.advanceTimersByTimeAsync(LIVE_BATCH_MS * 3)
      expect(queryFn).toHaveBeenCalledTimes(1) // flush postponed: nothing swallowed by the initial read

      resolvers[0]('old')
      await vi.advanceTimersByTimeAsync(LIVE_BATCH_MS)
      expect(queryFn).toHaveBeenCalledTimes(2) // invalidation applied on top of the settled read
      resolvers[1]('new')
      await vi.advanceTimersByTimeAsync(0)
      expect(observer.getCurrentResult().data).toBe('new')
      unsubscribe()
      batcher.dispose()
    })
  })

  describe('portée de la garde de première lecture', () => {
    const hold = (client: QueryClient, queryKey: readonly unknown[]) => {
      const observer = new QueryObserver(client, { queryKey, queryFn: () => new Promise<string>(() => {}) })
      return observer.subscribe(() => {})
    }

    test('une première lecture sans rapport ne retarde pas une invalidation ciblée', () => {
      const { client, invalidate } = spyClient()
      const unsubscribe = hold(client, ['nodes'])
      const batcher = createLiveBatcher(client)
      batcher.push(task('nx-task-1'))
      vi.advanceTimersByTime(LIVE_BATCH_MS)
      expect(count(invalidate, { queryKey: ['tasks', 'nx-task-1'] })).toBe(1)
      unsubscribe()
      batcher.dispose()
    })

    test('une première lecture concernée retarde la relecture ciblée, qui part dès qu\'elle a abouti', async () => {
      const client = new QueryClient()
      const invalidate = vi.spyOn(client, 'invalidateQueries') // pass-through: the real refetch runs
      const resolvers: ((v: string) => void)[] = []
      const queryFn = vi.fn(() => new Promise<string>((resolve) => resolvers.push(resolve)))
      const observer = new QueryObserver(client, { queryKey: ['tasks', 'nx-task-1'], queryFn })
      const unsubscribe = observer.subscribe(() => {})
      expect(queryFn).toHaveBeenCalledTimes(1)

      const batcher = createLiveBatcher(client)
      batcher.push(task('nx-task-1')) // targeted invalidation, no `hello` involved
      await vi.advanceTimersByTimeAsync(LIVE_BATCH_MS * 3)
      expect(invalidate).not.toHaveBeenCalled() // held while the matching first read is in flight

      resolvers[0]('old')
      await vi.advanceTimersByTimeAsync(LIVE_BATCH_MS)
      // The pending set survived the postponements: released exactly once, for the held key.
      expect(count(invalidate, { queryKey: ['tasks', 'nx-task-1'] })).toBe(1)
      expect(count(invalidate, { queryKey: ['tasks'], exact: true })).toBe(1)
      expect(queryFn).toHaveBeenCalledTimes(2) // the observer refetches on top of the settled read
      unsubscribe()
      batcher.dispose()
    })

    test('avec « tout » en attente, une première lecture sans rapport retarde', () => {
      const { client, invalidate } = spyClient()
      const unsubscribe = hold(client, ['nodes'])
      const batcher = createLiveBatcher(client)
      batcher.push({ type: 'resync', cursor: CURSOR })
      vi.advanceTimersByTime(LIVE_BATCH_MS * 3)
      expect(invalidate).not.toHaveBeenCalled()
      unsubscribe()
      batcher.dispose()
    })
  })

  describe('plafond de reports', () => {
    function holdMutation(client: QueryClient) {
      void client.getMutationCache().build(client, { mutationFn: () => new Promise<void>(() => {}) }).execute(undefined)
    }

    test('LIVE_MAX_DEFERRALS vaut 200', () => {
      expect(LIVE_MAX_DEFERRALS).toBe(200)
    })

    test('une mutation bloquée ne retarde pas indéfiniment : relecture au plafond', () => {
      const { client, invalidate } = spyClient()
      holdMutation(client)
      const batcher = createLiveBatcher(client)
      batcher.push(task('nx-task-1'))
      // First flush at 1 window, then LIVE_MAX_DEFERRALS postponements; the next flush runs.
      vi.advanceTimersByTime(LIVE_BATCH_MS * LIVE_MAX_DEFERRALS)
      expect(invalidate).not.toHaveBeenCalled()
      vi.advanceTimersByTime(LIVE_BATCH_MS)
      expect(count(invalidate, { queryKey: ['tasks', 'nx-task-1'] })).toBe(1)
      batcher.dispose()
    })

    test('le compteur repart de zéro après une relecture', () => {
      const { client, invalidate } = spyClient()
      holdMutation(client)
      const batcher = createLiveBatcher(client)
      batcher.push(task('nx-task-1'))
      vi.advanceTimersByTime(LIVE_BATCH_MS * (LIVE_MAX_DEFERRALS + 1))
      expect(count(invalidate, { queryKey: ['tasks', 'nx-task-1'] })).toBe(1)
      invalidate.mockClear()
      batcher.push(task('nx-task-2'))
      vi.advanceTimersByTime(LIVE_BATCH_MS * LIVE_MAX_DEFERRALS)
      expect(invalidate).not.toHaveBeenCalled() // fresh budget
      vi.advanceTimersByTime(LIVE_BATCH_MS)
      expect(count(invalidate, { queryKey: ['tasks', 'nx-task-2'] })).toBe(1)
      batcher.dispose()
    })
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
