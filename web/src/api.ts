// Toute donnée passe par l'API FastAPI — jamais d'accès direct propre au navigateur (ADR-017).

import { apiUrl } from './apiBase'
import { clearToken, getToken, markLocked } from './auth'

export type Health = {
  version: string
  db: { status: 'ok' | 'unknown'; source: string; measured_at: string }
  backup: { last_at: string | null; count: number; source: string; measured_at: string }
}

export type Status = 'backlog' | 'todo' | 'in_progress' | 'blocked' | 'review' | 'done' | 'dropped'
export type Priority = 'low' | 'normal' | 'high' | 'critical'
export type Role = 'main' | 'auxiliary'
export type Actor =
  | 'loic'
  | 'helios'
  | 'mnema'
  | 'aether'
  | 'artemis'
  | 'claude'
  | 'codex'
  | 'orca'
  | 'hermes'

export type Task = {
  id: string
  title: string
  objective: string
  status: Status
  human_owner: Actor
  lead_agent: Actor | null
  collaborators: Actor[]
  next_action: string | null
  due_at: string | null
  follow_up_at: string | null
  block_cause: string | null
  block_plan: string | null
  drop_reason: string | null
  expected_evidence: string | null
  evidence: string[]
  priority: Priority
  operation_role: Role | null
  origin: string | null
  context: string[]
  depends_on: string[]
  created_by: Actor
  created_at: string
  updated_at: string
  source: string
  measured_at: string
}

export type TaskDraft = {
  title: string
  objective: string
  status?: 'backlog' | 'todo'
  lead_agent?: Actor | null
  collaborators?: Actor[]
  next_action?: string | null
  due_at?: string | null
  follow_up_at?: string | null
  expected_evidence?: string | null
  priority?: Priority
}

export type TaskChanges = Partial<
  Pick<
    Task,
    | 'title'
    | 'objective'
    | 'lead_agent'
    | 'collaborators'
    | 'next_action'
    | 'due_at'
    | 'follow_up_at'
    | 'expected_evidence'
    | 'priority'
    | 'operation_role'
  >
>

export type StatusChange = {
  status: Status
  reason?: string
  block_cause?: string
  block_plan?: string
  follow_up_at?: string
  evidence?: string[]
  next_action?: string
  role?: Role
}

export type Comment = {
  id: number
  task: string
  author: Actor
  body: string
  at: string
  source: string
  measured_at: string
}

export type HistoryEntry = {
  id: number
  task: string
  actor: Actor
  at: string
  action: string
  changes: Record<string, unknown>
  source: string
  measured_at: string
}

/** Refus lisible par Loïc : `code` stable côté serveur, `message` en français. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** Au-delà, une requête sans réponse échoue : jamais de chargement infini (ADR-005). */
export const REQUEST_TIMEOUT_MS = 10_000

/** Codes of a 401 after which the stored token is useless: Nexus refused it (ADR-020, D8). */
const TOKEN_REFUSED = ['auth_required', 'invalid_token']

/** The token goes to the Nexus API only, never to another address (ADR-020, D4). */
const isApiPath = (path: string): boolean => path.startsWith('/api/')

export async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const timeout = AbortSignal.timeout(timeoutMs)
  const headers = new Headers(init?.headers)
  if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const sent = isApiPath(path) && !headers.has('Authorization') ? getToken() : null
  if (sent) headers.set('Authorization', `Bearer ${sent}`)
  const res = await fetch(apiUrl(path), {
    ...init,
    signal: init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout,
    headers,
  })
  if (res.ok) return res.status === 204 ? (undefined as T) : res.json()
  let code = `http_${res.status}`
  let message = `Le serveur a répondu ${res.status}.`
  try {
    const body = await res.json()
    const detail = body?.detail
    if (detail?.code) {
      code = detail.code
      message = detail.message
    } else if (Array.isArray(detail)) {
      code = 'invalid'
      message = detail.map((d: { msg?: string }) => d.msg).join(' ; ')
    }
  } catch {
    // corps absent ou illisible : on garde le message générique
  }
  if (res.status === 401 && getToken() === sent) {
    // The server drives the lock screen. A late answer to an older token is ignored: the token
    // Loïc just entered must not be forgotten because of it.
    if (TOKEN_REFUSED.includes(code)) clearToken()
    markLocked(code)
  }
  throw new ApiError(res.status, code, message)
}

/** TanStack's default (3 tries), except after a 401: retrying a refused token only repeats the refusal. */
export const retryQuery = (failureCount: number, error: unknown): boolean =>
  !(error instanceof ApiError && error.status === 401) && failureCount < 3

