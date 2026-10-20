import type { ReactNode } from 'react'

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-line px-5 py-4">
      <h3 className="mb-2.5 font-orbital-display text-xs font-semibold uppercase tracking-[0.18em] text-muted">{title}</h3>
      {children}
    </section>
  )
}
