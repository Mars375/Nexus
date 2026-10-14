import { useState, type FormEvent } from 'react'
import type { Status, StatusChange, Task } from '@/api'
import { formatDateTime, localInputToIso } from '@/format'
import { Button, Dialog, Field, inputClass } from '@/ui'
import { canMove, moveNeeds } from './moves'
import { useMoveTask } from './queries'
import { STATUS_LABEL } from './vocabulary'

/** Demande ce que la règle exige avant un déplacement (blocage, abandon, prochaine action…). */
export function MoveDialog({
  task: opened,
  to,
  all,
  onClose,
}: {
  task: Task
  to: Status
  all: Task[]
  onClose: () => void
}) {
  // La tâche a pu changer depuis l'ouverture (agent, autre fenêtre) : on relit la version courante.
  const task = all.find((t) => t.id === opened.id) ?? opened
  const needs = moveNeeds(task, to, all)
  const stale = canMove(task.status, to)
    ? null
    : task.status === 'done'
      ? 'Cette tâche vient d’être terminée : ce passage n’est plus possible.'
      : 'Cette tâche a changé de statut : ce passage n’est plus possible.'
  const move = useMoveTask()
  const [nextAction, setNextAction] = useState('')
  const [cause, setCause] = useState('')
  const [plan, setPlan] = useState('')
  const [followUp, setFollowUp] = useState('')
  const [reason, setReason] = useState('')
  const [evidence, setEvidence] = useState('')

  // Le serveur reprend la relance déjà posée sur la tâche : pas besoin de la ressaisir.
  const blockReady = cause.trim() && (plan.trim() || followUp || task.follow_up_at)
  const ready =
    !stale &&
    (!needs.nextAction || nextAction.trim()) &&
    (!needs.block || blockReady) &&
    (!needs.reason || reason.trim())

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!ready) return
    const change: StatusChange = { status: to }
    if (needs.mainTaken) change.role = 'auxiliary'
    if (needs.nextAction) change.next_action = nextAction.trim()
    if (needs.block) {
      change.block_cause = cause.trim()
      if (plan.trim()) change.block_plan = plan.trim()
      const iso = localInputToIso(followUp)
      if (iso) change.follow_up_at = iso
    }
    if (needs.reason) change.reason = reason.trim()
    const refs = evidence.split('\n').map((s) => s.trim()).filter(Boolean)
    if (refs.length) change.evidence = refs
    move.mutate({ id: task.id, change })
    onClose()
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Passer « ${task.title} » en ${STATUS_LABEL[to].toLowerCase()}`}
      description={
        needs.mainTaken
          ? 'Une autre opération principale est déjà en cours : celle-ci démarrera comme auxiliaire.'
          : needs.evidence
          ? 'Cette tâche attend une preuve. Sans preuve, elle ira « À vérifier ».'
          : undefined
      }
    >
      <form onSubmit={submit} className="grid gap-3">
        {stale && (
          <p role="alert" className="text-xs text-danger">
            {stale}
          </p>
        )}
        {needs.nextAction && (
          <Field label="Prochaine action" hint="Une tâche active dit toujours ce qui vient ensuite.">
            <textarea
              className={inputClass}
              rows={2}
              value={nextAction}
              onChange={(e) => setNextAction(e.target.value)}
              autoFocus
            />
          </Field>
        )}
        {needs.block && (
          <>
            <Field label="Ce qui bloque">
              <input className={inputClass} value={cause} onChange={(e) => setCause(e.target.value)} autoFocus />
            </Field>
            <Field label="Ce qui débloquerait" hint="Ou une date de relance, au choix.">
              <input className={inputClass} value={plan} onChange={(e) => setPlan(e.target.value)} />
            </Field>
            <Field
              label="Relance prévue"
              hint={task.follow_up_at ? `Déjà prévue le ${formatDateTime(task.follow_up_at)} : laisse vide pour la garder.` : undefined}
            >
              <input
                type="datetime-local"
                className={inputClass}
                value={followUp}
                onChange={(e) => setFollowUp(e.target.value)}
              />
            </Field>
          </>
        )}
        {needs.reason && (
          <Field label="Pourquoi abandonner cette tâche ?">
            <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
          </Field>
        )}
        {to === 'done' && (
          <Field
            label="Preuves"
            hint={task.expected_evidence ? `Attendu : ${task.expected_evidence}` : 'Commit, fichier, lien… une par ligne.'}
          >
            <textarea
              className={inputClass}
              rows={2}
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
              placeholder="commit:a1b2c3d"
            />
          </Field>
        )}
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Annuler
          </Button>
          <Button type="submit" variant="primary" disabled={!ready}>
            Déplacer en {STATUS_LABEL[to].toLowerCase()}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
