import type { HistoryEntry } from '@/api'
import { describeHistory } from '@/tasks/history'
import { actorName } from '@/tasks/vocabulary'
import type { TimelineEntry } from '@/timelineApi'
import { RUN_STATUS_LABEL } from './vocabulary'

/** What an agent event says, with the actor in front: « Codex a pris la tâche ». */
const EVENT_VERB: Record<string, string> = {
  claimed: 'a pris la tâche',
  working: 'travaille dessus',
  progress: 'avance',
  question: 'pose une question',
  blocked: 'est bloqué',
  needs_human: 'demande un humain',
  handoff: 'passe la main',
  review: 'demande une vérification',
  done: 'a terminé',
  failed: 'a échoué',
  unknown: 'ne sait plus où il en est',
  answer: 'a reçu une réponse',
}

export type Group =
  | { type: 'entry'; entry: TimelineEntry }
  | { type: 'progress'; run: string; entries: TimelineEntry[] }

const isProgress = (e: TimelineEntry) => e.kind === 'event' && e.event_kind === 'progress' && !!e.run

/** Consecutive `progress` of one run fold into a single group; anything else stays alone. */
export function groupEntries(entries: TimelineEntry[]): Group[] {
  const groups: Group[] = []
  let current: TimelineEntry[] = []
  const flush = () => {
    if (current.length === 1) groups.push({ type: 'entry', entry: current[0] })
    else if (current.length > 1) groups.push({ type: 'progress', run: current[0].run as string, entries: current })
    current = []
  }
  for (const entry of entries) {
    if (isProgress(entry) && (current.length === 0 || current[0].run === entry.run)) {
      current.push(entry)
      continue
    }
    flush()
    if (isProgress(entry)) current.push(entry)
    else groups.push({ type: 'entry', entry })
  }
  flush()
  return groups
}

/** The effects the server did not apply, each with its reason in plain words. */
export function unappliedEffects(entry: TimelineEntry): { action: string; reason: string }[] {
  return (entry.effects ?? [])
    .filter((e) => !e.applied)
    .map((e) => ({ action: e.action, reason: e.reason ?? 'raison non donnée' }))
}

export function describeEntry(entry: TimelineEntry): string {
  const who = actorName(entry.actor)
  switch (entry.kind) {
    case 'history':
      return `${who} ${describeHistory({ actor: entry.actor, action: entry.action ?? '', changes: entry.changes ?? {} } as HistoryEntry)}`
    case 'event': {
      const kind = entry.event_kind ?? ''
      return Object.hasOwn(EVENT_VERB, kind) ? `${who} ${EVENT_VERB[kind]}` : `${who} : ${kind}`
    }
    case 'run_started':
      return `Run ${entry.run} confié à ${actorName(entry.agent)}`
    case 'run_ended': {
      const status = entry.status ?? ''
      const label = Object.hasOwn(RUN_STATUS_LABEL, status)
        ? RUN_STATUS_LABEL[status as keyof typeof RUN_STATUS_LABEL].toLowerCase()
        : null
      return label ? `Run ${entry.run} terminé : ${label}` : `Run ${entry.run} terminé`
    }
  }
}
