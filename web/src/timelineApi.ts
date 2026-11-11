// The story of a card (ADR-023, lot E): history, agent events and run milestones, newest first.

import { request } from './api'

export type TimelineEffect = { action: string; applied: boolean; reason?: string; approval?: string }

export type TimelineEntry = {
  /** Stable per fact (`event-12`, `history-3`, `run-1-started`): the React key and the dedupe key. */
  id: string
  kind: 'history' | 'event' | 'run_started' | 'run_ended'
  at: string
  actor?: string | null
  // history
  action?: string | null
  changes?: Record<string, unknown> | null
  // event
  event?: string | null
  event_kind?: string | null
  requested_kind?: string | null
  subject?: string | null
  body?: string | null
  origin?: string | null
  effects?: TimelineEffect[] | null
  evidence?: string[] | null
  needs?: string[] | null
  // event and run milestones
  run?: string | null
  executor?: string | null
  agent?: string | null
  status?: string | null
  source: string
  measured_at: string
}

export type TimelinePage = {
  entries: TimelineEntry[]
  next_cursor: string | null
  source: string
  measured_at: string
}

export const PAGE_SIZE = 50

export const timelineApi = {
  page: (taskId: string, before: string | null, signal?: AbortSignal) => {
    const query = new URLSearchParams({ limit: String(PAGE_SIZE) })
    if (before) query.set('before', before)
    return request<TimelinePage>(`/api/tasks/${taskId}/timeline?${query}`, { signal })
  },
}
