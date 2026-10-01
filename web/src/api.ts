// Toute donnée passe par l'API FastAPI — jamais d'accès direct propre au navigateur (ADR-017).

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

export async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const timeout = AbortSignal.timeout(timeoutMs)
  const res = await fetch(path, {
    ...init,
    signal: init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers,
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
  throw new ApiError(res.status, code, message)
}

const json = (body: unknown): RequestInit['body'] => JSON.stringify(body)

/** Au-delà, un contrôle sans réponse compte comme un échec (état unknown, ADR-005). */
export const HEALTH_TIMEOUT_MS = 5_000

export async function fetchHealth(
  signal?: AbortSignal,
  timeoutMs: number = HEALTH_TIMEOUT_MS,
): Promise<Health> {
  const timeout = AbortSignal.timeout(timeoutMs)
  const res = await fetch('/api/health', {
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

export type NowAsk = {
  event: string
  agent: Actor
  kind: 'question' | 'needs_human'
  subject: string
  task: string | null
  at: string
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
