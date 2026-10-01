import { describe, expect, test } from 'vitest'
import { DESK, box, layoutFloor, toPercent } from './iso'

describe('layoutFloor', () => {
  test('8 agents : deux rangées de 4, la table au centre', () => {
    const l = layoutFloor(8, 4)
    expect(l.seats).toHaveLength(8)
    expect(l.seats.filter((s) => s.back)).toHaveLength(4)
    const tableCenterX = l.table.x + l.table.w / 2
    const seatsCenterX = (Math.min(...l.seats.map((s) => s.x)) + Math.max(...l.seats.map((s) => s.x + DESK.w))) / 2
    expect(Math.abs(tableCenterX - seatsCenterX)).toBeLessThan(0.01)
    expect(l.racks).toHaveLength(4)
  })
  test('12 agents : les rangées s\'allongent, l\'étage s\'élargit', () => {
    const eight = layoutFloor(8, 4), twelve = layoutFloor(12, 4)
    expect(twelve.seats.filter((s) => s.back)).toHaveLength(6)
    expect(twelve.width).toBeGreaterThan(eight.width)
  })
  test('aucun bureau ne chevauche la table ni un autre bureau', () => {
    const l = layoutFloor(12, 4)
    const rects = [...l.seats.map((s) => ({ x: s.x, y: s.y, w: DESK.w, d: DESK.d })), { x: l.table.x, y: l.table.y, w: l.table.w, d: l.table.d }]
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i], b = rects[j]
      const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.d && b.y < a.y + a.d
      expect(overlap).toBe(false)
    }
  })
  test('tout le sol tient dans le viewBox', () => {
    const l = layoutFloor(8, 4), { x, y, w, h } = l.viewBox
    for (const [px, py] of [l.project(0, 0), l.project(l.width, 0), l.project(0, l.depth), l.project(l.width, l.depth)]) {
      expect(px).toBeGreaterThanOrEqual(x); expect(px).toBeLessThanOrEqual(x + w)
      expect(py).toBeGreaterThanOrEqual(y); expect(py).toBeLessThanOrEqual(y + h)
    }
  })
  test('1 agent et aucun nœud : un étage valable', () => {
    const l = layoutFloor(1, 0)
    expect(l.seats).toHaveLength(1)
    expect(l.racks).toHaveLength(0)
  })
})

describe('box', () => {
  test('rend trois faces de quatre points chacune', () => {
    const l = layoutFloor(8, 4)
    const b = box(l.project, 1, 1, 0, 3, 1.5, 0.75)
    for (const face of [b.top, b.left, b.right]) expect(face.split(' ')).toHaveLength(4)
  })
  test('le dessus est plus haut à l\'écran que le bas (z monte)', () => {
    const l = layoutFloor(8, 4)
    expect(l.project(1, 1, 1)[1]).toBeLessThan(l.project(1, 1, 0)[1])
  })
})

test('toPercent place un point du viewBox en pourcentage', () => {
  const l = layoutFloor(8, 4)
  const [px, py] = toPercent(l, [l.viewBox.x + l.viewBox.w / 2, l.viewBox.y + l.viewBox.h / 4])
  expect(px).toBeCloseTo(50); expect(py).toBeCloseTo(25)
})
