import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError, fetchHealth, liveApi, LIVE_PROTOCOL, request, retryQuery, tasksApi } from './api'
import { clearToken, getAuthState, getToken, markUnlocked, setToken } from './auth'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

test("un contrôle sans réponse échoue au bout du délai au lieu d'attendre indéfiniment", async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))
        }),
    ),
  )

  await expect(fetchHealth(undefined, 20)).rejects.toThrow()
})

function hangingFetch() {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))
      }),
  )
}

test("une requête de tâches sans réponse échoue au bout du délai au lieu d'attendre indéfiniment", async () => {
  vi.stubGlobal('fetch', hangingFetch())

  await expect(request('/api/tasks', undefined, 20)).rejects.toThrow()
})

test("l'annulation demandée par TanStack Query est transmise à la requête", async () => {
  vi.stubGlobal('fetch', hangingFetch())
  const controller = new AbortController()

  const pending = tasksApi.list(controller.signal)
  controller.abort()

  await expect(pending).rejects.toThrow()
})

test("avec VITE_NEXUS_API_URL, les requêtes REST et le contrôle de santé visent l'API configurée", async () => {
  vi.stubEnv('VITE_NEXUS_API_URL', 'http://127.0.0.1:8765/')
  vi.resetModules()
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url)
      return new Response('[]', { status: 200 })
    }),
  )
  const api = await import('./api')

  await api.tasksApi.list()
  await api.fetchHealth()

  expect(calls).toEqual(['http://127.0.0.1:8765/api/tasks', 'http://127.0.0.1:8765/api/health'])
  vi.unstubAllEnvs()
  vi.resetModules()
})

// --- Jeton d'acteur (ADR-020, D4) -------------------------------------------------------------

describe('jeton porteur', () => {
  const TOKEN = 'nxt_' + 'A'.repeat(43)
  const OTHER = 'nxt_' + 'B'.repeat(43)

  const refuse = (code: string, status = 401) =>
    vi.fn(async (..._args: [string, RequestInit?]) =>
      new Response(JSON.stringify({ detail: { code, message: 'refus' } }), { status, headers: { 'content-type': 'application/json' } }),
    )
  const ok = () => vi.fn(async (..._args: [string, RequestInit?]) => new Response('[]', { status: 200 }))
  const headersOf = (fetchMock: ReturnType<typeof ok>) => new Headers(fetchMock.mock.calls[0][1]?.headers)

  beforeEach(() => {
    clearToken()
    markUnlocked()
  })

  test("sans jeton, aucun en-tête Authorization n'est envoyé et l'application n'est pas verrouillée", async () => {
    const fetchMock = ok()
    vi.stubGlobal('fetch', fetchMock)
    await tasksApi.list()
    expect(headersOf(fetchMock).has('Authorization')).toBe(false)
    expect(getAuthState().locked).toBe(false)
  })

  test('avec un jeton, request() envoie Authorization: Bearer', async () => {
    setToken(TOKEN)
    const fetchMock = ok()
    vi.stubGlobal('fetch', fetchMock)
    await tasksApi.list()
    expect(headersOf(fetchMock).get('Authorization')).toBe(`Bearer ${TOKEN}`)
  })

  test("l'en-tête s'ajoute à ceux qui existent : Content-Type d'un corps, en-têtes de l'appelant", async () => {
    setToken(TOKEN)
    const fetchMock = ok()
    vi.stubGlobal('fetch', fetchMock)
    await request('/api/tasks', { method: 'POST', body: '{}', headers: { 'X-Test': '1' } })
    const headers = headersOf(fetchMock)
    expect(headers.get('Authorization')).toBe(`Bearer ${TOKEN}`)
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.get('X-Test')).toBe('1')
  })

  test("le jeton n'est jamais envoyé hors de l'API", async () => {
    setToken(TOKEN)
    const fetchMock = ok()
    vi.stubGlobal('fetch', fetchMock)
    await request('/autre/chemin')
    await request('//evil.example/api/tasks')
    for (const call of fetchMock.mock.calls) expect(new Headers(call[1]?.headers).has('Authorization')).toBe(false)
  })

  test('le contrôle de santé reste anonyme', async () => {
    setToken(TOKEN)
    const fetchMock = ok()
    vi.stubGlobal('fetch', fetchMock)
    await fetchHealth()
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has('Authorization')).toBe(false)
  })

  test.each(['auth_required', 'invalid_token'])('un 401 %s oublie le jeton et verrouille', async (code) => {
    setToken(TOKEN)
    vi.stubGlobal('fetch', refuse(code))
    await expect(tasksApi.list()).rejects.toMatchObject({ status: 401, code })
    expect(getToken()).toBeNull()
    expect(getAuthState()).toMatchObject({ locked: true, lockReason: code, hasToken: false })
  })

  test("un 401 sans code connu verrouille mais garde le jeton (il ne vient peut-être pas de Nexus)", async () => {
    setToken(TOKEN)
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })))
    await expect(tasksApi.list()).rejects.toMatchObject({ status: 401, code: 'http_401' })
    expect(getToken()).toBe(TOKEN)
    expect(getAuthState()).toMatchObject({ locked: true, hasToken: true })
  })

  test.each([403, 409, 500])('un %i ne touche ni au jeton ni au verrou', async (status) => {
    setToken(TOKEN)
    vi.stubGlobal('fetch', refuse('human_only', status))
    await expect(tasksApi.list()).rejects.toMatchObject({ status })
    expect(getToken()).toBe(TOKEN)
    expect(getAuthState().locked).toBe(false)
  })

  test("un 401 tardif d'un ancien jeton n'efface pas celui que Loïc vient d'enregistrer", async () => {
    setToken(TOKEN)
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    vi.stubGlobal('fetch', vi.fn(async () => {
      await gate
      return new Response(JSON.stringify({ detail: { code: 'invalid_token', message: 'x' } }), { status: 401 })
    }))
    const pending = tasksApi.list()
    setToken(OTHER) // saisi pendant que la requête est en vol
    release()
    await expect(pending).rejects.toMatchObject({ status: 401 })
    expect(getToken()).toBe(OTHER)
    expect(getAuthState().locked).toBe(false)
  })

  test("le jeton n'apparaît pas dans le message d'une erreur", async () => {
    setToken(TOKEN)
    vi.stubGlobal('fetch', refuse('invalid_token'))
    const error = await tasksApi.list().catch((e: Error) => e)
    expect(String((error as Error).message)).not.toContain(TOKEN)
  })
})

