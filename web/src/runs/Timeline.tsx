import { useState } from 'react'
import { formatDateTime } from '@/format'
import { ListProvenance, LoadState } from '@/tasks/TaskPaneActivity'
import { Section } from '@/tasks/TaskPaneSection'
import type { TimelineEntry } from '@/timelineApi'
import { Button } from '@/ui'
import { describeEntry, groupEntries, unappliedEffects } from './timelineModel'
import { useTimeline } from './timelineQueries'

function EntryRow({ entry }: { entry: TimelineEntry }) {
  const unapplied = unappliedEffects(entry)
  return (
    <li className="grid gap-0.5 text-xs">
      <p className="flex gap-2">
        <span className="w-28 shrink-0 text-muted tabular-nums">{formatDateTime(entry.at)}</span>
        <span>
          {describeEntry(entry)}
          {entry.kind === 'event' && entry.run && (
            <span className="ml-2 font-data text-muted">{entry.run}</span>
          )}
        </span>
      </p>
      {entry.kind === 'event' && (entry.subject || entry.body) && (
        <div className="pl-[7.5rem] text-muted">
          {entry.subject && <p className="whitespace-pre-wrap">{entry.subject}</p>}
          {entry.body && <p className="whitespace-pre-wrap">{entry.body}</p>}
        </div>
      )}
      {(entry.evidence ?? []).map((proof) => (
        <p key={proof} className="pl-[7.5rem] text-muted">
          Preuve : <span className="font-data">{proof}</span>
        </p>
      ))}
      {unapplied.map((effect) => (
        <p key={effect.action} className="pl-[7.5rem] text-attention">
          Sans effet sur la tâche ({effect.action}) : {effect.reason}
        </p>
      ))}
    </li>
  )
}

export function Timeline({ id }: { id: string }) {
  const timeline = useTimeline(id)
  // Kept here, not in the group: a refresh must not fold again what a person opened.
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())
  const entries = timeline.data ?? []

  function toggle(key: string) {
    setOpen((current) => {
      const next = new Set(current)
      if (!next.delete(key)) next.add(key)
      return next
    })
  }

  return (
    <Section title="Chronologie">
      {timeline.isError && !timeline.data && (
        <p role="status" className="text-xs text-danger">
          Impossible de lire la chronologie : le serveur Nexus ne répond pas.
        </p>
      )}
      {timeline.isError && timeline.data && (
        <LoadState
          query={{ isPending: false, isError: true, data: timeline.data }}
          what="la chronologie"
          label="Chronologie"
        />
      )}
      {timeline.isPending && <p className="text-xs text-muted">Chargement de la chronologie…</p>}
      <ListProvenance items={timeline.data} updatedAt={timeline.dataUpdatedAt} />
      {timeline.isSuccess && entries.length === 0 && (
        <p className="text-xs text-muted">Rien ne s’est encore passé sur cette carte.</p>
      )}
      <ol className="grid gap-2">
        {groupEntries(entries).map((group) => {
          if (group.type === 'entry') return <EntryRow key={group.entry.id} entry={group.entry} />
          // The oldest entry names the group: newer progress joins it without changing its key.
          const key = group.entries[group.entries.length - 1].id
          const expanded = open.has(key)
          return (
            <li key={key} className="text-xs">
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => toggle(key)}
                className="text-left text-muted underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-accent"
              >
                {expanded ? '▾' : '▸'} {group.entries.length} avancées de {group.run}
              </button>
              {expanded && (
                <ol className="mt-2 grid gap-2 border-l border-line pl-3">
                  {group.entries.map((entry) => (
                    <EntryRow key={entry.id} entry={entry} />
                  ))}
                </ol>
              )}
            </li>
          )
        })}
      </ol>
      {timeline.isFetchNextPageError && (
        <p role="alert" className="mt-2 text-xs text-danger">
          Impossible de lire la suite : les entrées déjà affichées restent valables.
        </p>
      )}
      {timeline.hasNextPage && (
        <div className="mt-3">
          <Button variant="ghost" disabled={timeline.isFetchingNextPage} onClick={() => void timeline.fetchNextPage()}>
            Charger plus ancien
          </Button>
        </div>
      )}
    </Section>
  )
}
