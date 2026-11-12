import { useState } from 'react'
import type { Task } from '@/api'
import { formatDateTime } from '@/format'
import type { Run } from '@/runsApi'
import { ListProvenance } from '@/tasks/TaskPaneActivity'
import { Section } from '@/tasks/TaskPaneSection'
import { actorName } from '@/tasks/vocabulary'
import { Button, Dialog } from '@/ui'
import { ConfierDialog } from './ConfierDialog'
import { useCancelRun, useRunEvidence, useRuns } from './queries'
import { BRANCH_EXECUTORS, CANCELLABLE, HANDOVER_CLOSED, modelName, RUN_STATUS_LABEL } from './vocabulary'

export function RunsSection({ task }: { task: Task }) {
  const runs = useRuns(task.id)
  const evidence = useRunEvidence(task.id, (runs.data?.length ?? 0) > 0)
  const [handing, setHanding] = useState(false)
  const [cancelling, setCancelling] = useState<Run | null>(null)
  const cancel = useCancelRun(task.id)
  const list = runs.data ?? []
  // The run the dialog is about, as it is now: it may have ended or been cancelled meanwhile.
  const current = cancelling ? (list.find((r) => r.id === cancelling.id) ?? cancelling) : null
  const cancellable = current !== null && CANCELLABLE.includes(current.status) && !current.cancel_requested_at

  return (
    <Section title="Runs">
      {runs.isPending && <p className="text-xs text-muted">Chargement des runs…</p>}
      {runs.isError && (
        <p role="alert" className="text-xs text-danger">
          Impossible de lire les runs{runs.data ? ' : les derniers connus restent affichés, peut-être périmés' : ''}.
        </p>
      )}
      {runs.isSuccess && list.length === 0 && <p className="text-xs text-muted">Aucun run : rien n’a été confié.</p>}
      {list.length > 0 && (
        <ul className="grid gap-2.5">
          {list.map((run) => (
            <li key={run.id} className="grid gap-0.5 text-xs">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-data tabular-nums">{run.id}</span>
                <span className="text-ink">{RUN_STATUS_LABEL[run.status]}</span>
                <span className="text-muted">
                  {actorName(run.executor)} → {actorName(run.agent)}
                  {run.model ? ` · ${modelName(run.model)}` : ''}
                </span>
              </p>
              {run.native_status && (
                <p className="text-muted">
                  Statut de l’exécutant : <span className="font-data">{run.native_status}</span>
                </p>
              )}
              {run.external_ref && (
                <p className="text-muted">
                  {BRANCH_EXECUTORS.includes(run.executor) ? 'Branche' : 'Référence de l’exécutant'} :{' '}
                  <span className="font-data">{run.external_ref}</span>
                </p>
              )}
              {(evidence.data?.get(run.id) ?? []).map((proof) => (
                <p key={proof} className="text-muted">
                  Preuve : <span className="font-data">{proof}</span>
                </p>
              ))}
              {run.cancel_requested_at && !run.ended_at && (
                <p className="text-attention">Annulation demandée le {formatDateTime(run.cancel_requested_at)}</p>
              )}
              {CANCELLABLE.includes(run.status) && !run.cancel_requested_at && (
                <div>
                  <Button variant="ghost" className="px-2 py-0.5 text-xs" onClick={() => setCancelling(run)}>
                    Annuler le run {run.id}
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {list.length > 0 && evidence.isPending && (
        <p className="mt-2 text-xs text-muted">Lecture des preuves…</p>
      )}
      {list.length > 0 && evidence.isError && (
        <p role="status" className="mt-2 text-xs text-attention">
          Les preuves des runs n’ont pas pu être lues{evidence.data ? ' : celles affichées sont peut-être périmées' : ''}.
        </p>
      )}
      <div className="mt-2">
        <ListProvenance items={runs.data} updatedAt={runs.dataUpdatedAt} />
      </div>
      {!HANDOVER_CLOSED.includes(task.status) && (
        <div className="mt-3">
          <Button onClick={() => setHanding(true)}>Confier à…</Button>
        </div>
      )}

      {handing && <ConfierDialog task={task} onClose={() => setHanding(false)} />}
      {cancelling && current && (
        <Dialog
          open
          onOpenChange={(open) => !open && setCancelling(null)}
          title={`Annuler le run ${cancelling.id} ?`}
          description="L’exécutant est arrêté ; ce que l’agent a déjà écrit dans son worktree reste en place."
        >
          {!cancellable && (
            <p role="alert" className="mb-3 text-xs text-danger">
              Ce run a changé depuis : il ne s’annule plus ({RUN_STATUS_LABEL[current.status].toLowerCase()}
              {current.cancel_requested_at ? ', annulation déjà demandée' : ''}).
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCancelling(null)} autoFocus>
              Garder le run
            </Button>
            <Button
              variant="primary"
              disabled={!cancellable}
              onClick={() => {
                cancel.mutate(cancelling.id)
                setCancelling(null)
              }}
            >
              Annuler le run
            </Button>
          </div>
        </Dialog>
      )}
    </Section>
  )
}
