import clsx from 'clsx'
import { useState, type FormEvent, type ReactNode } from 'react'
import type { Actor, Priority, Task, TaskChanges } from '@/api'
import { formatDateTime, isoToLocalInput, localInputToIso } from '@/format'
import { AgentMark, Button, Field, inputClass } from '@/ui'
import { ACTIVE_STATUSES } from './moves'
import { useUpdateTask } from './queries'
import { Section } from './TaskPaneSection'
import { ACTOR_NAME, ACTORS, actorName, PRIORITY_LABEL } from './vocabulary'

type Draft = {
  title: string
  objective: string
  next_action: string
  lead_agent: string
  collaborators: Actor[]
  priority: Priority
  due_at: string
  follow_up_at: string
  expected_evidence: string
}

function draftFrom(task: Task): Draft {
  return {
    title: task.title,
    objective: task.objective,
    next_action: task.next_action ?? '',
    lead_agent: task.lead_agent ?? '',
    collaborators: task.collaborators,
    priority: task.priority,
    due_at: isoToLocalInput(task.due_at),
    follow_up_at: isoToLocalInput(task.follow_up_at),
    expected_evidence: task.expected_evidence ?? '',
  }
}

function toChange(key: keyof Draft, form: Draft): TaskChanges {
  switch (key) {
    case 'title':
    case 'objective':
      return { [key]: form[key].trim() }
    case 'next_action':
    case 'expected_evidence':
      return { [key]: form[key].trim() || null }
    case 'lead_agent':
      return { lead_agent: (form.lead_agent || null) as Actor | null }
    case 'due_at':
    case 'follow_up_at':
      return { [key]: localInputToIso(form[key]) }
    default:
      return { [key]: form[key] }
  }
}

/** La ligne de #70, partagée par le formulaire et le résumé : elle n'apparaît qu'une fois. */
function LeadLine({ task }: { task: Task }) {
  return (
    <p className="text-sm">
      {task.lead_agent ? `Agent principal : ${actorName(task.lead_agent)}` : 'Aucun agent principal'}
    </p>
  )
}

