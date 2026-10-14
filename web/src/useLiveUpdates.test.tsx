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
  protocols: string | string[] | undefined
  constructor(url: string, protocols?: string | string[]) {
    this.url = url
    this.protocols = protocols
    FakeWebSocket.instances.push(this)
  }
  close() {}
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent)
  }
}

const CURSOR = { history: 1, events: 1 }
const TICKET = 'nxw_' + 'T'.repeat(43) // built at runtime

describe('useLiveUpdates (câblage)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ ticket: TICKET, protocol: 'nexus.live.v1', expires_in: 30 }), { status: 200 })),
    )
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  async function setup() {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue(undefined)
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const hook = renderHook(() => useLiveUpdates(), { wrapper })
    // The socket opens once the ticket request has been answered.
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    return { invalidate, hook, socket: FakeWebSocket.instances[0] }
  }

  test('regroupe une rafale : chaque clé relue une seule fois après 50 ms', async () => {
    const { invalidate, socket } = await setup()
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

  test('le démontage libère le lot : rien n\'est relu après, aucun timer en attente', async () => {
    const { invalidate, hook, socket } = await setup()
    socket.emit({ type: 'task_changed', task: 'nx-task-1', cursor: CURSOR })
    hook.unmount()
    expect(vi.getTimerCount()).toBe(0)
    vi.advanceTimersByTime(LIVE_BATCH_MS * 10)
    expect(invalidate).not.toHaveBeenCalled()
  })

  test('ouvre la socket avec le sous-protocole nexus.live.v1 et le ticket, jamais dans l\'URL', async () => {
    const { socket } = await setup()
    expect(socket.protocols).toEqual(['nexus.live.v1', TICKET])
    expect(socket.url).not.toContain('nxw_')
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toContain('/api/ws-ticket')
    expect(init?.method).toBe('POST')
  })
})
