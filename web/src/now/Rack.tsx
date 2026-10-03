import clsx from 'clsx'
import type { CSSProperties } from 'react'
import type { NodeState } from '@/api'
import { LED_STEP, LED_TOP, RACK, box, ledQuad, type Box, type Dir, type Layout } from './iso'
import type { RackTone } from './model'

/** Top face and visible side faces of one box. */
export function Faces({ b, topClass }: { b: Box; topClass?: string }) {
  return (<><polygon className={clsx('f-top', topClass)} points={b.top} />{b.sides.map((s) => <polygon key={s.dir} className={s.shade} points={s.points} />)}</>)
}

/** `index` is the rack's place on its floor: it staggers the arrival (--i in floor.css). */
export function Rack({ l, at, node, tone, face, index }: { l: Layout; at: { x: number; y: number }; node: NodeState; tone: RackTone; face: Dir; index: number }) {
  return (
    <g className="rack" data-node={node.id} data-tone={tone} style={{ '--i': index } as CSSProperties}>
      <Faces b={box(l, at.x, at.y, 0, RACK.w, RACK.d, RACK.h)} />
      {[0, 1, 2, 3, 4].map((j) => {
        // Three stacked layers whose opacity follows the tone, so a change fades instead of jumping.
        const pts = ledQuad(l, at, face, LED_TOP - j * LED_STEP).map((q) => q.join(',')).join(' ')
        return <g key={j}><polygon className="led" data-face={face} points={pts} /><polygon className="led-on" points={pts} /><polygon className="led-ring" points={pts} /></g>
      })}
    </g>
  )
}
