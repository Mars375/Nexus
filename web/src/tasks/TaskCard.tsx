import { useDraggable } from '@dnd-kit/core'
import clsx from 'clsx'
import type { Status, Task } from '@/api'
import { formatShortDate, isOverdue } from '@/format'
import { AgentMark } from '@/ui'
import { PRIORITY_LABEL } from './vocabulary'

type CardProps = {
  task: Task
  pendingDependencies: string[]
  now: number
  lifted?: boolean
}

/** Contenu d'une carte, partagé entre le tableau et l'aperçu en cours de glisser. */
export function TaskCardBody({ task, pendingDependencies, now, lifted }: CardProps) {
  const main = task.operation_role === 'main' && task.status === 'in_progress'
  const overdue = isOverdue(task.due_at, now) && task.status !== 'done'
  return (
    <article
      className={clsx(
        'relative rounded-md border bg-surface px-3 py-2.5 text-left',
        main ? 'border-accent/60 bg-accent-soft/40' : 'border-line',
        lifted && 'rotate-[0.6deg] scale-[1.02] shadow-xl shadow-black/15',
      )}
    >
      {main && (
        <span aria-hidden className="absolute inset-y-2 left-0 w-[3px] rounded-r bg-accent" />
      )}
      <h3 className="font-display text-sm leading-snug font-semibold">{task.title}</h3>
      {main && <p className="mt-0.5 text-2xs font-medium text-accent">Opération principale</p>}
      {task.status === 'blocked' && task.block_cause && (
        <p className="mt-1 text-xs text-attention">Bloqué : {task.block_cause}</p>
      )}
      <p className="mt-1 line-clamp-2 text-xs text-muted">{task.objective}</p>
      {task.next_action && (
        <p className="mt-1 line-clamp-2 text-xs">
          <span className="text-muted">Ensuite : </span>
          {task.next_action}
        </p>
      )}
      <footer className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-2xs text-muted">
        {task.lead_agent && <AgentMark actor={task.lead_agent} />}
        {task.collaborators.map((actor) => (
          <AgentMark key={actor} actor={actor} />
        ))}
        {(task.priority === 'high' || task.priority === 'critical') && (
          <span className={clsx('font-medium', task.priority === 'critical' && 'text-danger')}>
            {PRIORITY_LABEL[task.priority]}
          </span>
        )}
        {task.due_at && (
          <span className={clsx(overdue && 'font-medium text-danger')}>
            {overdue ? 'En retard' : 'Échéance'} {formatShortDate(task.due_at)}
          </span>
        )}
        {pendingDependencies.length > 0 && (
          <span className="text-attention">
            Attend {pendingDependencies.length === 1 ? '1 tâche' : `${pendingDependencies.length} tâches`}
          </span>
        )}
        {task.expected_evidence && task.evidence.length === 0 && task.status !== 'done' && (
          <span>Preuve attendue</span>
        )}
        <span className="ml-auto tabular-nums">{task.id.replace('nx-task-', '#')}</span>
      </footer>
    </article>
  )
}

export function TaskCard({
  task,
  pendingDependencies,
  now,
  onOpen,
}: CardProps & { onOpen: (id: string) => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: task.id,
    data: { status: task.status satisfies Status },
  })
  return (
    <li>
      <button
        ref={setNodeRef}
        type="button"
        onClick={() => onOpen(task.id)}
        className={clsx(
          'block w-full cursor-grab rounded-md active:cursor-grabbing',
          isDragging && 'opacity-30',
        )}
        aria-label={`${task.title} — ouvrir ou déplacer`}
        {...attributes}
        {...listeners}
      >
        <TaskCardBody task={task} pendingDependencies={pendingDependencies} now={now} />
      </button>
    </li>
  )
}