const json = (body: unknown): RequestInit['body'] => JSON.stringify(body)

/** Au-delà, un contrôle sans réponse compte comme un échec (état unknown, ADR-005). */
export const HEALTH_TIMEOUT_MS = 5_000

export async function fetchHealth(
  signal?: AbortSignal,
  timeoutMs: number = HEALTH_TIMEOUT_MS,
): Promise<Health> {
  const timeout = AbortSignal.timeout(timeoutMs)
  const res = await fetch(apiUrl('/api/health'), {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export const tasksApi = {
  list: (signal?: AbortSignal) => request<Task[]>('/api/tasks', { signal }),
  create: (draft: TaskDraft) => request<Task>('/api/tasks', { method: 'POST', body: json(draft) }),
  update: (id: string, changes: TaskChanges) =>
    request<Task>(`/api/tasks/${id}`, { method: 'PATCH', body: json(changes) }),
  move: (id: string, change: StatusChange) =>
    request<Task>(`/api/tasks/${id}/status`, { method: 'POST', body: json(change) }),
  comments: (id: string, signal?: AbortSignal) =>
    request<Comment[]>(`/api/tasks/${id}/comments`, { signal }),
  comment: (id: string, body: string) =>
    request<Comment>(`/api/tasks/${id}/comments`, { method: 'POST', body: json({ body }) }),
  history: (id: string, signal?: AbortSignal) =>
    request<HistoryEntry[]>(`/api/tasks/${id}/history`, { signal }),
  link: (id: string, other: string) =>
    request<void>(`/api/tasks/${id}/dependencies/${other}`, { method: 'PUT' }),
  unlink: (id: string, other: string) =>
    request<void>(`/api/tasks/${id}/dependencies/${other}`, { method: 'DELETE' }),
}

export type AgentId = Exclude<Actor, 'loic'>

export type NowAgent = {
  agent: AgentId
  state: 'run' | 'idle'
  task: string | null
  title: string | null
  run: string | null
  since: string | null
}

/** `expired` is computed by the server at read time, never stored (ADR-019, D4). */
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'answered' | 'expired'

/** Decision state of an ask. `null` on an ask: published before migration 0004 (D6), or addressed by Loïc to himself (no approval is opened). */
export type NowApproval = {
  ref: string
  status: ApprovalStatus
  expires_at: string | null
  decided_by: Actor | null
  decided_at: string | null
}

export type NowAsk = {
  event: string
  agent: Actor
  kind: 'question' | 'needs_human'
  subject: string
  task: string | null
  at: string
  received_at: string
  body: string | null
  /** Texts at their original positions: a decision's `choice` is an index into this list (blank entries kept). */
  options: string[]
  /** Announced by the requester, not verified by Nexus (ADR-005). */
  consequence: string | null
  approval: NowApproval | null
}

export type NowBlock = {
  task: string
  title: string
  cause: string | null
  since: string | null
  follow_up_at: string | null
  lead_agent: Actor | null
}

export type NowDone = {
  task: string
  title: string
  agent: Actor | null
  evidence: string[]
  at: string
}

export type NowSnapshot = {
  source: string
  measured_at: string
  operation:
    | {
        task: string
        title: string
        lead_agent: Actor | null
        since: string | null
        next_action: string | null
        due_at: string | null
      }
    | null
  auxiliaries: { task: string; title: string }[]
  agents: NowAgent[]
  asks: NowAsk[]
  blocks: NowBlock[]
  done: NowDone[]
}

export type NodeState = {
  id: string
  kind: string
  guardian_agent: string
  status: 'online' | 'offline' | 'offline-by-design' | 'unknown'
  last_seen: string | null
  detail: string | null
  source: string
  measured_at: string
}

export const nowApi = {
  get: (signal?: AbortSignal) => request<NowSnapshot>('/api/now', { signal }),
}

export const nodesApi = {
  list: (signal?: AbortSignal) => request<NodeState[]>('/api/nodes', { signal }),
}

export type Decision = {
  decision: 'approved' | 'rejected'
  /** 0-based index into the ask's `options`. */
  choice?: number
  note?: string
}

/** What Loïc writes back (EVENT-PROTOCOL §6 ter): the server answers with the approval view. */
export const approvalsApi = {
  answer: (ref: string, text: string) =>
    request<unknown>(`/api/approvals/${ref}/answer`, { method: 'POST', body: json({ text }) }),
  decide: (ref: string, decision: Decision) =>
    request<unknown>(`/api/approvals/${ref}/decision`, { method: 'POST', body: json(decision) }),
}
