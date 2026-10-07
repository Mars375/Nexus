import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useId, useRef, useState, type FormEvent } from 'react'
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

/** Refusals after which the ask must be read again: someone else got there first. */
const STALE_CODES = ['approval_already_decided', 'approval_expired']
const UNREACHABLE = 'Le serveur Nexus ne répond pas. Ta saisie est conservée : réessaie dans un instant.'

/** Message shown under the form: the server's French text, never a value Loïc typed. */
const errorText = (e: unknown): string => (e instanceof ApiError ? e.message : UNREACHABLE)

type Props = {
  ask: NowAsk
  now: number
  fresh: boolean
  draft: AskDraft | undefined
  onDraft: (ref: string, change: Partial<AskDraft>) => void
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
  const inFlight = useRef(false) // two clicks in the same tick must send one request

  const approval = ask.approval
  const status = approval?.status ?? null
  const pending = status === 'pending'
  const isQuestion = ask.kind === 'question'
  const entries = ask.options.map((text, index) => ({ text, index })).filter((o) => o.text.trim() !== '')
  const choiceRequired = !isQuestion && entries.length >= 2
  const stale = approval !== null && !pending && hasDraft(draft) && !sent
  const formShown = approval !== null && !sent && (pending || status === 'expired' || stale)
  const editable = pending && !sending

  async function send(run: () => Promise<unknown>) {
    if (inFlight.current || !approval) return
    inFlight.current = true
    setSending(true)
    setError(null)
    try {
      await run()
      // Stay "sending" until Maintenant has been read again: the form never reopens on the old state.
      await client.invalidateQueries({ queryKey: nowKey })
      setSent(true)
      onSent(approval.ref)
    } catch (e) {
      setError(errorText(e))
      if (e instanceof ApiError && STALE_CODES.includes(e.code)) await client.invalidateQueries({ queryKey: nowKey })
    } finally {
      inFlight.current = false
      setSending(false)
    }
  }

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
      className={clsx('mb-1.5 border-l-2 px-3 py-2', pending ? 'border-attention' : 'border-line-strong', fresh ? 'now-fresh' : pending && 'bg-attention-soft')}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="m-0 min-w-0 text-[13px]">
          <button type="button" aria-expanded={open} aria-controls={`${id}-detail`} onClick={() => setOpen((o) => !o)}
            className="flex w-full min-w-0 items-baseline gap-1.5 bg-transparent p-0 text-left font-semibold text-ink">
            <span aria-hidden className="font-data text-[11px] text-muted">{open ? '▾' : '▸'}</span>
            <span className="min-w-0 break-words">{ask.subject}</span>
          </button>
        </h3>
        <span className="shrink-0 font-data text-[11px] text-muted">{age(ask.received_at, now)}</span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs text-muted">
        <span>
          {isQuestion ? 'Question' : 'Demande de validation'} de {displayName(ask.agent)}{' '}
          {ask.task ? <>sur <a href={`#/travail/${ask.task}`}>{ask.task}</a></> : 'sur aucune tâche'}.
        </span>
        <Chip approval={approval} />
        {pending && approval?.expires_at && <span className="font-data text-[11px]">expire {until(approval!.expires_at!, now)}</span>}
      </div>
      {stale && (
        <p role="status" className="mt-1.5 mb-0 border border-attention bg-attention-soft px-2 py-1 text-xs text-ink">
          {status === 'expired' ? 'Expirée entre-temps' : `Traitée entre-temps par ${approval.decided_by ? displayName(approval.decided_by) : 'un autre acteur'}`}
          {' : '}{isQuestion ? 'ta réponse' : 'ta décision'} n'a pas été envoyée
        </p>
      )}
      {open && (
        <div id={`${id}-detail`} className="mt-2 grid gap-2.5">
          {ask.body && <p className="m-0 whitespace-pre-wrap text-xs text-ink">{ask.body}</p>}
          {!isQuestion && !formShown && <Consequence ask={ask} />}
          {approval === null && <p className="m-0 text-xs text-muted">Cette demande date d'avant le suivi des approbations : Nexus ne sait pas si elle est traitée, elle ne peut pas être traitée ici.</p>}
          {approval !== null && !pending && !formShown && <Treated approval={approval} />}
          {approval !== null && sent && <p role="status" className="m-0 text-xs text-muted">{isQuestion ? 'Réponse envoyée.' : 'Décision envoyée.'}</p>}
          {formShown && isQuestion && (
            <form onSubmit={submitAnswer} className="grid gap-2" aria-label={`Répondre à ${ask.subject}`}>
              {ask.options.length > 0 && (
                <div role="group" aria-label="Réponses proposées" className="flex flex-wrap gap-1.5">
                  {entries.map((o) => (
                    <Button key={o.index} disabled={!editable} onClick={() => onDraft(approval!.ref, { text: o.text })}>{o.text}</Button>
                  ))}
                </div>
              )}
              <label htmlFor={`${id}-text`} className="font-orbital-display text-xs font-semibold uppercase tracking-[0.14em] text-muted">Ta réponse</label>
              <textarea id={`${id}-text`} rows={3} maxLength={ANSWER_MAX} disabled={!editable} value={draft.text}
                aria-describedby={canAnswer ? undefined : reasonId}
                onChange={(e) => onDraft(approval!.ref, { text: e.target.value })} className={clsx(inputClass, 'resize-y')} />
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" variant="primary" disabled={!canAnswer} aria-describedby={canAnswer ? undefined : reasonId}>Répondre</Button>
                {!canAnswer && <span id={reasonId} className="text-xs text-muted">{reasonFor(status, sending, 'Écris une réponse pour pouvoir répondre.')}</span>}
              </div>
            </form>
          )}
          {formShown && !isQuestion && (
            <form onSubmit={(e) => e.preventDefault()} className="grid gap-2" aria-label={`Décider : ${ask.subject}`}>
              {entries.length > 0 && (
                <fieldset className="m-0 grid gap-1 border-0 p-0" disabled={!editable}>
                  <legend className="mb-1 p-0 font-orbital-display text-xs font-semibold uppercase tracking-[0.14em] text-muted">
                    Option {choiceRequired ? '(à choisir pour valider)' : '(facultative)'}
                  </legend>
                  {entries.map((o) => (
                    <label key={o.index} className="flex items-center gap-2 text-xs">
                      <input type="radio" name={`${id}-choice`} value={o.index} checked={draft.choice === o.index}
                        onChange={() => onDraft(approval!.ref, { choice: o.index })} />
                      {o.text}
                    </label>
                  ))}
                </fieldset>
              )}
              <label htmlFor={`${id}-note`} className="font-orbital-display text-xs font-semibold uppercase tracking-[0.14em] text-muted">Note (facultative)</label>
              <textarea id={`${id}-note`} rows={2} maxLength={NOTE_MAX} disabled={!editable} value={draft.note}
                onChange={(e) => onDraft(approval!.ref, { note: e.target.value })} className={clsx(inputClass, 'resize-y')} />
              <Consequence ask={ask} />
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="primary" disabled={!canApprove} aria-describedby={canApprove ? undefined : reasonId} onClick={() => decide('approved')}>Valider</Button>
                <Button disabled={!editable} onClick={() => decide('rejected')}>Refuser</Button>
                {!canApprove && <span id={reasonId} className="text-xs text-muted">{reasonFor(status, sending, 'Choisis une option pour pouvoir valider.')}</span>}
              </div>
            </form>
          )}
          <p aria-live="polite" className="m-0 min-h-4 text-xs text-muted">{sending ? 'Envoi…' : ''}</p>
          {error && <p role="alert" className="m-0 text-xs text-danger">{error}</p>}
        </div>
      )}
    </article>
  )
}

