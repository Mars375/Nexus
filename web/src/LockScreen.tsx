import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { clearToken, isTokenFormat, markUnlocked, setToken, useAuth } from './auth'
import { Button, Field, inputClass } from './ui'

const FIELD = 'Jeton d’accès'

/** Why Nexus locked the app, from the code of the 401 it sent (ADR-020, D8). */
function reasonText(reason: string | null): string | null {
  switch (reason) {
    case null:
      return null
    case 'auth_required':
      return 'Nexus exige un jeton d’accès pour répondre.'
    case 'invalid_token':
      return 'Nexus a refusé le jeton enregistré (inconnu ou révoqué). Il a été oublié : saisis-en un nouveau.'
    default:
      return 'L’accès a été refusé (401).'
  }
}

function validate(value: string): string | null {
  if (value === '') return `${FIELD} : le champ est obligatoire.`
  if (!isTokenFormat(value)) {
    return `${FIELD} : format invalide. Un jeton commence par nxt_, suivi de 43 lettres, chiffres, tirets (-) ou tirets bas (_).`
  }
  return null
}

/**
 * Écran « Nexus verrouillé » (ADR-020, D4) : affiché quand l’API répond 401, jamais parce qu’aucun
 * jeton n’est stocké. Le jeton saisi n’est ni réaffiché ni recopié dans une erreur.
 */
export function LockScreen() {
  const { lockReason, hasToken } = useAuth()
  const client = useQueryClient()
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const errorId = useId()

  useEffect(() => inputRef.current?.focus(), [])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const token = value.trim() // un copier-coller peut ajouter un espace ou un saut de ligne
    const problem = validate(token)
    setError(problem)
    if (problem) {
      inputRef.current?.focus()
      return
    }
    setToken(token)
    markUnlocked()
    setValue('')
    void client.invalidateQueries() // les données se relisent avec le jeton
  }

  const why = reasonText(lockReason)
  return (
    <main
      className="orbital fixed inset-0 z-[1000] grid place-items-center overflow-auto bg-paper p-4 font-orbital text-ink"
    >
      <form
        onSubmit={submit}
        noValidate
        aria-labelledby="lock-title"
        className="grid w-[min(26rem,100%)] grid-cols-[minmax(0,1fr)] gap-4 rounded-sm border border-line-strong bg-surface p-4 sm:p-6"
      >
        <h1 id="lock-title" className="m-0 font-orbital-display text-2xl font-semibold uppercase tracking-[0.12em]">
          Nexus verrouillé
        </h1>
        {why && <p role="status" className="m-0 text-sm text-attention">{why}</p>}
        <p className="m-0 text-sm text-muted">
          Pour obtenir un jeton d’accès sur ce poste, lance
          <code className="my-1 block overflow-x-auto whitespace-nowrap rounded-sm bg-sunken px-2 py-1.5 font-data text-[11px] text-ink sm:text-xs">nexus-token issue loic --label navigateur</code>
          puis colle ici le jeton affiché. Il reste dans ce navigateur et n’est jamais réaffiché.
        </p>
        <Field label={FIELD}>
          {/* type=password keeps the token masked on screen; autocomplete=off because it is not a login (there is no username). Browsers may still offer to save it (Chromium ignores autocomplete=off on password fields): accepted. */}
          <input
            ref={inputRef}
            type="password"
            name="token"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={errorId}
            className={`${inputClass} font-data`}
          />
        </Field>
        <div id={errorId} role="alert" className="text-sm text-danger empty:hidden">
          {error}
        </div>
        <div className="flex items-center justify-between gap-3">
          <Button type="submit" variant="primary">Déverrouiller</Button>
          {hasToken && (
            <Button variant="ghost" onClick={() => { clearToken(); void client.invalidateQueries() }}>
              Oublier le jeton
            </Button>
          )}
        </div>
      </form>
    </main>
  )
}
