/*
 * Géométrie de l'étage (#6) : projection isométrique et placement des postes, en fonctions
 * pures. Unités de sol : un bureau fait 3 × 1,5. L'écran ne fait que lire ce plan.
 */
export type Pt = readonly [number, number]
export type Box = { top: string; left: string; right: string }
export type Seat = { x: number; y: number; back: boolean }
export type Layout = {
  width: number
  depth: number
  seats: Seat[]
  table: { x: number; y: number; w: number; d: number }
  racks: { x: number; y: number }[]
  viewBox: { x: number; y: number; w: number; h: number }
  project: (x: number, y: number, z?: number) => Pt
}

export const DESK = { w: 3, d: 1.5, h: 0.75 }
export const RACK = { w: 1.4, d: 1.4, h: 2.4 }
const UNIT = 26
const A = Math.cos(Math.PI / 6) * UNIT
const B = Math.sin(Math.PI / 6) * UNIT
const PITCH = 4 // un poste tous les 4 unités sur une rangée
const MARGIN = { side: 150, top: 110, bottom: 90 } // place pour les étiquettes, en px

const round = (v: number) => Math.round(v * 10) / 10

export function layoutFloor(agentCount: number, rackCount: number): Layout {
  const perRow = Math.max(4, Math.ceil(agentCount / 2))
  const rowWidth = perRow * PITCH
  const serverWidth = rackCount > 0 ? 3.2 : 0
  const width = rowWidth + 1 + serverWidth
  const depth = 14
  const seats: Seat[] = []
  for (let i = 0; i < agentCount; i++) {
    const back = i < perRow
    const col = back ? i : i - perRow
    seats.push({ x: 1.2 + col * PITCH, y: back ? 1.4 : 10.8, back })
  }
  // table centrée sur l'étendue réelle des postes
  const first = 1.2, last = 1.2 + (perRow - 1) * PITCH + DESK.w
  const table = { w: 5, d: 3.2, x: (first + last) / 2 - 2.5, y: 5.4 }
  const racks = Array.from({ length: rackCount }, (_, i) => ({ x: width - 2.1, y: 0.8 + i * 1.85 }))

  // origine choisie pour que le coin gauche du sol (0, depth) tombe à MARGIN.side
  const ox = MARGIN.side + depth * A
  const oy = MARGIN.top
  const project = (x: number, y: number, z = 0): Pt => [round(ox + (x - y) * A), round(oy + (x + y) * B - z * UNIT)]
  const right = project(width, 0)[0], bottom = project(width, depth)[1]
  const viewBox = { x: 0, y: 0, w: round(right + MARGIN.side), h: round(bottom + MARGIN.bottom) }
  return { width, depth, seats, table, racks, viewBox, project }
}

const pts = (list: Pt[]) => list.map((p) => `${p[0]},${p[1]}`).join(' ')

export function box(project: Layout['project'], x: number, y: number, z: number, w: number, d: number, h: number): Box {
  return {
    top: pts([project(x, y, z + h), project(x + w, y, z + h), project(x + w, y + d, z + h), project(x, y + d, z + h)]),
    left: pts([project(x, y + d, z + h), project(x + w, y + d, z + h), project(x + w, y + d, z), project(x, y + d, z)]),
    right: pts([project(x + w, y, z + h), project(x + w, y + d, z + h), project(x + w, y + d, z), project(x + w, y, z)]),
  }
}

export function toPercent(layout: Layout, p: Pt): readonly [number, number] {
  const { x, y, w, h } = layout.viewBox
  return [((p[0] - x) / w) * 100, ((p[1] - y) / h) * 100]
}
