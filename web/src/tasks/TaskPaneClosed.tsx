import type { Task } from '@/api'
import { Button } from '@/ui'
import { Section } from './TaskPaneSection'
import { STATUS_LABEL } from './vocabulary'

/** « Suite de nx-task-N — titre » : mène à la tâche que celle-ci prolonge. */
export function FollowsLine({ follows, tasks, onOpen }: { follows: string; tasks: Task[]; onOpen: (id: string) => void }) {
  const followed = tasks.find((t) => t.id === follows)
  return (
    <p className="border-b border-line px-5 py-2 text-xs">
      <button type="button" className="text-left underline decoration-line-strong underline-offset-2 hover:text-accent" onClick={() => onOpen(follows)}>
        Suite de {follows}
        {followed && ` — ${followed.title}`}
      </button>
    </p>
  )
}

/** Tâche terminée : plus d'avancement ; on ouvre une suite (ADR-022). */
export function ClosedSection({ task, tasks, onOpen, onFollowUp }: {
  task: Task
  tasks: Task[]
  onOpen: (id: string) => void
  onFollowUp: (id: string) => void
}) {
  // Calculé sur la liste complète : le serveur ne renvoie que le lien de la tâche qui suit.
  const followedBy = tasks.filter((t) => t.follows === task.id)
  return (
    <Section title="Terminée">
      <p className="text-xs">Cette tâche ne se modifie plus. Un problème trouvé ensuite se règle dans une tâche de suite.</p>
      <Button className="mt-3" onClick={() => onFollowUp(task.id)}>
        Ouvrir une tâche de suite
      </Button>
      {followedBy.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-muted">Suivie par :</p>
          <ul className="mt-1 grid gap-1">
            {followedBy.map((t) => (
              <li key={t.id}>
                <button type="button" className="text-left text-xs underline decoration-line-strong underline-offset-2 hover:text-accent" onClick={() => onOpen(t.id)}>
                  {t.title}
                  <span className="text-muted"> — {STATUS_LABEL[t.status]}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  )
}
