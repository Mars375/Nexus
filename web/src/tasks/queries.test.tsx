import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { clearToken, getAuthState, markUnlocked, setToken } from '@/auth'
import { useAddComment, useAttachEvidence, useCreateTask, useLink, useMoveTask, useUpdateTask } from './queries'

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }))

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
)

function answer(status: number, code: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ detail: { code, message: 'refus simulé' } }), { status })),
  )
}

beforeEach(() => {
  clearToken()
  markUnlocked()
  vi.mocked(toast.error).mockClear()
})
afterEach(() => vi.unstubAllGlobals())

const draft = { title: 't', objective: 'o', status: 'backlog' as const, next_action: null, lead_agent: null, priority: 'normal' as const, due_at: null, expected_evidence: null }

test.each([
  ['création', () => useCreateTask(), (m: ReturnType<typeof useCreateTask>) => m.mutate(draft)],
  ['modification', () => useUpdateTask(), (m: ReturnType<typeof useUpdateTask>) => m.mutate({ id: 'nx-task-1', changes: { title: 'x' } })],
  ['déplacement', () => useMoveTask(), (m: ReturnType<typeof useMoveTask>) => m.mutate({ id: 'nx-task-1', change: { status: 'todo' } })],
  ['commentaire', () => useAddComment('nx-task-1'), (m: ReturnType<typeof useAddComment>) => m.mutate('salut')],
  ['lien', () => useLink('nx-task-1'), (m: ReturnType<typeof useLink>) => m.mutate({ other: 'nx-task-2' })],
  ['preuve', () => useAttachEvidence('nx-task-1'), (m: ReturnType<typeof useAttachEvidence>) => m.mutate(['commit:abc'])],
] as const)('%s : un 401 n’affiche pas de toast (l’écran verrouillé parle)', async (_name, hook, run) => {
  answer(401, 'invalid_token')
  const { result } = renderHook(hook as () => never, { wrapper })
  act(() => (run as (m: unknown) => void)(result.current))
  await waitFor(() => expect((result.current as { isError: boolean }).isError).toBe(true))
  expect(toast.error).not.toHaveBeenCalled()
})

test('un autre refus garde son toast', async () => {
  answer(422, 'invalid')
  const { result } = renderHook(() => useCreateTask(), { wrapper })
  act(() => result.current.mutate(draft))
  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(toast.error).toHaveBeenCalledWith('refus simulé')
})

test('un 401 qui ne verrouille pas (jeton changé entre-temps) garde son toast', async () => {
  const older = 'nxt_' + 'A'.repeat(43)
  const newer = 'nxt_' + 'B'.repeat(43)
  setToken(older)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      setToken(newer) // another tab saved a new token while the request was in flight
      return new Response(JSON.stringify({ detail: { code: 'invalid_token', message: 'refus simulé' } }), { status: 401 })
    }),
  )
  const { result } = renderHook(() => useUpdateTask(), { wrapper })
  act(() => result.current.mutate({ id: 'nx-task-1', changes: { title: 'x' } }))
  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(getAuthState().locked).toBe(false)
  expect(toast.error).toHaveBeenCalledWith('refus simulé')
})
