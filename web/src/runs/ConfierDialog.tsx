import { useRef, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import type { Actor, Task } from '@/api'
import type { ExecutorInfo } from '@/runsApi'
import { Button, Dialog, Field, inputClass } from '@/ui'
import { actorName } from '@/tasks/vocabulary'
import { newClientKey, useDispatchRun, useExecutors } from './queries'
import { refusalText } from './vocabulary'

export const BRIEF_MAX = 20_000

/** « Confier à » : hands a task to an agent. This starts a language model: the dialog says so. */
export function ConfierDialog({ task, onClose }: { task: Task; onClose: () => void }) {
  const executors = useExecutors(true)
  const dispatch = useDispatchRun(task.id)
  const [executor, setExecutor] = useState<Actor | ''>('')
  const [agent, setAgent] = useState<Actor | ''>('')
  const [workdir, setWorkdir] = useState('')
  const [brief, setBrief] = useState('')
  // One key per distinct request: a double click or a resend is the same run, an edited request
  // is a new one (the server refuses the same key for another content).
  const sent = useRef<{ signature: string; key: string } | null>(null)

  const list = executors.data ?? []
  const chosen: ExecutorInfo | undefined = list.find((e) => e.executor === (executor || list[0]?.executor))
  const agents = chosen?.agents ?? []
  const theAgent = agent && agents.includes(agent) ? agent : agents[0]
  const theWorkdir = workdir && chosen?.workdirs.includes(workdir) ? workdir : chosen?.workdirs[0]
  const ready = chosen && theAgent && brief.trim().length > 0 && !dispatch.isPending

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!ready || !chosen || !theAgent) return
    const text = brief.trim()
    const signature = JSON.stringify([chosen.executor, theAgent, theWorkdir ?? null, text])
    if (sent.current?.signature !== signature) sent.current = { signature, key: newClientKey() }
    dispatch.mutate(
      { executor: chosen.executor, agent: theAgent, client_key: sent.current.key, brief: text, workdir: theWorkdir },
      {
        onSuccess: (run) => {
          toast.success(`Confié à ${actorName(run.agent)} (${run.id})`)
          onClose()
        },
      },
    )
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Confier « ${task.title} »`}
      description="Un agent travaille sur cette tâche, dans un dossier à part."
    >
      <form onSubmit={submit} className="grid gap-3">
        {executors.isPending && <p className="text-xs text-muted">Chargement des exécutants…</p>}
        {executors.isError && (
          <p role="alert" className="text-xs text-danger">
            Impossible de lire les exécutants disponibles.
          </p>
        )}
        {executors.isSuccess && list.length === 0 && (
          <p role="alert" className="text-xs text-attention">
            Aucun exécutant n’est configuré sur ce serveur : rien ne peut être confié pour l’instant.
          </p>
        )}
        {chosen && (
          <>
            <Field label="Exécutant">
              <select
                className={inputClass}
                value={chosen.executor}
                onChange={(e) => {
                  setExecutor(e.target.value as Actor)
                  setAgent('')
                  setWorkdir('')
                }}
                autoFocus
              >
                {list.map((e) => (
                  <option key={e.executor} value={e.executor}>{actorName(e.executor)}</option>
                ))}
              </select>
            </Field>
            <Field label="Agent" hint="Seuls les agents que cet exécutant sert sont proposés.">
              <select className={inputClass} value={theAgent} onChange={(e) => setAgent(e.target.value as Actor)}>
                {agents.map((a) => (
                  <option key={a} value={a}>{actorName(a)}</option>
                ))}
              </select>
            </Field>
            {chosen.workdirs.length > 0 && (
              <Field label="Dossier de travail" hint="Un dépôt déclaré sur le serveur ; le travail se fait dans un worktree à part.">
                <select className={inputClass} value={theWorkdir} onChange={(e) => setWorkdir(e.target.value)}>
                  {chosen.workdirs.map((w) => (
                    <option key={w} value={w}>{w}</option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="Brief" hint="Ce que l’agent doit faire, écrit par toi : il ne reprend ni les commentaires ni les notes d’agents.">
              <textarea
                className={inputClass}
                rows={5}
                value={brief}
                maxLength={BRIEF_MAX}
                onChange={(e) => setBrief(e.target.value)}
                required
              />
            </Field>
            <p className="rounded-sm border border-attention/50 px-3 py-2 text-xs text-attention">
              Lance un LLM : l’agent travaille réellement, consomme du quota et peut modifier des fichiers dans son
              worktree. Rien n’est poussé ni fusionné.
            </p>
          </>
        )}
        {dispatch.isError && (
          <p role="alert" className="text-xs text-danger">
            {refusalText(dispatch.error)}
          </p>
        )}
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Annuler
          </Button>
          <Button type="submit" variant="primary" disabled={!ready}>
            {dispatch.isPending ? 'Envoi…' : 'Lancer l’agent'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
