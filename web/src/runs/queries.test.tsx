import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '@/api'
import { clearToken, markUnlocked } from '@/auth'
import type { Run } from '@/runsApi'
import { newClientKey, runsKey, useCancelRun, useDispatchRun, useExecutors, useRuns } from './queries'

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }))

const run: Run = {
  id: 'nx-run-1', task: 'nx-task-1', executor: 'codex', agent: 'codex', dispatched_by: 'loic',
  client_key: 'k', brief: 'b', workdir: null, model: null, external_ref: null, status: 'dispatched',
  native_status: null, created_at: '2026-11-05T10:00:00+01:00', ended_at: null,
  cancel_requested_at: null, version: 1, source: 'nexus.db', measured_at: '2026-11-05T10:00:01+01:00',
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

const reply = (status: number, body: unknown) =>
  vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(body), { status }))

beforeEach(() => {
  clearToken()
  markUnlocked()
  vi.mocked(toast.error).mockClear()
})
afterEach(() => vi.unstubAllGlobals())

test('la liste des runs d’une tâche se lit sous la clé de la tâche', async () => {
  const fetchMock = reply(200, [run])
  vi.stubGlobal('fetch', fetchMock)
  const { wrapper } = setup()
  const { result } = renderHook(() => useRuns('nx-task-1'), { wrapper })
  await waitFor(() => expect(result.current.data).toEqual([run]))
  expect(String(fetchMock.mock.calls[0][0])).toContain('/api/tasks/nx-task-1/runs')
  expect(runsKey('nx-task-1').slice(0, 2)).toEqual(['tasks', 'nx-task-1'])
})

test('les exécutants ne sont lus que dialogue ouvert', async () => {
  const fetchMock = reply(200, [])
  vi.stubGlobal('fetch', fetchMock)
  const { wrapper } = setup()
  const { rerender } = renderHook(({ on }) => useExecutors(on), { wrapper, initialProps: { on: false } })
  expect(fetchMock).not.toHaveBeenCalled()
  rerender({ on: true })
  await waitFor(() => expect(fetchMock).toHaveBeenCalled())
})

test('confier envoie la clé du clic ; renvoyée, la même clé donne la même requête', async () => {
  const fetchMock = reply(201, run)
  vi.stubGlobal('fetch', fetchMock)
  const { wrapper } = setup()
  const { result } = renderHook(() => useDispatchRun('nx-task-1'), { wrapper })
  const draft = { executor: 'codex' as const, agent: 'codex' as const, client_key: 'ui-k1', brief: 'Fais-le' }

  act(() => result.current.mutate(draft))
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  act(() => result.current.mutate(draft))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

  const bodies = fetchMock.mock.calls.map((c) => JSON.parse(String(c[1]?.body)))
  expect(bodies[0]).toEqual(draft)
  expect(bodies[1].client_key).toBe(bodies[0].client_key)
})

test('un refus 409 reste dans la mutation, sans toast, avec son code', async () => {
  vi.stubGlobal('fetch', reply(409, { detail: { code: 'executor_busy', message: 'Cet exécutant est occupé.' } }))
  const { wrapper } = setup()
  const { result } = renderHook(() => useDispatchRun('nx-task-1'), { wrapper })
  act(() => result.current.mutate({ executor: 'codex', agent: 'codex', client_key: 'k', brief: 'b' }))
  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(result.current.error).toBeInstanceOf(ApiError)
  expect((result.current.error as ApiError).code).toBe('executor_busy')
  expect(toast.error).not.toHaveBeenCalled()
})

test('annuler appelle la route d’annulation et le dit', async () => {
  const fetchMock = reply(200, { ...run, cancel_requested_at: '2026-11-05T10:05:00+01:00' })
  vi.stubGlobal('fetch', fetchMock)
  const { wrapper } = setup()
  const { result } = renderHook(() => useCancelRun('nx-task-1'), { wrapper })
  act(() => result.current.mutate('nx-run-1'))
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(String(fetchMock.mock.calls[0][0])).toContain('/api/runs/nx-run-1/cancel')
  expect(toast.success).toHaveBeenCalledWith('Annulation demandée')
})

test('chaque dialogue a sa propre clé, au format accepté par le serveur', () => {
  const a = newClientKey()
  const b = newClientKey()
  expect(a).not.toBe(b)
  expect(a).toMatch(/^[A-Za-z0-9._:-]{1,128}$/)
})

test('annuler relit toute la tâche : runs et historique', async () => {
  vi.stubGlobal('fetch', reply(200, run))
  const { client, wrapper } = setup()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const { result } = renderHook(() => useCancelRun('nx-task-1'), { wrapper })
  act(() => result.current.mutate('nx-run-1'))
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks', 'nx-task-1'] })
})
