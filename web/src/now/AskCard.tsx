import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { ApiError, approvalsApi, type NowApproval, type NowAsk } from '@/api'
import { age, formatDateTime, until } from '@/format'
import { Button, inputClass } from '@/ui'
import { EMPTY_DRAFT, hasDraft, type AskDraft } from './askDrafts'
import { displayName } from './model'
import { nowKey } from './queries'

/** Same limits as the server (EVENT-PROTOCOL §6 ter). */
export const ANSWER_MAX = 2000
export const NOTE_MAX = 2000

const CHIP_TEXT = { pending: 'en attente', approved: 'validée', rejected: 'refusée', answered: 'répondue', expired: 'expirée' } as const
const TREATED_TEXT = { approved: 'Validée', rejected: 'Refusée', answered: 'Répondue' } as const

const UNREACHABLE = 'Le serveur Nexus ne répond pas. Ta saisie est conservée : réessaie dans un instant.'

/** Message shown under the form: the server's French text, never a value Loïc typed. */
const errorText = (e: unknown): string => (e instanceof ApiError ? e.message : UNREACHABLE)

type Props = {
  ask: NowAsk
  now: number
  fresh: boolean
  draft: AskDraft | undefined
  onDraft: (ref: string, change: Partial<AskDraft>) => void
  /** Drops the draft of an approval: after a successful send, or when Loïc discards it. */
  onSent: (ref: string) => void
}

