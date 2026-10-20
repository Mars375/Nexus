import { useState } from 'react'
import type { Task } from '@/api'
import { Button, inputClass } from '@/ui'
import { dependencyCandidates, dependencyRefusal } from './moves'
import { useLink } from './queries'
import { Section } from './TaskPaneSection'
import { STATUS_LABEL } from './vocabulary'

export function Dependencies({ task, tasks }: { task: Task; tasks: Task[] }) {
  const link = useLink(task.id)
  const [choice, setChoice] = useState('')
  const byId = new Map(tasks.map((t) => [t.id, t]))
  const candidates = dependencyCandidates(task, tasks)
  // La liste peut changer pendant qu'un choix est en attente (statut modifié par un agent) :
  // le choix fait partie du brouillon, il reste affiché avec la raison et bloque l'ajout.
  const refusal = choice ? dependencyRefusal(task, choice, tasks) : null
  // Une tâche terminée ne change plus ses dépendances (ADR-022) : ni « Retirer », ni ajout.
  const closed = task.status === 'done'

  return (
    <Section title="Dépend de">
      {task.depends_on.length === 0 ? (
        <p className="text-xs text-muted">Aucune dépendance.</p>
      ) : (
        <ul className="grid gap-1.5">
          {task.depends_on.map((id) => {
            const dep = byId.get(id)
            return (
              <li key={id} className="flex items-center gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate">
                  {dep ? dep.title : id}
                  <span className="text-muted"> — {dep ? STATUS_LABEL[dep.status] : 'inconnue'}</span>
                </span>
                {!closed && (
                  <Button variant="ghost" className="px-2 py-0.5 text-xs" onClick={() => link.mutate({ other: id, remove: true })}>
                    Retirer
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {(candidates.length > 0 || choice) && (
        <div className="mt-3 grid gap-1.5">
          <div className="flex gap-2">
            <select
              className={inputClass}
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
              aria-label="Tâche dont celle-ci dépend"
              aria-invalid={refusal ? true : undefined}
            >
              {/* Sur une tâche terminée, l'option vide sert à abandonner le choix, pas à en faire un. */}
              <option value="">{closed ? 'Abandonner ce choix' : 'Ajouter une dépendance…'}</option>
              {refusal && (
                <option value={choice}>{byId.get(choice)?.title ?? 'Tâche disparue'} — choix invalide</option>
              )}
              {candidates.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
            <Button
              disabled={!choice || refusal !== null}
              onClick={() => {
                link.mutate({ other: choice })
                setChoice('')
              }}
            >
              Ajouter
            </Button>
          </div>
          {refusal && (
            <p role="alert" className="text-xs text-danger">
              {refusal}
            </p>
          )}
        </div>
      )}
    </Section>
  )
}
