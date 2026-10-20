import { useState, type FormEvent } from 'react'
import { formatDateTime } from '@/format'
import { listProvenance, type Provenanced } from '@/freshness'
import { Provenance } from '@/Provenance'
import { AgentMark, Button, inputClass } from '@/ui'
import { describeHistory } from './history'
import { useAddComment, useComments, useHistory } from './queries'
import { Section } from './TaskPaneSection'
import { actorName } from './vocabulary'

/** Provenance d'une sous-liste (commentaires, historique) : son élément le plus ancien. */
function ListProvenance({ items, updatedAt }: { items: Provenanced[] | undefined; updatedAt: number }) {
  const provenance = items ? listProvenance(items, 'tasks', updatedAt) : null
  return provenance ? (
    <p className="mb-2">
      <Provenance source={provenance.source} measuredAt={provenance.measuredAt} kind="tasks" />
    </p>
  ) : null
}

/** Chargement, échec ou données non à jour d'une section de détail (ADR-005 : jamais de vide muet). */
function LoadState({ query, what, label }: {
  query: { isPending: boolean; isError: boolean; data: unknown }
  what: string
  label: string
}) {
  if (query.isPending) return <p className="text-xs text-muted">Chargement…</p>
  if (query.isError && !query.data)
    return <p className="text-xs text-danger">Impossible de lire {what} : le serveur Nexus ne répond pas.</p>
  if (query.isError)
    return (
      <p role="status" className="mb-2 text-xs text-attention">
        {label} non à jour : le dernier rafraîchissement a échoué.
      </p>
    )
  return null
}

export function Comments({ id }: { id: string }) {
  const comments = useComments(id)
  const add = useAddComment(id)
  const [body, setBody] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!body.trim()) return
    add.mutate(body, { onSuccess: () => setBody('') })
  }

  return (
    <Section title="Commentaires">
      <LoadState query={comments} what="les commentaires" label="Commentaires" />
      <ListProvenance items={comments.data} updatedAt={comments.dataUpdatedAt} />
      <ul className="grid gap-3">
        {comments.data?.map((c) => (
          <li key={c.id} className="text-xs">
            <p className="flex items-center gap-2 text-muted">
              <AgentMark actor={c.author} withName />
              <span>{formatDateTime(c.at)}</span>
            </p>
            <p className="mt-1 whitespace-pre-wrap">{c.body}</p>
          </li>
        ))}
        {comments.data?.length === 0 && <li className="text-xs text-muted">Aucun commentaire.</li>}
      </ul>
      <form onSubmit={submit} className="mt-3 grid gap-2">
        <textarea
          className={inputClass}
          rows={2}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Ajouter un commentaire"
          aria-label="Nouveau commentaire"
        />
        <div className="flex justify-end">
          <Button type="submit" disabled={!body.trim() || add.isPending}>
            Commenter
          </Button>
        </div>
      </form>
    </Section>
  )
}

export function History({ id }: { id: string }) {
  const history = useHistory(id)
  return (
    <Section title="Historique">
      <LoadState query={history} what="l’historique" label="Historique" />
      <ListProvenance items={history.data} updatedAt={history.dataUpdatedAt} />
      <ol className="grid gap-1.5 text-xs">
        {history.data
          ?.slice()
          .reverse()
          .map((entry) => (
            <li key={entry.id} className="flex gap-2">
              <span className="w-28 shrink-0 text-muted tabular-nums">{formatDateTime(entry.at)}</span>
              <span>
                {actorName(entry.actor)} {describeHistory(entry)}
              </span>
            </li>
          ))}
      </ol>
    </Section>
  )
}