/** One request received by Loïc: state, detail on demand, and the form to answer it while it waits. */
export function AskCard({ ask, now, fresh, draft = EMPTY_DRAFT, onDraft, onSent }: Props) {
  const client = useQueryClient()
  const id = useId()
  const [open, setOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The last send got no answer from the server: it may have been recorded all the same.
  const [unsure, setUnsure] = useState(false)
  const alertRef = useRef<HTMLParagraphElement>(null)
  const statusRef = useRef<HTMLParagraphElement>(null)
  const inFlight = useRef(false) // two clicks in the same tick must send one request

  const approval = ask.approval
  const status = approval?.status ?? null
  const pending = status === 'pending'
  const isQuestion = ask.kind === 'question'
  const entries = ask.options.map((text, index) => ({ text, index })).filter((o) => o.text.trim() !== '')
  const choiceRequired = !isQuestion && entries.length >= 2
  const stale = approval !== null && !pending && hasDraft(draft) && !sent
  const formShown = approval !== null && !sent && (pending || stale)
  const editable = pending && !sending

  async function send(run: () => Promise<unknown>) {
    if (inFlight.current || !approval) return
    inFlight.current = true
    setSending(true)
    setError(null)
    setUnsure(false)
    try {
      await run()
      // Stay "sending" until Maintenant has been read again: the form never reopens on the old state.
      await client.invalidateQueries({ queryKey: nowKey })
      setSent(true)
      onSent(approval.ref)
    } catch (e) {
      setError(errorText(e))
      // No answer from the server (timeout, network): the request may have been recorded.
      setUnsure(!(e instanceof ApiError))
      // Whatever went wrong, read the ask again: its real state is the only source of truth.
      await client.invalidateQueries({ queryKey: nowKey })
    } finally {
      inFlight.current = false
      setSending(false)
    }
  }

  // Keyboard and screen-reader users land on what just happened.
  useEffect(() => { if (error) alertRef.current?.focus() }, [error])
  useEffect(() => { if (sent) statusRef.current?.focus() }, [sent])

  const submitAnswer = (e: FormEvent) => {
    e.preventDefault()
    if (approval && pending && draft.text.trim() !== '') void send(() => approvalsApi.answer(approval.ref, draft.text))
  }
  const decide = (decision: 'approved' | 'rejected') => {
    if (!approval || !pending) return
    const note = draft.note.trim() === '' ? undefined : draft.note
    // A choice only goes with an approval: refusing never "picks" an option.
    const choice = decision === 'approved' && draft.choice !== null ? draft.choice : undefined
    void send(() => approvalsApi.decide(approval.ref, { decision, ...(choice !== undefined && { choice }), ...(note !== undefined && { note }) }))
  }

  const canAnswer = editable && draft.text.trim() !== ''
  const canApprove = editable && !(choiceRequired && draft.choice === null)
  const reasonId = `${id}-reason`

  return (
    <article
      data-ask={ask.event}
      data-state={status ?? 'unknown'}
      className={clsx('mb-1.5 min-w-0 max-w-full border-l-2 px-3 py-2', pending ? 'border-attention' : 'border-line-strong', fresh ? 'now-fresh' : pending && 'bg-attention-soft')}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="m-0 min-w-0 text-[13px]">
          <button type="button" aria-expanded={open} aria-controls={`${id}-detail`} onClick={() => setOpen((o) => !o)}
            className="flex w-full min-w-0 items-baseline gap-1.5 bg-transparent p-0 text-left font-semibold text-ink">
            <span aria-hidden className="font-data text-[11px] text-muted">{open ? '▾' : '▸'}</span>
            <span className="min-w-0 [overflow-wrap:anywhere]">{ask.subject}</span>
          </button>
        </h3>
        <span className="shrink-0 font-data text-[11px] text-muted">{age(ask.received_at, now)}</span>
      </div>
      <div className="mt-0.5 flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs text-muted">
        <span>
          {isQuestion ? 'Question' : 'Demande de validation'} de {displayName(ask.agent)}{' '}
          {ask.task ? <>sur <a href={`#/travail/${ask.task}`}>{ask.task}</a></> : 'sur aucune tâche'}.
        </span>
        <Chip approval={approval} agent={ask.agent} />
        {pending && approval?.expires_at && <span className="font-data text-[11px]">expire {until(approval!.expires_at!, now)}</span>}
      </div>
      {/* Always mounted, so a change of its text is announced (sending, sent, treated elsewhere). */}
      <p ref={statusRef} tabIndex={-1} aria-live="polite"
        className={clsx('m-0 text-xs', (stale || sent) && 'mt-1.5', stale && 'border border-attention bg-attention-soft px-2 py-1 text-ink [overflow-wrap:anywhere]', !stale && 'text-muted')}>
        {sending ? 'Envoi…' : sent ? (isQuestion ? 'Réponse envoyée.' : 'Décision envoyée.') : stale ? staleText(approval, isQuestion, unsure) : ''}
      </p>
      {open && (
        <div id={`${id}-detail`} className="mt-2 grid grid-cols-[minmax(0,1fr)] gap-2.5">
          {ask.body && <p className="m-0 whitespace-pre-wrap text-xs text-ink [overflow-wrap:anywhere]">{ask.body}</p>}
          {!isQuestion && !formShown && <Consequence ask={ask} />}
          {approval === null && <p className="m-0 text-xs text-muted">{ask.agent === 'loic' ? 'Tu as publié cette demande pour toi-même : Nexus ne l\'ouvre pas à l\'approbation, il n\'y a rien à décider ici.' : 'Cette demande est antérieure au suivi des approbations : Nexus ne sait pas si elle est traitée et elle ne peut pas l\'être ici.'}</p>}
          {approval !== null && !pending && !formShown && !sent && <Treated approval={approval} />}
          {formShown && isQuestion && (
            <form onSubmit={submitAnswer} className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-label={`Répondre à ${ask.subject}`}>
              {ask.options.length > 0 && (
                <div role="group" aria-label="Réponses proposées" className="flex flex-wrap gap-1.5">
                  {entries.map((o) => (
                    <Button key={o.index} className="h-auto min-w-0 max-w-full whitespace-normal break-words text-left [overflow-wrap:anywhere]" disabled={!editable} onClick={() => onDraft(approval!.ref, { text: o.text })}><span className="min-w-0 [overflow-wrap:anywhere]">{o.text}</span></Button>
                  ))}
                </div>
              )}
              <label htmlFor={`${id}-text`} className="font-orbital-display text-xs font-semibold uppercase tracking-[0.14em] text-muted">Ta réponse</label>
              <textarea id={`${id}-text`} rows={3} maxLength={ANSWER_MAX} disabled={sending} readOnly={!pending} value={draft.text}
                aria-describedby={canAnswer ? undefined : reasonId}
                onChange={(e) => onDraft(approval!.ref, { text: e.target.value })} className={clsx(inputClass, 'resize-y')} />
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" variant="primary" disabled={!canAnswer} aria-describedby={canAnswer ? undefined : reasonId}>Répondre</Button>
                {stale && <Button onClick={() => onSent(approval!.ref)}>Effacer le brouillon</Button>}
                {!canAnswer && <span id={reasonId} className="text-xs text-muted">{reasonFor(status, sending, 'Écris une réponse pour pouvoir répondre.')}</span>}
              </div>
            </form>
          )}
          {formShown && !isQuestion && (
            <form onSubmit={(e) => e.preventDefault()} className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-label={`Décider : ${ask.subject}`}>
              {entries.length > 0 && (
                <fieldset className="m-0 grid gap-1 border-0 p-0" disabled={!editable}>
                  <legend className="mb-1 p-0 font-orbital-display text-xs font-semibold uppercase tracking-[0.14em] text-muted">
                    Option {choiceRequired ? '(à choisir pour valider)' : '(facultative)'}
                  </legend>
                  {entries.map((o) => (
                    <label key={o.index} className="flex min-w-0 items-start gap-2 text-xs [overflow-wrap:anywhere]">
                      <input type="radio" name={`${id}-choice`} value={o.index} checked={draft.choice === o.index}
                        onChange={() => onDraft(approval!.ref, { choice: o.index })} />
                      {o.text}
                    </label>
                  ))}
                </fieldset>
              )}
              <label htmlFor={`${id}-note`} className="font-orbital-display text-xs font-semibold uppercase tracking-[0.14em] text-muted">Note (facultative)</label>
              <textarea id={`${id}-note`} rows={2} maxLength={NOTE_MAX} disabled={sending} readOnly={!pending} value={draft.note}
                onChange={(e) => onDraft(approval!.ref, { note: e.target.value })} className={clsx(inputClass, 'resize-y')} />
              <Consequence ask={ask} />
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="primary" disabled={!canApprove} aria-describedby={canApprove ? undefined : reasonId} onClick={() => decide('approved')}>Valider</Button>
                <Button disabled={!editable} onClick={() => decide('rejected')}>Refuser</Button>
                {stale && <Button onClick={() => onSent(approval!.ref)}>Effacer le brouillon</Button>}
                {!canApprove && <span id={reasonId} className="text-xs text-muted">{reasonFor(status, sending, 'Choisis une option pour pouvoir valider.')}</span>}
              </div>
            </form>
          )}
          {error && <p ref={alertRef} tabIndex={-1} role="alert" className="m-0 text-xs text-danger [overflow-wrap:anywhere]">{error}</p>}
        </div>
      )}
    </article>
  )
}

/** Banner of a draft whose ask is no longer pending. `unsure`: the send itself got no answer. */
function staleText(approval: NowApproval, isQuestion: boolean, unsure: boolean): string {
  const noun = isQuestion ? 'ta réponse' : 'ta décision'
  const head = approval.status === 'expired'
    ? 'Expirée entre-temps'
    : `Traitée entre-temps par ${approval.decided_by ? displayName(approval.decided_by) : 'un autre acteur'}`
  return unsure
    ? `${head} : l'envoi n'a pas eu de réponse, vérifie que c'est bien ${noun}`
    : `${head} : ${noun} n'a pas été envoyée`
}

/** Why the send button is off, said next to it. */
function reasonFor(status: NowApproval['status'] | null, sending: boolean, missing: string): string {
  if (status === 'expired') return 'Cette demande a expiré : l\'agent n\'attend plus de réponse.'
  if (status !== 'pending') return 'Cette demande est déjà traitée.'
  return sending ? 'Envoi en cours.' : missing
}

function Chip({ approval, agent }: { approval: NowApproval | null; agent: string }) {
  if (approval === null) return <span data-chip="unknown" className="border border-line-strong px-1.5 text-[11px] text-muted [overflow-wrap:anywhere]">{agent === 'loic' ? 'demande que tu t\'adresses à toi-même : rien à décider ici' : 'sans suivi d\'approbation (demande antérieure au suivi)'}</span>
  const pending = approval.status === 'pending'
  return (
    <span data-chip={pending ? 'pending' : 'treated'}
      className={clsx('border px-1.5 text-[11px] font-semibold', pending ? 'border-attention text-attention' : 'border-line-strong text-muted')}>
      {CHIP_TEXT[approval.status]}
    </span>
  )
}

/** The announced consequence sits just above the buttons: announced by the agent, never verified (ADR-005). */
function Consequence({ ask }: { ask: NowAsk }) {
  return ask.consequence
    ? <p className="m-0 text-xs text-ink [overflow-wrap:anywhere]"><strong className="font-semibold">Conséquence annoncée par {displayName(ask.agent)} :</strong> {ask.consequence}</p>
    : <p className="m-0 text-xs font-semibold text-attention">Conséquence non précisée par l'agent</p>
}

function Treated({ approval }: { approval: NowApproval }) {
  if (approval.status === 'expired') return <p className="m-0 text-xs text-muted">Expirée{approval.expires_at ? ` le ${formatDateTime(approval.expires_at)}` : ''} : l'agent n'attendait plus de réponse.</p>
  if (approval.status === 'pending') return null
  const who = approval.decided_by ? ` par ${displayName(approval.decided_by)}` : ''
  const when = approval.decided_at ? ` le ${formatDateTime(approval.decided_at)}` : ''
  return <p className="m-0 text-xs text-muted">{TREATED_TEXT[approval.status]}{who}{when}.</p>
}