/** Why the send button is off, said next to it. */
function reasonFor(status: NowApproval['status'] | null, sending: boolean, missing: string): string {
  if (status === 'expired') return 'Cette demande a expiré : l\'agent n\'attend plus de réponse.'
  if (status !== 'pending') return 'Cette demande est déjà traitée.'
  return sending ? 'Envoi en cours.' : missing
}

function Chip({ approval }: { approval: NowApproval | null }) {
  if (approval === null) return <span data-chip="unknown" className="border border-line-strong px-1.5 text-[11px] text-muted">suivi indisponible (demande antérieure)</span>
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
    ? <p className="m-0 text-xs text-ink"><strong className="font-semibold">Conséquence annoncée par {displayName(ask.agent)} :</strong> {ask.consequence}</p>
    : <p className="m-0 text-xs font-semibold text-attention">Conséquence non précisée par l'agent</p>
}

function Treated({ approval }: { approval: NowApproval }) {
  if (approval.status === 'expired') return <p className="m-0 text-xs text-muted">Expirée{approval.expires_at ? ` le ${formatDateTime(approval.expires_at)}` : ''} : l'agent n'attendait plus de réponse.</p>
  if (approval.status === 'pending') return null
  const who = approval.decided_by ? ` par ${displayName(approval.decided_by)}` : ''
  const when = approval.decided_at ? ` le ${formatDateTime(approval.decided_at)}` : ''
  return <p className="m-0 text-xs text-muted">{TREATED_TEXT[approval.status]}{who}{when}.</p>
}
