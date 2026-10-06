import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { LIVE_BATCH_MS, useLiveUpdates } from './liveUpdates'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: ((e: Event) => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  onclose: ((e: CloseEvent) => void) | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
  close() {}
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent)
  }
}

const CURSOR = { history: 1, events: 1 }

describe('useLiveUpdates (câblage)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  function setup() {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue(undefined)
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const hook = renderHook(() => useLiveUpdates(), { wrapper })
    return { invalidate, hook, socket: FakeWebSocket.instances[0] }
  }

  test('regroupe une rafale : chaque clé relue une seule fois après 50 ms', () => {
    const { invalidate, socket } = setup()
    socket.emit({ type: 'hello', cursor: CURSOR, reset: false })
    vi.advanceTimersByTime(LIVE_BATCH_MS) // first hello flush (everything)
    invalidate.mockClear()
    for (let i = 0; i < 3; i++) socket.emit({ type: 'task_changed', task: 'nx-task-1', cursor: CURSOR })
    expect(invalidate).not.toHaveBeenCalled()
    vi.advanceTimersByTime(LIVE_BATCH_MS)
    const keys = invalidate.mock.calls.map(([f]) => JSON.stringify(f))
    expect(keys).toHaveLength(3) // list + detail + now, each once
    expect(new Set(keys).size).toBe(3)
  })

  test('le démontage libère le lot : rien n\'est relu après, aucun timer en attente', () => {
    const { invalidate, hook, socket } = setup()
    socket.emit({ type: 'task_changed', task: 'nx-task-1', cursor: CURSOR })
    hook.unmount()
    expect(vi.getTimerCount()).toBe(0)
    vi.advanceTimersByTime(LIVE_BATCH_MS * 10)
    expect(invalidate).not.toHaveBeenCalled()
  })
})