/** Résumé en lecture d'une tâche terminée : pas de champ, donc rien où le clavier s'arrête. */
function ClosedDetails({ task }: { task: Task }) {
  const rows: [string, ReactNode][] = [
    ['Titre', task.title],
    ['Objectif', task.objective],
    ['Collaborateurs', task.collaborators.length ? task.collaborators.map(actorName).join(', ') : 'Aucun'],
    ['Priorité', PRIORITY_LABEL[task.priority]],
    ['Échéance', task.due_at ? formatDateTime(task.due_at) : 'Aucune'],
    ['Relance', task.follow_up_at ? formatDateTime(task.follow_up_at) : 'Aucune'],
    ['Preuve attendue', task.expected_evidence || 'Aucune'],
  ]
  return (
    <Section title="Détails">
      <div className="grid gap-3">
        <LeadLine task={task} />
        <dl className="grid gap-2 text-xs">
          {rows.map(([label, value]) => (
            <div key={label}>
              <dt className="font-orbital-display text-2xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</dt>
              <dd className="mt-0.5 whitespace-pre-wrap">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-2xs text-muted">
          Propriétaire : {ACTOR_NAME[task.human_owner]}. Créée par {ACTOR_NAME[task.created_by]} le{' '}
          {formatDateTime(task.created_at)}.
        </p>
      </div>
    </Section>
  )
}

export function EditForm({ task }: { task: Task }) {
  const update = useUpdateTask()
  // `base` : la version de la tâche sur laquelle le brouillon a été commencé. On n'envoie que
  // les champs que Loïc a touchés, pour ne pas écraser ce qu'un agent a changé entre-temps.
  const [base, setBase] = useState(() => draftFrom(task))
  const [form, setForm] = useState(base)
  const [seen, setSeen] = useState(task.updated_at)
  const [changedElsewhere, setChangedElsewhere] = useState(false)
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const edited = (Object.keys(form) as (keyof Draft)[]).filter(
    (key) => JSON.stringify(form[key]) !== JSON.stringify(base[key]),
  )
  const dirty = edited.length > 0

  // La tâche a changé ailleurs (rafraîchissement, agent) : sans brouillon en cours, on suit ;
  // avec un brouillon, on le garde et on le signale.
  if (task.updated_at !== seen) {
    setSeen(task.updated_at)
    if (dirty) {
      setChangedElsewhere(true)
    } else {
      const next = draftFrom(task)
      setBase(next)
      setForm(next)
      setChangedElsewhere(false)
    }
  } else if (!dirty && changedElsewhere) {
    // Loïc a annulé ses modifications après un changement extérieur : on rejoint la tâche.
    const next = draftFrom(task)
    setBase(next)
    setForm(next)
    setChangedElsewhere(false)
  }

  const changes = Object.assign({}, ...edited.map((key) => toChange(key, form))) as TaskChanges
  // Mêmes exigences que le serveur : on ne propose pas d'enregistrer ce qu'il refusera.
  // Ce que la tâche vaudra après enregistrement : les champs touchés viennent du brouillon,
  // les autres de la dernière version connue (un agent a pu les remplir entre-temps).
  const latest = draftFrom(task)
  const after = <K extends keyof Draft>(key: K): Draft[K] =>
    edited.includes(key) ? form[key] : latest[key]
  const closed = task.status === 'done'
  const problem = closed
    ? 'Cette tâche vient d’être terminée : tes modifications ne peuvent plus être enregistrées. Copie-les dans un commentaire ou une tâche de suite.'
    : !after('title').trim()
      ? 'Le titre ne peut pas être vide.'
      : !after('objective').trim()
        ? "L'objectif ne peut pas être vide."
        : ACTIVE_STATUSES.includes(task.status) && !after('next_action').trim()
          ? 'Une tâche active doit garder une prochaine action.'
          : task.status === 'blocked' && !after('follow_up_at') && !task.block_plan?.trim()
            ? 'Un blocage garde une relance ou ce qui le débloquerait.'
            : null

  function abandon() {
    const next = draftFrom(task)
    setBase(next)
    setForm(next)
    setChangedElsewhere(false)
  }

  function save(event: FormEvent) {
    event.preventDefault()
    if (!dirty || problem) return
    const saved = form
    update.mutate(
      { id: task.id, changes },
      {
        onSuccess: () => {
          setBase(saved)
          setChangedElsewhere(false)
        },
      },
    )
  }

  // Une tâche terminée sans brouillon se lit ; avec un brouillon, il reste affiché (jamais jeté).
  if (closed && !dirty) return <ClosedDetails task={task} />

  return (
    <form onSubmit={save}>
      <Section title="Détails">
        <div className="grid gap-3">
          <LeadLine task={task} />
          <Field label="Titre">
            <input className={inputClass} maxLength={200} value={form.title} onChange={(e) => set('title', e.target.value)} />
          </Field>
          <Field label="Objectif">
            <textarea className={inputClass} rows={2} value={form.objective} onChange={(e) => set('objective', e.target.value)} />
          </Field>
          <Field label="Prochaine action">
            <textarea className={inputClass} rows={2} value={form.next_action} onChange={(e) => set('next_action', e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Agent principal">
              <select className={inputClass} value={form.lead_agent} onChange={(e) => set('lead_agent', e.target.value)}>
                <option value="">Personne</option>
                {ACTORS.map((a) => (
                  <option key={a} value={a}>{ACTOR_NAME[a]}</option>
                ))}
              </select>
            </Field>
            <Field label="Priorité">
              <select className={inputClass} value={form.priority} onChange={(e) => set('priority', e.target.value as Priority)}>
                {(Object.keys(PRIORITY_LABEL) as Priority[]).map((p) => (
                  <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>
                ))}
              </select>
            </Field>
            <Field label="Échéance">
              <input type="datetime-local" className={inputClass} value={form.due_at} onChange={(e) => set('due_at', e.target.value)} />
            </Field>
            <Field label="Relance">
              <input type="datetime-local" className={inputClass} value={form.follow_up_at} onChange={(e) => set('follow_up_at', e.target.value)} />
            </Field>
          </div>
          <fieldset className="grid gap-1">
            <legend className="mb-1 font-orbital-display text-xs font-semibold uppercase tracking-[0.14em] text-muted">Collaborateurs</legend>
            <div className="flex flex-wrap gap-1.5">
              {ACTORS.filter((a) => a !== 'loic').map((actor) => {
                const on = form.collaborators.includes(actor)
                return (
                  <button
                    key={actor}
                    type="button"
                    aria-pressed={on}
                    onClick={() =>
                      set('collaborators', on ? form.collaborators.filter((a) => a !== actor) : [...form.collaborators, actor])
                    }
                    className={clsx(
                      'rounded-full border px-2 py-0.5 transition-colors duration-100 hover:bg-ink/10',
                      on ? 'border-ink bg-sunken' : 'border-line-strong',
                    )}
                  >
                    <AgentMark actor={actor} withName />
                  </button>
                )
              })}
            </div>
          </fieldset>
          <Field label="Preuve attendue" hint="Si elle est renseignée, la tâche ne se clôt pas sans preuve.">
            <input className={inputClass} value={form.expected_evidence} onChange={(e) => set('expected_evidence', e.target.value)} />
          </Field>
          <p className="text-2xs text-muted">
            Propriétaire : {ACTOR_NAME[task.human_owner]}. Créée par {ACTOR_NAME[task.created_by]} le{' '}
            {formatDateTime(task.created_at)}.
          </p>
          <div className="flex items-center justify-end gap-3">
            {dirty && problem && <p className="text-xs text-danger">{problem}</p>}
            {dirty && !problem && changedElsewhere && (
              <p className="text-xs text-attention">
                Modifiée ailleurs pendant ta saisie : seuls les champs que tu as changés seront
                enregistrés.
              </p>
            )}
            {closed && (
              <Button variant="ghost" onClick={abandon}>
                Abandonner le brouillon
              </Button>
            )}
            <Button type="submit" variant="primary" disabled={!dirty || !!problem || update.isPending}>
              Enregistrer
            </Button>
          </div>
        </div>
      </Section>
    </form>
  )
}
