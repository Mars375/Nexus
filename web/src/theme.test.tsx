import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Dialog } from './ui'

// Vitest compiles `.css` imports to an empty string (even with `?raw`), and the project has no
// Node typings: read the stylesheet through a non-literal specifier.
const fsModule = 'node:fs'
const { readFileSync } = (await import(/* @vite-ignore */ fsModule)) as {
  readFileSync: (path: string, encoding: 'utf8') => string
}
// Under jsdom `import.meta.url` is an http URL; Vitest still provides the file's directory.
const css = readFileSync(`${(import.meta as unknown as { dirname: string }).dirname}/index.css`, 'utf8')

/** Token map of every `.orbital` block of index.css; a later block overrides an earlier one, as in CSS. */
function orbitalTokens(): Record<string, string> {
  const tokens: Record<string, string> = {}
  for (const block of css.matchAll(/\n\.orbital \{([^}]*)\}/g)) {
    for (const m of block[1].matchAll(/--([\w-]+):\s*([^;]+);/g)) tokens[m[1]] = m[2].trim()
  }
  return tokens
}

type Rgba = [number, number, number, number]

function parse(value: string): Rgba {
  const hex = /^#([0-9a-f]{6})$/i.exec(value)
  if (hex) {
    const n = parseInt(hex[1], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1]
  }
  const rgba = /^rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)$/.exec(value)
  if (rgba) return [+rgba[1], +rgba[2], +rgba[3], +rgba[4]]
  throw new Error(`unsupported colour: ${value}`)
}

/** `top` painted over an opaque `under` colour. */
function over(top: Rgba, under: Rgba): Rgba {
  const [r, g, b, a] = top
  return [0, 1, 2].map((i) => [r, g, b][i] * a + under[i] * (1 - a)).concat(1) as Rgba
}

function luminance([r, g, b]: Rgba): number {
  const lin = (c: number) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function ratio(a: Rgba, b: Rgba): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const t = orbitalTokens()
const colour = (name: string, under?: Rgba) => {
  const c = parse(t[name])
  return under ? over(c, under) : c
}
const surfaces = ['paper', 'surface', 'surface-sunken'] as const

describe('orbital theme: contrast (WCAG 2.x)', () => {
  it('declares the tokens the Travail view relies on', () => {
    for (const name of ['paper', 'surface', 'surface-sunken', 'ink', 'muted', 'line-strong', 'accent', 'on-accent'])
      expect(t[name], name).toBeDefined()
  })

  const texts = ['ink', 'muted', 'accent', 'attention', 'danger', 'ok', 'run', 'unknown']
  const agents = ['loic', 'helios', 'mnema', 'aether', 'artemis', 'claude', 'codex', 'orca', 'hermes'].map((a) => `agent-${a}`)
  for (const text of [...texts, ...agents]) {
    for (const surface of surfaces) {
      it(`text ${text} on ${surface} is at least 4.5:1`, () => {
        expect(ratio(colour(text), colour(surface))).toBeGreaterThanOrEqual(4.5)
      })
    }
  }

  it('text on the main-operation card (accent-soft over the column, which is sunken) is at least 4.5:1', () => {
    const card = colour('accent-soft', colour('surface-sunken'))
    for (const text of ['ink', 'muted', 'accent']) expect(ratio(colour(text), card), text).toBeGreaterThanOrEqual(4.5)
  })

  it('text on hovered buttons (ink at 10% over the surface) is at least 4.5:1', () => {
    for (const surface of surfaces) {
      const hover = over([...parse(t.ink).slice(0, 3), 0.1] as Rgba, colour(surface))
      for (const text of ['ink', 'muted']) expect(ratio(colour(text), hover), `${text}/${surface}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('primary button text (on-accent) on accent, plain and at 90%, is at least 4.5:1', () => {
    expect(ratio(colour('on-accent'), colour('accent'))).toBeGreaterThanOrEqual(4.5)
    for (const surface of surfaces) {
      const hover = over([...parse(t.accent).slice(0, 3), 0.9] as Rgba, colour(surface))
      expect(ratio(colour('on-accent'), hover)).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('control borders and the focus ring are at least 3:1 against every surface', () => {
    for (const surface of surfaces) {
      expect(ratio(colour('line-strong'), colour(surface)), `line-strong/${surface}`).toBeGreaterThanOrEqual(3)
      expect(ratio(colour('accent'), colour(surface)), `accent/${surface}`).toBeGreaterThanOrEqual(3)
    }
  })
})

describe('orbital theme: portals', () => {
  it('Dialog renders in a portal outside any .orbital parent, so it carries the theme class itself', () => {
    render(
      <div className="orbital">
        <Dialog open onOpenChange={() => {}} title="Test">
          <p>contenu</p>
        </Dialog>
      </div>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog.closest('.orbital')).toBe(dialog)
  })
})
