import { describe, expect, test } from 'vitest'
import { isStale, listProvenance, REFRESH_MS, SOURCE_OF, STALE_FACTOR } from './freshness'

const T0 = Date.parse('2026-09-29T10:00:00+02:00')
const at = (ms: number) => new Date(T0 + ms).toISOString()

describe('isStale', () => {
  test('juste à 3 × la cadence, la donnée est encore fraîche', () => {
    expect(isStale(at(0), 'tasks', T0 + STALE_FACTOR * REFRESH_MS.tasks)).toBe(false)
  })
  test('au-delà de 3 × la cadence, elle est périmée', () => {
    expect(isStale(at(0), 'tasks', T0 + 30_001)).toBe(true)
  })
  test('la cadence dépend du type : un nœud reste frais 3 min', () => {
    expect(isStale(at(0), 'nodes', T0 + 179_000)).toBe(false)
    expect(isStale(at(0), 'nodes', T0 + 181_000)).toBe(true)
  })
  test('une date illisible compte comme périmée', () => {
    expect(isStale('pas une date', 'tasks', T0)).toBe(true)
  })
  test('une date dans le futur n\'est jamais périmée', () => {
    expect(isStale(at(60_000), 'tasks', T0)).toBe(false)
  })
})

describe('listProvenance', () => {
  test('une liste est aussi fraîche que son élément le plus ancien', () => {
    const items = [
      { source: 'nexus.db', measured_at: at(5_000) },
      { source: 'nexus.db', measured_at: at(0) },
    ]
    expect(listProvenance(items, 'tasks', T0 + 6_000)).toEqual({ source: 'nexus.db', measuredAt: at(0) })
  })
  test('liste vide : source du type et instant de la dernière lecture réussie', () => {
    expect(listProvenance([], 'tasks', T0)).toEqual({
      source: SOURCE_OF.tasks,
      measuredAt: new Date(T0).toISOString(),
    })
  })
  test('liste vide jamais lue : rien à afficher', () => {
    expect(listProvenance([], 'tasks', 0)).toBeNull()
  })
})
