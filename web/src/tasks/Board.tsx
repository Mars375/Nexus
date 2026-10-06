import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import clsx from 'clsx'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import type { Status, Task } from '@/api'
import { useNow } from '@/useNow'
import { MoveDialog } from './MoveDialog'
import { canMove, dependencyBlock, moveNeeds, needsPrompt } from './moves'
import { useMoveTask } from './queries'
import { TaskCard, TaskCardBody } from './TaskCard'
import { compareTasks, STATUS_LABEL } from './vocabulary'

type Props = {
  tasks: Task[]
  allTasks: Task[]
  statuses: Status[]
  onOpen: (id: string) => void
}

export function Board({ tasks, allTasks, statuses, onOpen }: Props) {
  const now = useNow(30_000)
  const move = useMoveTask()
  const [dragged, setDragged] = useState<Task | null>(null)
  const [pending, setPending] = useState<{ task: Task; to: Status } | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    // Espace pour saisir et poser une carte ; Entrée reste libre pour l'ouvrir.
    useSensor(KeyboardSensor, {
      keyboardCodes: { start: ['Space'], cancel: ['Escape'], end: ['Space'] },
    }),
  )

  const statusById = useMemo(() => new Map(allTasks.map((t) => [t.id, t.status])), [allTasks])
  const pendingDeps = (task: Task) =>
    task.depends_on.filter((id) => !['done', 'dropped'].includes(statusById.get(id) ?? ''))

  const columns = useMemo(
    () =>
      statuses.map((status) => ({
        status,
        tasks: tasks.filter((t) => t.status === status).sort(compareTasks),
      })),
    [tasks, statuses],
  )

  function onDragStart(event: DragStartEvent) {
    setDragged(tasks.find((t) => t.id === event.active.id) ?? null)
  }

  function onDragEnd(event: DragEndEvent) {
    const task = dragged
    setDragged(null)
    const to = event.over?.id as Status | undefined
    if (!task || !to || to === task.status) return
    if (!canMove(task.status, to)) {
      toast.error(`Une tâche ${STATUS_LABEL[task.status].toLowerCase()} ne peut pas passer en ${STATUS_LABEL[to].toLowerCase()}.`)
      return
    }
    const waiting = dependencyBlock(task, to, allTasks)
    if (waiting) {
      toast.error(waiting)
      return
    }
    if (needsPrompt(moveNeeds(task, to, allTasks))) {
      setPending({ task, to })
      return
    }
    move.mutate({ id: task.id, change: { status: to } })
  }

  return (
    <DndContext
      sensors={sensors}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setDragged(null)}
      accessibility={{
        screenReaderInstructions: {
          draggable:
            'Entrée ouvre la tâche. Pour la déplacer, appuie sur espace, déplace-la avec les flèches jusqu’à la colonne voulue, puis espace pour la poser ou Échap pour annuler. Le panneau de détail propose aussi des boutons de changement de statut.',
        },
      }}
    >
      <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto px-5 pb-5">
        {columns.map(({ status, tasks: columnTasks }) => (
          <Column
            key={status}
            status={status}
            count={columnTasks.length}
            dragging={dragged}
          >
            {columnTasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                pendingDependencies={pendingDeps(task)}
                now={now}
                onOpen={onOpen}
              />
            ))}
          </Column>
        ))}
      </div>
      <DragOverlay dropAnimation={{ duration: 180, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' }}>
        {dragged && (
          <TaskCardBody task={dragged} pendingDependencies={pendingDeps(dragged)} now={now} lifted />
        )}
      </DragOverlay>
      {pending && (
        <MoveDialog
          task={pending.task}
          to={pending.to}
          all={allTasks}
          onClose={() => setPending(null)}
        />
      )}
    </DndContext>
  )
}

function Column({
  status,
  count,
  dragging,
  children,
}: {
  status: Status
  count: number
  dragging: Task | null
  children: React.ReactNode
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status })
  const allowed = !dragging || dragging.status === status || canMove(dragging.status, status)
  return (
    <section
      ref={setNodeRef}
      aria-label={STATUS_LABEL[status]}
      className={clsx(
        'flex min-w-48 max-w-80 flex-1 basis-0 flex-col border border-line bg-sunken transition-[opacity,box-shadow] duration-150',
        dragging && !allowed && 'opacity-40',
        isOver && allowed && dragging?.status !== status && 'ring-2 ring-accent',
      )}
    >
      <header className="flex items-baseline gap-2 px-3 pt-3 pb-1">
        <h2 className="font-orbital-display text-xs font-semibold uppercase tracking-[0.18em]">{STATUS_LABEL[status]}</h2>
        <span className="font-data text-xs text-muted tabular-nums">{count}</span>
      </header>
      {/* pt-1 (header pb-1): room for the 4 px focus ring of the first card, which overflow-y-auto would clip. */}
      <ul className="flex min-h-16 flex-1 flex-col gap-2 overflow-y-auto px-2 pt-1 pb-2">
        {children}
        {count === 0 && (
          <li className="px-1 py-3 text-xs text-muted">Aucune tâche.</li>
        )}
      </ul>
    </section>
  )
}
