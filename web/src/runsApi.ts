// Runs (ADR-023): work handed to an agent. Every call goes through the FastAPI API.

import { request, type Actor } from './api'

export type RunStatus =
  | 'dispatched'
  | 'running'
  | 'unknown'
  | 'blocked'
  | 'review'
  | 'done'
  | 'failed'
  | 'cancelled'

export type Run = {
  id: string
  task: string
  executor: Actor
  agent: Actor
  dispatched_by: Actor
  client_key: string
  brief: string
  workdir: string | null
  /** The executor's own reference; for Codex, the branch `nexus/nx-run-<n>`. */
  external_ref: string | null
  status: RunStatus
  /** The executor's own word, shown as given and never interpreted (ADR-005). */
  native_status: string | null
  created_at: string
  ended_at: string | null
  cancel_requested_at: string | null
  version: number
  source: string
  measured_at: string
}

/** An executor that can take work now (an adapter is registered), with whom it works for. */
export type ExecutorInfo = {
  executor: Actor
  agents: Actor[]
  workdirs: string[]
  source: string
  measured_at: string
}

export type RunDraft = {
  executor: Actor
  agent: Actor
  /** One per dialog: a double click or a resend with it is the same run (idempotent). */
  client_key: string
  brief: string
  workdir?: string
}

const json = (body: unknown): RequestInit['body'] => JSON.stringify(body)

export const runsApi = {
  executors: (signal?: AbortSignal) => request<ExecutorInfo[]>('/api/executors', { signal }),
  forTask: (taskId: string, signal?: AbortSignal) =>
    request<Run[]>(`/api/tasks/${taskId}/runs`, { signal }),
  dispatch: (taskId: string, draft: RunDraft) =>
    request<Run>(`/api/tasks/${taskId}/runs`, { method: 'POST', body: json(draft) }),
  /** The evidence each run's events carry, by run (`nx-run-<n>` → references, no duplicate). */
  evidence: async (taskId: string, signal?: AbortSignal): Promise<Map<string, string[]>> => {
    const events = await request<{ run: string | null; evidence: string[] }[]>(
      `/api/events?task=${taskId}&limit=500`,
      { signal },
    )
    const byRun = new Map<string, string[]>()
    for (const e of events) {
      if (!e.run || e.evidence.length === 0) continue
      byRun.set(e.run, [...new Set([...(byRun.get(e.run) ?? []), ...e.evidence])])
    }
    return byRun
  },
  cancel: (runId: string) => request<Run>(`/api/runs/${runId}/cancel`, { method: 'POST' }),
}
