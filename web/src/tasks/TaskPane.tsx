import clsx from 'clsx'
import { toast } from 'sonner'
import { useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, type Actor, type Priority, type Status, type Task, type TaskChanges } from '@/api'
import { formatDateTime, isoToLocalInput, localInputToIso } from '@/format'
import { listProvenance, type Provenanced } from '@/freshness'
import { Provenance } from '@/Provenance'
import { AgentMark, Button, Field, inputClass } from '@/ui'
import { MoveDialog } from './MoveDialog'
import {
  ACTIVE_STATUSES,
  dependencyBlock,
  dependencyCandidates,
  dependencyRefusal,
  moveNeeds,
  needsPrompt,
  TRANSITIONS,
} from './moves'
import {
  useAddComment,
  useAttachEvidence,
  useComments,
  useHistory,
  useLink,
  useMoveTask,
  useUpdateTask,
} from './queries'
import { describeHistory } from './history'
import { ACTOR_NAME, ACTORS, actorName, PRIORITY_LABEL, ROLE_LABEL, STATUS_LABEL } from './vocabulary'

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

/** « Suite de nx-task-N — titre » : mène à la tâche que celle-ci prolonge. */
function FollowsLine({ follows, tasks, onOpen }: { follows: string; tasks: Task[]; onOpen: (id: string) => void }) {
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
function ClosedSection({ task, tasks, onOpen, onFollowUp }: {
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

function EvidenceList({ evidence }: { evidence: string[] }) {
  return (
    <ul className="grid gap-1 text-xs">
      {evidence.map((ref) => (
        <li key={ref} className="break-all">{ref}</li>
      ))}
    </ul>
  )
}

/** Longueur maximale d'une preuve (EVIDENCE_REF_MAX côté serveur), mesurée après dépouillement. */
const EVIDENCE_MAX = 512

/** Preuves d'une tâche terminée, toujours affichées, et « Joindre une preuve » (ajout seul). */
function EvidenceSection({ task }: { task: Task }) {
  const attach = useAttachEvidence(task.id)
  const [text, setText] = useState('')
  // Une preuve par ligne : une virgule appartient à la preuve (un lien peut en contenir).
  const refs = text.split('\n').map((line) => line.trim()).filter(Boolean)
  const tooLong = refs.some((ref) => ref.length > EVIDENCE_MAX)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (refs.length === 0 || tooLong || attach.isPending) return
    attach.mutate(refs, { onSuccess: () => setText('') })
  }

  return (
    <Section title="Preuves">
      {task.evidence.length > 0 ? (
        <EvidenceList evidence={task.evidence} />
      ) : (
        <p className="text-xs text-muted">
          {task.expected_evidence ? `Preuve attendue : ${task.expected_evidence} — aucune preuve jointe` : 'Aucune preuve jointe.'}
        </p>
      )}
      <form onSubmit={submit} className="mt-3 grid gap-2">
        <textarea
          className={inputClass}
          rows={2}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            attach.reset()
          }}
          placeholder="Une preuve par ligne, par exemple commit:a1b2c3d"
          aria-label="Joindre une preuve"
        />
        <div className="flex items-center justify-end gap-3">
          {tooLong && <p className="text-xs text-danger">Une preuve ne dépasse pas {EVIDENCE_MAX} caractères.</p>}
          <Button type="submit" disabled={refs.length === 0 || tooLong || attach.isPending}>
            Joindre
          </Button>
        </div>
        {attach.isError && (
          <p role="alert" className="text-xs text-danger">
            {attach.error instanceof ApiError ? attach.error.message : 'Le serveur Nexus ne répond pas.'}
          </p>
        )}
      </form>
    </Section>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-line px-5 py-4">
      <h3 className="mb-2.5 font-orbital-display text-xs font-semibold uppercase tracking-[0.18em] text-muted">{title}</h3>
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

function Dependencies({ task, tasks }: { task: Task; tasks: Task[] }) {
  const link = useLink(task.id)
  const [choice, setChoice] = useState('')
  const byId = new Map(tasks.map((t) => [t.id, t]))
  const candidates = dependencyCandidates(task, tasks)
  // La liste peut changer pendant qu'un choix est en attente (statut modifié par un agent) :
  // le choix fait partie du brouillon, il reste affiché avec la raison et bloque l'ajout.
  const refusal = choice ? dependencyRefusal(task, choice, tasks) : null
  // Une tâche terminée ne change plus ses dépendances (ADR-022) : ni « Retirer », ni ajout.
  const closed = task.status === 'done'

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
                {!closed && (
                  <Button variant="ghost" className="px-2 py-0.5 text-xs" onClick={() => link.mutate({ other: id, remove: true })}>
                    Retirer
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {(candidates.length > 0 || choice) && (
        <div className="mt-3 grid gap-1.5">
          <div className="flex gap-2">
            <select
              className={inputClass}
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
              aria-label="Tâche dont celle-ci dépend"
              aria-invalid={refusal ? true : undefined}
            >
              {/* Sur une tâche terminée, l'option vide sert à abandonner le choix, pas à en faire un. */}
              <option value="">{closed ? 'Abandonner ce choix' : 'Ajouter une dépendance…'}</option>
              {refusal && (
                <option value={choice}>{byId.get(choice)?.title ?? 'Tâche disparue'} — choix invalide</option>
              )}
              {candidates.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
            <Button
              disabled={!choice || refusal !== null}
              onClick={() => {
                link.mutate({ other: choice })
                setChoice('')
              }}
            >
              Ajouter
            </Button>
          </div>
          {refusal && (
            <p role="alert" className="text-xs text-danger">
              {refusal}
            </p>
          )}
        </div>
      )}
    </Section>
  )
}

/** Provenance d'une sous-liste (commentaires, historique) : son élément le plus ancien. */
function ListProvenance({ items, updatedAt }: { items: Provenanced[] | undefined; updatedAt: number }) {
  const provenance = items ? listProvenance(items, 'tasks', updatedAt) : null
  return provenance ? (
    <p className="mb-2">
      <Provenance source={provenance.source} measuredAt={provenance.measuredAt} kind="tasks" />
    </p>
  ) : null
}

/** Chargement, échec ou données non à jour d'une section de détail (ADR-005 : jamais de vide muet). */
function LoadState({ query, what, label }: {
  query: { isPending: boolean; isError: boolean; data: unknown }
  what: string
  label: string
}) {
  if (query.isPending) return <p className="text-xs text-muted">Chargement…</p>
  if (query.isError && !query.data)
    return <p className="text-xs text-danger">Impossible de lire {what} : le serveur Nexus ne répond pas.</p>
  if (query.isError)
    return (
      <p role="status" className="mb-2 text-xs text-attention">
        {label} non à jour : le dernier rafraîchissement a échoué.
      </p>
    )
  return null
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
      <LoadState query={comments} what="les commentaires" label="Commentaires" />
      <ListProvenance items={comments.data} updatedAt={comments.dataUpdatedAt} />
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

function History({ id }: { id: string }) {
  const history = useHistory(id)
  return (
    <Section title="Historique">
      <LoadState query={history} what="l’historique" label="Historique" />
      <ListProvenance items={history.data} updatedAt={history.dataUpdatedAt} />
      <ol className="grid gap-1.5 text-xs">
        {history.data
          ?.slice()
          .reverse()
          .map((entry) => (
            <li key={entry.id} className="flex gap-2">
              <span className="w-28 shrink-0 text-muted tabular-nums">{formatDateTime(entry.at)}</span>
              <span>
                {actorName(entry.actor)} {describeHistory(entry)}
              </span>
            </li>
          ))}
      </ol>
    </Section>
  )
}
