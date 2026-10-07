import { expect, test } from 'vitest'
import { until } from './format'

const NOW = Date.parse('2026-10-07T12:00:00+02:00')
const at = (ms: number) => new Date(NOW + ms).toISOString()

test('until : une durée à venir, à la minute, à l\'heure ou au jour', () => {
  expect(until(at(30_000), NOW)).toBe('dans moins d\'une minute')
  expect(until(at(12 * 60_000), NOW)).toBe('dans 12 min')
  expect(until(at(3 * 3_600_000 - 40), NOW)).toBe('dans 3 h')
  expect(until(at(60 * 3_600_000), NOW)).toBe('dans 3 j')
})

test('until : une échéance atteinte ou passée ne s\'annonce pas comme à venir', () => {
  expect(until(at(0), NOW)).toBe('maintenant')
  expect(until(at(-5_000), NOW)).toBe('maintenant')
})

test('until : on compare des instants, pas du texte (heure d\'automne à Paris)', () => {
  const later = '2026-10-25T02:30:00+01:00' // after 02:15+02:00
  expect(until(later, Date.parse('2026-10-25T02:15:00+02:00'))).toBe('dans 1 h')
})