test("TanStack ne réessaie pas après un 401, mais garde ses trois essais ailleurs", () => {
  expect(retryQuery(0, new ApiError(401, 'invalid_token', 'x'))).toBe(false)
  expect(retryQuery(0, new ApiError(500, 'http_500', 'x'))).toBe(true)
  expect(retryQuery(2, new Error('réseau'))).toBe(true)
  expect(retryQuery(3, new Error('réseau'))).toBe(false)
})

test('joindre une preuve envoie la liste à la route dédiée, sans acteur dans le corps', async () => {
  const fetchMock = vi.fn(async () => Response.json({ id: 'nx-task-1' }))
  vi.stubGlobal('fetch', fetchMock)

  await tasksApi.attachEvidence('nx-task-1', ['commit:abc'])

  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  expect(url).toMatch(/\/api\/tasks\/nx-task-1\/evidence$/)
  expect(init.method).toBe('POST')
  expect(JSON.parse(init.body as string)).toEqual({ evidence: ['commit:abc'] })
})

// --- Ticket WebSocket (#57) --------------------------------------------------------------------

describe('liveApi.ticket', () => {
  const TOKEN = 'nxt_' + 'A'.repeat(43)
  const TICKET = 'nxw_' + 'T'.repeat(43)
  const answer = (body: unknown, status = 200) =>
    vi.fn(async (..._args: [string, RequestInit?]) =>
      new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }),
    )
  const valid = { ticket: TICKET, protocol: LIVE_PROTOCOL, expires_in: 30 }

  beforeEach(() => {
    clearToken()
    markUnlocked()
    setToken(TOKEN)
  })
  afterEach(() => {
    clearToken()
    markUnlocked()
  })

  test('POST /api/ws-ticket avec le jeton stocké, et rend la chaîne du ticket', async () => {
    const fetchMock = answer(valid)
    vi.stubGlobal('fetch', fetchMock)
    await expect(liveApi.ticket(new AbortController().signal)).resolves.toBe(TICKET)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/ws-ticket')
    expect(init?.method).toBe('POST')
    expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${TOKEN}`)
  })

  test.each([
    ['préfixe nxt_', { ...valid, ticket: 'nxt_' + 'T'.repeat(43) }],
    ['42 caractères', { ...valid, ticket: 'nxw_' + 'T'.repeat(42) }],
    ['44 caractères', { ...valid, ticket: 'nxw_' + 'T'.repeat(44) }],
    ['protocole autre', { ...valid, protocol: 'nexus.live.v2' }],
    ['ticket absent', { protocol: LIVE_PROTOCOL, expires_in: 30 }],
    ['ticket non texte', { ...valid, ticket: 42 }],
    ['corps non objet', ['nxw_' + 'T'.repeat(43)]],
    ['corps nul', null],
  ])('une réponse mal formée (%s) est rejetée sans rien recopier', async (_name, body) => {
    vi.stubGlobal('fetch', answer(body))
    const error = await liveApi.ticket(new AbortController().signal).then(
      () => null,
      (e: unknown) => e,
    )
    expect(error).toBeInstanceOf(Error)
    expect(error).not.toBeInstanceOf(ApiError)
    expect(String((error as Error).message)).not.toContain('nxw_')
    expect(String((error as Error).message)).not.toContain('nxt_')
    expect(getAuthState().locked).toBe(false)
  })

  test('un 401 invalid_token passe par le chemin habituel : jeton oublié, application verrouillée', async () => {
    vi.stubGlobal('fetch', answer({ detail: { code: 'invalid_token', message: 'refus' } }, 401))
    await expect(liveApi.ticket(new AbortController().signal)).rejects.toMatchObject({ status: 401, code: 'invalid_token' })
    expect(getToken()).toBeNull()
    expect(getAuthState()).toMatchObject({ locked: true, lockReason: 'invalid_token' })
  })

  test('le signal passé annule la requête', async () => {
    vi.stubGlobal('fetch', hangingFetch())
    const controller = new AbortController()
    const pending = liveApi.ticket(controller.signal)
    controller.abort()
    await expect(pending).rejects.toThrow()
  })
})
