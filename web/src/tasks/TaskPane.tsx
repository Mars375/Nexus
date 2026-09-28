import clsx from 'clsx'
import { toast } from 'sonner'
import { useState, type FormEvent, type ReactNode } from 'react'
import type { Actor, HistoryEntry, Priority, Status, Task, TaskChanges } from '@/api'
import { formatDateTime, isoToLocalInput, localInputToIso } from '@/format'
import { AgentMark, Button, Field, inputClass } from '@/ui'
import { MoveDialog } from './MoveDialog'
import { ACTIVE_STATUSES, dependencyBlock, moveNeeds, needsPrompt, TRANSITIONS } from './moves'
import {
  useAddComment,
  useComments,
  useHistory,
  useLink,
  useMoveTask,
  useUpdateTask,
} from './queries'
import { ACTOR_NAME, ACTORS, PRIORITY_LABEL, ROLE_LABEL, STATUS_LABEL } from './vocabulary'

type Props = { task: Task; tasks: Task[]; onClose: () => void }

export function TaskPane({ task, tasks, onClose }: Props) {
  const [moving, setMoving] = useState<Status | null>(null)
  const move = useMoveTask()

  function requestMove(to: Status) {
    const waiting = dependencyBlock(task, to, tasks)
    if (waiting) {
      toast.error(waiting)
      return
    }
    if (needsPrompt(moveNeeds(task, to))) setMoving(to)
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
            <span className="tabular-nums">{task.id}</span>
            <span className="text-ink">{STATUS_LABEL[task.status]}</span>
            {task.status === 'in_progress' && task.operation_role && (
              <span className={task.operation_role === 'main' ? 'text-accent' : undefined}>
                {ROLE_LABEL[task.operation_role]}
              </span>
            )}
          </p>
          <h2 className="mt-0.5 font-display text-lg leading-tight font-semibold">{task.title}</h2>
        </div>
        <Button variant="ghost" onClick={onClose} aria-label="Fermer le détail">
          Fermer
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto">
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

        <EditForm key={task.id} task={task} />

        {task.evidence.length > 0 && (
          <Section title="Preuves">
            <ul className="grid gap-1 text-xs">
              {task.evidence.map((ref) => (
                <li key={ref} className="break-all">{ref}</li>
              ))}
            </ul>
          </Section>
        )}

        <Dependencies task={task} tasks={tasks} />
        <Comments id={task.id} />
        <History id={task.id} />
      </div>

      {moving && <MoveDialog task={task} to={moving} onClose={() => setMoving(null)} />}
    </aside>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-line px-5 py-4">
      <h3 className="mb-2.5 text-xs font-semibold text-muted">{title}</h3>
      {children}
    </section>
  )
}

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

function EditForm({ task }: { task: Task }) {
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
  const problem = !after('title').trim()
    ? 'Le titre ne peut pas être vide.'
    : !after('objective').trim()
      ? "L'objectif ne peut pas être vide."
      : ACTIVE_STATUSES.includes(task.status) && !after('next_action').trim()
        ? 'Une tâche active doit garder une prochaine action.'
        : task.status === 'blocked' && !after('follow_up_at') && !task.block_plan?.trim()
          ? 'Un blocage garde une relance ou ce qui le débloquerait.'
          : task.status === 'done' &&
            task.evidence.length === 0 &&
            edited.includes('expected_evidence') &&
            form.expected_evidence.trim()
          ? 'Cette tâche est terminée sans preuve : rouvre-la pour exiger une preuve.'
          : null

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

  return (
    <form onSubmit={save}>
      <Section title="Détails">
        <div className="grid gap-3">
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
            <legend className="mb-1 text-xs font-medium text-muted">Collaborateurs</legend>
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
                      'rounded-full border px-2 py-0.5 transition-colors duration-100',
                      on ? 'border-ink/40 bg-sunken' : 'border-line opacity-60 hover:opacity-100',
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
            <Button type="submit" variant="primary" disabled={!dirty || !!problem || update.isPending}>
              Enregistrer
            </Button>
          </div>
        </div>
      </Section>
    </form>
  )
}

