import { useState } from 'react'
import type { Task } from '@/api'
import { formatDateTime } from '@/format'
import { Provenance } from '@/Provenance'
import type { Run } from '@/runsApi'
import { Section } from '@/tasks/TaskPaneSection'
import { actorName } from '@/tasks/vocabulary'
import { Button, Dialog } from '@/ui'
import { ConfierDialog } from './ConfierDialog'
import { useCancelRun, useRunEvidence, useRuns } from './queries'
import { CANCELLABLE, RUN_STATUS_LABEL } from './vocabulary'

/** A task that ended (done) or was dropped cannot be handed over (the server says 409). */
const HANDOVER_CLOSED = ['done', 'dropped']

export function RunsSection({ task }: { task: Task }) {
  const runs = useRuns(task.id)
  const evidence = useRunEvidence(task.id, (runs.data?.length ?? 0) > 0)
  const [handing, setHanding] = useState(false)
  const [cancelling, setCancelling] = useState<Run | null>(null)
  const cancel = useCancelRun(task.id)
  const list = runs.data ?? []
  const first = list[0]

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
                </span>
              </p>
              {run.native_status && (
                <p className="text-muted">
                  Statut de l’exécutant : <span className="font-data">{run.native_status}</span>
                </p>
              )}
              {run.external_ref && (
                <p className="text-muted">
                  Branche : <span className="font-data">{run.external_ref}</span>
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
      {first && <Provenance source={first.source} measuredAt={first.measured_at} kind="tasks" className="mt-2 block font-data" />}
      {!HANDOVER_CLOSED.includes(task.status) && (
        <div className="mt-3">
          <Button onClick={() => setHanding(true)}>Confier à…</Button>
        </div>
      )}

      {handing && <ConfierDialog task={task} onClose={() => setHanding(false)} />}
      {cancelling && (
        <Dialog
          open
          onOpenChange={(open) => !open && setCancelling(null)}
          title={`Annuler le run ${cancelling.id} ?`}
          description="L’exécutant est arrêté ; ce que l’agent a déjà écrit dans son worktree reste en place."
        >
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCancelling(null)} autoFocus>
              Garder le run
            </Button>
            <Button
              variant="primary"
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
