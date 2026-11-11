import { expect, test } from 'vitest'
import type { TimelineEntry } from '@/timelineApi'
import { describeEntry, eventEffects, groupEntries, originLabel } from './timelineModel'

const T = '2026-11-10T09:00:00+00:00'
let n = 0

function event(kind: string, run: string | null = 'nx-run-1', extra: Partial<TimelineEntry> = {}): TimelineEntry {
  n += 1
  return {
    id: `event-${n}`, kind: 'event', at: T, actor: 'codex', event: `evt_${n}`, event_kind: kind,
    subject: `sujet ${n}`, body: null, origin: 'fake', effects: [], evidence: [], needs: [], run,
    source: 'nexus.db', measured_at: T, ...extra,
  }
}

test('des progress consécutifs d’un même run se replient en un groupe', () => {
  const list = [event('done'), event('progress'), event('progress'), event('progress'), event('claimed')]
  const groups = groupEntries(list)
  expect(groups.map((g) => g.type)).toEqual(['entry', 'progress', 'entry'])
  const progress = groups[1]
  expect(progress.type === 'progress' && progress.entries).toHaveLength(3)
})

test('un progress seul reste une entrée, et un autre run coupe le groupe', () => {
  expect(groupEntries([event('progress')]).map((g) => g.type)).toEqual(['entry'])
  const mixed = groupEntries([event('progress', 'nx-run-1'), event('progress', 'nx-run-2')])
  expect(mixed.map((g) => g.type)).toEqual(['entry', 'entry'])
  const noRun = groupEntries([event('progress', null), event('progress', null)])
  expect(noRun.map((g) => g.type)).toEqual(['entry', 'entry'])
})

test('une entrée d’un autre type entre deux progress coupe le groupe', () => {
  const history: TimelineEntry = {
    id: 'history-1', kind: 'history', at: T, actor: 'loic', action: 'commented', changes: {},
    source: 'nexus.db', measured_at: T,
  }
  const groups = groupEntries([event('progress'), history, event('progress')])
  expect(groups.map((g) => g.type)).toEqual(['entry', 'entry', 'entry'])
})

test('les effets appliqués et non appliqués, ceux-ci avec leur raison', () => {
  const e = event('handoff', 'nx-run-1', {
    effects: [{ action: 'handoff', applied: false, reason: 'tâche déjà terminée' }, { action: 'status:done', applied: true }],
  })
  expect(eventEffects(e)).toEqual([
    { applied: false, action: 'handoff', reason: 'tâche déjà terminée' },
    { applied: true, action: 'status:done', reason: null },
  ])
  expect(eventEffects(event('done'))).toEqual([])
})

test('l’origine dit qui a porté l’événement jusqu’à Nexus', () => {
  expect(originLabel('api')).toBe('publié par l’API')
  expect(originLabel('codex')).toBe('publié par l’adaptateur codex')
  expect(originLabel(null)).toBeNull()
})

test('describeEntry dit qui et quoi, sans valeur brute', () => {
  expect(describeEntry(event('claimed'))).toBe('Codex a pris la tâche')
  expect(describeEntry(event('done'))).toBe('Codex a terminé')
  expect(describeEntry(event('mystère'))).toBe('Codex : mystère')
  const started: TimelineEntry = {
    id: 'run-1-started', kind: 'run_started', at: T, run: 'nx-run-1', executor: 'codex', agent: 'codex',
    status: 'dispatched', source: 'nexus.db', measured_at: T,
  }
  expect(describeEntry(started)).toBe('Run nx-run-1 confié à Codex')
  expect(describeEntry({ ...started, kind: 'run_ended', status: 'failed' })).toBe('Run nx-run-1 terminé : échoué')
  expect(describeEntry({ ...started, kind: 'run_ended', status: 'inconnu-futur' })).toBe('Run nx-run-1 terminé')
})