function Dependencies({ task, tasks }: { task: Task; tasks: Task[] }) {
  const link = useLink(task.id)
  const [choice, setChoice] = useState('')
  const byId = new Map(tasks.map((t) => [t.id, t]))
  const candidates = tasks.filter((t) => t.id !== task.id && !task.depends_on.includes(t.id))

  return (
    <Section title="Dépend de">
      {task.depends_on.length === 0 ? (
        <p className="text-xs text-muted">Aucune dépendance.</p>
      ) : (
        <ul className="grid gap-1.5">
          {task.depends_on.map((id) => {
            const dep = byId.get(id)
            return (
              <li key={id} className="flex items-center gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate">
                  {dep ? dep.title : id}
                  <span className="text-muted"> — {dep ? STATUS_LABEL[dep.status] : 'inconnue'}</span>
                </span>
                <Button variant="ghost" className="px-2 py-0.5 text-xs" onClick={() => link.mutate({ other: id, remove: true })}>
                  Retirer
                </Button>
              </li>
            )
          })}
        </ul>
      )}
      {candidates.length > 0 && (
        <div className="mt-3 flex gap-2">
          <select className={inputClass} value={choice} onChange={(e) => setChoice(e.target.value)} aria-label="Tâche dont celle-ci dépend">
            <option value="">Ajouter une dépendance…</option>
            {candidates.map((t) => (
              <option key={t.id} value={t.id}>{t.title}</option>
            ))}
          </select>
          <Button
            disabled={!choice}
            onClick={() => {
              link.mutate({ other: choice })
              setChoice('')
            }}
          >
            Ajouter
          </Button>
        </div>
      )}
    </Section>
  )
}

function Comments({ id }: { id: string }) {
  const comments = useComments(id)
  const add = useAddComment(id)
  const [body, setBody] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!body.trim()) return
    add.mutate(body, { onSuccess: () => setBody('') })
  }

  return (
    <Section title="Commentaires">
      <ul className="grid gap-3">
        {comments.data?.map((c) => (
          <li key={c.id} className="text-xs">
            <p className="flex items-center gap-2 text-muted">
              <AgentMark actor={c.author} withName />
              <span>{formatDateTime(c.at)}</span>
            </p>
            <p className="mt-1 whitespace-pre-wrap">{c.body}</p>
          </li>
        ))}
        {comments.data?.length === 0 && <li className="text-xs text-muted">Aucun commentaire.</li>}
      </ul>
      <form onSubmit={submit} className="mt-3 grid gap-2">
        <textarea
          className={inputClass}
          rows={2}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Ajouter un commentaire"
          aria-label="Nouveau commentaire"
        />
        <div className="flex justify-end">
          <Button type="submit" disabled={!body.trim() || add.isPending}>
            Commenter
          </Button>
        </div>
      </form>
    </Section>
  )
}

function describe(entry: HistoryEntry): string {
  const c = entry.changes
  switch (entry.action) {
    case 'created':
      return 'a créé la tâche'
    case 'status': {
      const [from, to] = c.status as [Status, Status]
      return `l'a passée de ${STATUS_LABEL[from].toLowerCase()} à ${STATUS_LABEL[to].toLowerCase()}`
    }
    case 'updated':
      return `a modifié ${Object.keys(c).length > 1 ? 'plusieurs champs' : 'un champ'}`
    case 'commented':
      return 'a commenté'
    case 'linked':
      return 'a ajouté une dépendance'
    case 'unlinked':
      return 'a retiré une dépendance'
    case 'secret_redacted':
      return 'a collé un secret, masqué automatiquement'
    default:
      return entry.action
  }
}

function History({ id }: { id: string }) {
  const history = useHistory(id)
  return (
    <Section title="Historique">
      <ol className="grid gap-1.5 text-xs">
        {history.data
          ?.slice()
          .reverse()
          .map((entry) => (
            <li key={entry.id} className="flex gap-2">
              <span className="w-28 shrink-0 text-muted tabular-nums">{formatDateTime(entry.at)}</span>
              <span>
                {ACTOR_NAME[entry.actor]} {describe(entry)}
              </span>
            </li>
          ))}
      </ol>
    </Section>
  )
}
