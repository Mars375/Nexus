import { useEffect, useRef, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { ApiError, type Actor, type Task } from '@/api'
import { useAuth } from '@/auth'
import { Button, Dialog, Field, inputClass } from '@/ui'
import { actorName } from '@/tasks/vocabulary'
import { newClientKey, useDispatchRun, useExecutors } from './queries'
import { defaultModel, HANDOVER_CLOSED, modelLabel, modelName, refusalText } from './vocabulary'

export const BRIEF_MAX = 20_000

/** « Confier à » : hands a task to an agent. This starts a language model: the dialog says so. */
export function ConfierDialog({ task, onClose }: { task: Task; onClose: () => void }) {
  const executors = useExecutors(true)
  const dispatch = useDispatchRun(task.id)
  const [executor, setExecutor] = useState<Actor | ''>('')
  const [agent, setAgent] = useState<Actor | ''>('')
  const [workdir, setWorkdir] = useState('')
  const [model, setModel] = useState('')
  const [brief, setBrief] = useState('')
  // One key per distinct request: a double click or a resend is the same run, an edited request
  // is a new one (the server refuses the same key for another content).
  const sent = useRef<{ signature: string; key: string } | null>(null)

  // A 401 is no longer true once the token is entered again: forget it on unlock.
  const { locked } = useAuth()
  const refusedAuth = dispatch.error instanceof ApiError && dispatch.error.status === 401
  const unlockable = useRef(false)
  unlockable.current = refusedAuth
  useEffect(() => {
    if (!locked && unlockable.current) dispatch.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only locked -> unlocked matters
  }, [locked])

  const list = executors.data ?? []
  // What Loïc chose stays what he chose: if the server no longer offers it, it stays on screen,
  // marked invalid, and blocks the sending (never replaced by another value in silence).
  const selected = executor || list[0]?.executor
  const info = list.find((e) => e.executor === selected)
  const executorGone = executor !== '' && executors.isSuccess && !info
  const agents = info?.agents ?? []
  const theAgent = agent || agents[0]
  const agentGone = !!theAgent && !!info && !agents.includes(theAgent)
  const workdirs = info?.workdirs ?? []
  const theWorkdir = workdir || workdirs[0]
  const workdirGone = workdir !== '' && !!info && !workdirs.includes(workdir)
  const models = info?.models ?? []
  // Sonnet until Loïc picks another; a pick the server no longer offers stays, marked, and blocks.
  const theModel = model || defaultModel(models)
  // The default shown is pinned as the choice once the models are known, so a later refresh of
  // the list cannot move the select to another model in silence: it becomes « plus disponible ».
  const pinned = model === '' && models.length > 0 ? defaultModel(models) : undefined
  useEffect(() => {
    if (pinned) setModel(pinned)
  }, [pinned])
  const modelGone = model !== '' && !!info && !models.includes(model)
  const gone = executorGone || agentGone || workdirGone || modelGone
  const closed = HANDOVER_CLOSED.includes(task.status)
  const showForm = !!info || executorGone
  const ready = showForm && !gone && !closed && !!theAgent && brief.trim().length > 0 && !dispatch.isPending

  // Editing a field makes a past refusal obsolete.
  const edit = <T,>(set: (value: T) => void) => (value: T) => {
    if (dispatch.isError && !dispatch.isPending) dispatch.reset()
    set(value)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!ready || !selected || !theAgent) return
    const text = brief.trim()
    const sendModel = models.length > 0 ? theModel : undefined
    const signature = JSON.stringify([selected, theAgent, theWorkdir ?? null, sendModel ?? null, text])
    if (sent.current?.signature !== signature) sent.current = { signature, key: newClientKey() }
    dispatch.mutate(
      {
        executor: selected, agent: theAgent, client_key: sent.current.key, brief: text,
        workdir: theWorkdir, ...(sendModel ? { model: sendModel } : {}),
      },
      {
        onSuccess: (run) => {
          toast.success(`Confié à ${actorName(run.agent)} (${run.id})`)
          onClose()
        },
      },
    )
  }

  const options = (values: string[], held: string | undefined, gone: boolean) => (
    <>
      {gone && held && <option value={held}>{actorName(held)} — plus disponible</option>}
      {values.map((v) => (
        <option key={v} value={v}>{actorName(v)}</option>
      ))}
    </>
  )
  const pending = dispatch.isPending

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Confier « ${task.title} »`}
      description="Un agent travaille sur cette tâche, dans un dossier à part."
    >
      <form onSubmit={submit} className="grid gap-3">
        {closed && (
          <p role="alert" className="text-xs text-danger">
            Cette tâche vient d’être {task.status === 'done' ? 'terminée' : 'abandonnée'} : elle ne peut plus être confiée.
          </p>
        )}
        {executors.isPending && <p className="text-xs text-muted">Chargement des exécutants…</p>}
        {executors.isError && (
          <p role="alert" className="text-xs text-danger">
            Impossible de lire les exécutants disponibles.
          </p>
        )}
        {executors.isSuccess && list.length === 0 && !executorGone && (
          <p role="alert" className="text-xs text-attention">
            Aucun exécutant n’est configuré sur ce serveur : rien ne peut être confié pour l’instant.
          </p>
        )}
        {gone && (
          <p role="alert" className="text-xs text-danger">
            Ce choix n’est plus proposé par le serveur : change-le pour continuer. Ton brief est gardé.
          </p>
        )}
        {showForm && (
          <>
            <Field label="Exécutant">
              <select
                className={inputClass}
                value={selected}
                disabled={pending}
                aria-invalid={executorGone || undefined}
                onChange={(e) => {
                  edit(setExecutor)(e.target.value as Actor)
                  setAgent('')
                  setWorkdir('')
                  setModel('')
                }}
                autoFocus
              >
                {executorGone && selected && <option value={selected}>{actorName(selected)} — plus disponible</option>}
                {list.map((e) => (
                  <option key={e.executor} value={e.executor}>{actorName(e.executor)}</option>
                ))}
              </select>
            </Field>
            <Field label="Agent" hint="Seuls les agents que cet exécutant sert sont proposés.">
              <select
                className={inputClass}
                value={theAgent}
                disabled={pending}
                aria-invalid={agentGone || undefined}
                onChange={(e) => edit(setAgent)(e.target.value as Actor)}
              >
                {options(agents, theAgent, agentGone || executorGone)}
              </select>
            </Field>
            {(workdirs.length > 0 || workdirGone) && (
              <Field label="Dossier de travail" hint="Un dépôt déclaré sur le serveur ; le travail se fait dans un worktree à part.">
                <select
                  className={inputClass}
                  value={theWorkdir}
                  disabled={pending}
                  aria-invalid={workdirGone || undefined}
                  onChange={(e) => edit(setWorkdir)(e.target.value)}
                >
                  {workdirGone && <option value={workdir}>{workdir} — plus disponible</option>}
                  {workdirs.map((w) => (
                    <option key={w} value={w}>{w}</option>
                  ))}
                </select>
              </Field>
            )}
            {(models.length > 0 || modelGone) && (
              <Field label="Modèle" hint="Choisi à chaque run : le plus capable consomme le plus.">
                <select
                  className={inputClass}
                  value={theModel}
                  disabled={pending}
                  aria-invalid={modelGone || undefined}
                  onChange={(e) => edit(setModel)(e.target.value)}
                >
                  {modelGone && <option value={model}>{modelName(model)} — plus disponible</option>}
                  {models.map((m) => (
                    <option key={m} value={m}>{modelLabel(m)}</option>
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
                readOnly={pending}
                onChange={(e) => edit(setBrief)(e.target.value)}
                required
              />
            </Field>
            <p className="rounded-sm border border-attention/50 px-3 py-2 text-xs text-attention">
              Lance un LLM : l’agent travaille réellement, consomme du quota et peut modifier des fichiers dans son
              worktree. Rien n’est poussé ni fusionné.
              {selected === 'claude' && ' Ce run consomme l’abonnement Claude de Loïc.'}
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
            {pending ? 'Envoi…' : 'Lancer l’agent'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
