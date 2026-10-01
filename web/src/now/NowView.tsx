import clsx from 'clsx'
import type { ReactNode } from 'react'
import { age } from '@/format'
import { isStale } from '@/freshness'
import { Provenance } from '@/Provenance'
import { useNow } from '@/useNow'
import { AgentList } from './AgentList'
import { Floor } from './Floor'
import { AGE_TICK_MS, displayName } from './model'
import { useArrivals } from './useArrivals'
import { useNodes, useNowSnapshot } from './queries'


// Classes écrites en entier : Tailwind ne génère pas une classe construite (`text-${tone}`).
const TONE = { muted: 'text-muted', attention: 'text-attention', danger: 'text-danger', run: 'text-run' } as const

function Heading({ children, tone = 'muted' }: { children: ReactNode; tone?: keyof typeof TONE }) {
  return <h2 className={clsx('m-0 mb-1.5 font-orbital-display text-xs font-semibold uppercase tracking-[0.22em]', TONE[tone])}>{children}</h2>
}

function Tile({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div role="group" aria-label={label} className="border border-line bg-sunken px-3 py-2">
      <div className="font-orbital-display text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">{label}</div>
      <div className={clsx('font-data text-2xl', tone)}>{value}</div>
    </div>
  )
}

export function NowView() {
  const now = useNow(AGE_TICK_MS)
  const snap = useNowSnapshot()
  const nodes = useNodes()
  const s = snap.data
  const freshAsks = useArrivals(s ? s.asks.map((q) => q.event) : null)

  if (!s) {
    return (
      <div className="orbital flex h-full items-center justify-center bg-paper font-orbital text-muted">
        {snap.isError ? 'Maintenant n\'a pas pu être lu : le serveur Nexus ne répond pas.' : 'Lecture de Maintenant…'}
      </div>
    )
  }
  const active = s.agents.filter((a) => a.state === 'run').length
  const nodesStale = nodes.isError || (nodes.data?.some((n) => isStale(n.measured_at, 'nodes', now)) ?? false)
  const online = nodes.data?.filter((n) => n.status === 'online').length
  const nodesTile = nodes.data === undefined ? (nodes.isError ? 'illisibles' : 'lecture…') : `${nodesStale ? '?' : online} / ${nodes.data.length}${nodesStale ? ' · périmée' : ''}`

  return (
    <div className="orbital grid h-full min-h-0 grid-cols-[minmax(0,1fr)_336px] bg-paper font-orbital text-[13px] max-[1100px]:grid-cols-1 max-[1100px]:overflow-auto"
      style={{ backgroundImage: 'radial-gradient(rgba(244,244,245,.06) 1px, transparent 1px)', backgroundSize: '14px 14px' }}>
      <section className="flex min-w-0 flex-col gap-2 min-[1101px]:min-h-0 px-7 pt-5 pb-4 min-[1101px]:overflow-auto">
        <header className="flex items-baseline gap-4">
          <h1 className="m-0 font-orbital-display text-2xl font-semibold uppercase tracking-[0.12em]">Maintenant</h1>
          <Provenance source={s.source} measuredAt={s.measured_at} kind="now" className="font-data" />
          {snap.isError && <span className="font-data text-[11px] text-attention">dernière lecture réussie affichée</span>}
        </header>
        <div className="flex min-h-[560px] flex-1 items-center justify-center max-[760px]:hidden">
          <Floor snapshot={s} nodes={nodes.data} nodesFailed={nodes.isError} />
        </div>
        <AgentList snapshot={s} className="min-[760px]:sr-only" />
        <div className="grid grid-cols-2 gap-7 max-[760px]:grid-cols-1">
          <section>
            <Heading tone={s.blocks.length ? 'danger' : 'muted'}>Blocages {s.blocks.length || ''}</Heading>
            {s.blocks.length === 0 ? <p className="text-muted">Aucun blocage actif.</p> : s.blocks.map((b) => (
              <a key={b.task} href={`#/travail/${b.task}`} className="mb-1.5 flex flex-col gap-0.5 border-l-2 border-danger bg-[rgba(248,113,113,.05)] px-3 py-2 no-underline">
                <span className="flex justify-between gap-3"><strong className="font-semibold">{b.title}</strong><span className="font-data text-[11px] text-muted">{b.since ? age(b.since, now) : 'début inconnu'}</span></span>
                <span className="text-xs text-muted">{b.cause ?? 'Cause non renseignée.'}{b.follow_up_at ? ` Relance prévue le ${new Date(b.follow_up_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}.` : ''}</span>
              </a>
            ))}
          </section>
          <section>
            <Heading>Derniers done</Heading>
            {s.done.length === 0 ? <p className="text-muted">Rien de terminé ces 7 derniers jours.</p> : s.done.map((d) => (
              <a key={d.task} href={`#/travail/${d.task}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-b border-line py-1.5 no-underline">
                <strong className="font-semibold">{d.title}</strong><span className="font-data text-[11px] text-muted">{age(d.at, now)}</span>
                <span className="col-span-2 text-xs text-muted">Terminée{d.agent ? ` par ${displayName(d.agent)}` : ''}. {d.evidence.length ? `Preuve : ${d.evidence.join(', ')}.` : 'Aucune preuve jointe.'}</span>
              </a>
            ))}
          </section>
        </div>
      </section>
      <aside aria-label="Système" className="flex min-h-0 flex-col gap-4 overflow-auto border-l border-line bg-surface px-4.5 py-5 max-[1100px]:border-l-0 max-[1100px]:border-t">
        <Heading>Système</Heading>
        <div className="grid grid-cols-2 gap-2">
          <Tile label="Agents actifs" value={active} tone={active > 0 ? 'text-run' : undefined} />
          <Tile label="Demandes reçues" value={s.asks.length} tone={s.asks.length ? 'text-attention' : undefined} />
          <Tile label="Blocages" value={s.blocks.length} tone={s.blocks.length ? 'text-danger' : undefined} />
          <Tile label="Nœuds en ligne" value={nodesTile} />
        </div>
        <section>
          <Heading tone="attention">Demandes reçues</Heading>
          {s.asks.length === 0 ? <p className="text-muted">Aucune demande reçue ces 7 derniers jours.</p> : s.asks.map((q) => (
            <div key={q.event} className={clsx('mb-1.5 border-l-2 border-attention px-3 py-2', freshAsks.has(q.event) ? 'now-fresh' : 'bg-[rgba(251,146,60,.05)]')}>
              <div className="flex justify-between gap-3">
                {q.task ? <a href={`#/travail/${q.task}`} className="no-underline"><strong className="font-semibold">{q.subject}</strong></a> : <strong className="font-semibold">{q.subject}</strong>}
                <span className="font-data text-[11px] text-muted">{age(q.received_at, now)}</span>
              </div>
              <div className="text-xs text-muted">{q.kind === 'question' ? 'Question' : 'Demande de validation'} de {displayName(q.agent)} {q.task ? `sur ${q.task}` : 'sur aucune tâche'}.</div>
            </div>
          ))}
        </section>
        <section className="border-t border-line pt-3.5">
          <Heading tone="run">Opération principale</Heading>
          {s.operation === null ? <p className="text-muted">Pas d'opération principale en cours.</p> : (
            <a href={`#/travail/${s.operation.task}`} className="flex flex-col gap-1 no-underline">
              <strong className="text-base font-semibold">{s.operation.title}</strong>
              <span className="font-data text-[11px] leading-relaxed text-muted">
                {s.operation.lead_agent ? `menée par ${displayName(s.operation.lead_agent)}` : 'sans agent principal'}{s.operation.since ? `, ${age(s.operation.since, now)}` : ''}<br />
                prochaine action : {s.operation.next_action ?? 'non renseignée'}<br />
                {s.operation.due_at ? `échéance : ${new Date(s.operation.due_at).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })}` : 'sans échéance'}
              </span>
            </a>
          )}
          {s.auxiliaries.length > 0 && <p className="mt-2 text-xs text-muted">Auxiliaires : {s.auxiliaries.map((a) => a.title).join(', ')}</p>}
        </section>
      </aside>
    </div>
  )
}
