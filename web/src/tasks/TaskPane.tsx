import { toast } from 'sonner'
import { useState } from 'react'
import type { Status, Task } from '@/api'
import { formatDateTime } from '@/format'
import { Provenance } from '@/Provenance'
import { Button } from '@/ui'
import { MoveDialog } from './MoveDialog'
import { dependencyBlock, moveNeeds, needsPrompt, TRANSITIONS } from './moves'
import { useMoveTask } from './queries'
import { Comments, History } from './TaskPaneActivity'
import { ClosedSection, FollowsLine } from './TaskPaneClosed'
import { Dependencies } from './TaskPaneDependencies'
import { EditForm } from './TaskPaneDetails'
import { EvidenceList, EvidenceSection } from './TaskPaneEvidence'
import { Section } from './TaskPaneSection'
import { ROLE_LABEL, STATUS_LABEL } from './vocabulary'

type Props = {
  task: Task
  tasks: Task[]
  onClose: () => void
  /** Ouvre une autre tâche : quitte ce panneau, brouillons compris, comme un clic sur une carte. */
  onOpen: (id: string) => void
  /** Ouvre la création d'une tâche de suite de `id` (une tâche terminée). */
  onFollowUp: (id: string) => void
}

export function TaskPane({ task, tasks, onClose, onOpen, onFollowUp }: Props) {
  const [moving, setMoving] = useState<Status | null>(null)
  const move = useMoveTask()

  function requestMove(to: Status) {
    const waiting = dependencyBlock(task, to, tasks)
    if (waiting) {
      toast.error(waiting)
      return
    }
    if (needsPrompt(moveNeeds(task, to, tasks))) setMoving(to)
    else move.mutate({ id: task.id, change: { status: to } })
  }

  return (
    <aside
      aria-label={`Détail de ${task.title}`}
      className="flex w-[27rem] shrink-0 flex-col border-l border-line bg-surface animate-[pane-in_180ms_cubic-bezier(0.2,0.8,0.2,1)]"
    >
      <header className="flex items-start gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <p className="flex gap-2 text-xs text-muted">
            <span className="font-data tabular-nums">{task.id}</span>
            <span className="text-ink">{STATUS_LABEL[task.status]}</span>
            {task.status === 'in_progress' && task.operation_role && (
              <span className={task.operation_role === 'main' ? 'text-accent' : undefined}>
                {ROLE_LABEL[task.operation_role]}
              </span>
            )}
          </p>
          <h2 className="mt-0.5 font-orbital text-lg leading-tight font-semibold">{task.title}</h2>
          <Provenance source={task.source} measuredAt={task.measured_at} kind="tasks" className="mt-1 block font-data" />
        </div>
        <Button variant="ghost" onClick={onClose} aria-label="Fermer le détail">
          Fermer
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto">
        {task.follows && <FollowsLine follows={task.follows} tasks={tasks} onOpen={onOpen} />}

        {task.status === 'done' ? (
          <ClosedSection task={task} tasks={tasks} onOpen={onOpen} onFollowUp={onFollowUp} />
        ) : (
          <Section title="Avancer">
            <div className="flex flex-wrap gap-2">
              {TRANSITIONS[task.status].map((to) => (
                <Button key={to} onClick={() => requestMove(to)}>
                  {STATUS_LABEL[to]}
                </Button>
              ))}
            </div>
            {task.status === 'blocked' && (
              <p className="mt-3 text-xs text-attention">
                Bloqué : {task.block_cause}
                {task.block_plan && <> — se débloque si : {task.block_plan}</>}
                {task.follow_up_at && <> — relance le {formatDateTime(task.follow_up_at)}</>}
              </p>
            )}
            {task.status === 'dropped' && task.drop_reason && (
              <p className="mt-3 text-xs text-muted">Abandonnée : {task.drop_reason}</p>
            )}
          </Section>
        )}

        <EditForm key={task.id} task={task} />

        {task.status === 'done' ? (
          <EvidenceSection task={task} />
        ) : (
          task.evidence.length > 0 && (
            <Section title="Preuves">
              <EvidenceList evidence={task.evidence} />
            </Section>
          )
        )}

        <Dependencies task={task} tasks={tasks} />
        <Comments id={task.id} />
        <History id={task.id} />
      </div>

      {moving && <MoveDialog task={task} to={moving} all={tasks} onClose={() => setMoving(null)} />}
    </aside>
  )
}
