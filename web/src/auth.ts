/*
 * Jeton d'acteur de l'interface (ADR-020, D4). L'interface s'authentifie comme `loic` avec un
 * jeton porteur gardé en `localStorage` sous une seule clé, envoyé par `request()` dans
 * `Authorization`. Le jeton n'est jamais affiché, journalisé ni recopié dans un message d'erreur.
 * Le stockage peut lever (fenêtre privée, données bloquées) : chaque accès est protégé et le jeton
 * reste alors en mémoire pour la session.
 */
import { useSyncExternalStore } from 'react'

export const TOKEN_KEY = 'nexus.token'

/** `nxt_` suivi de 43 caractères base64url (32 octets), comme `nexus.auth.tokens` côté serveur. */
const TOKEN_FORMAT = /^nxt_[A-Za-z0-9_-]{43}$/

export const isTokenFormat = (value: unknown): value is string =>
  typeof value === 'string' && TOKEN_FORMAT.test(value)

let memoryToken: string | null = null
/** Le stockage a refusé une écriture : la mémoire fait foi jusqu'à `clearToken`. */
let memoryOnly = false

/** The stored token; a stored value of any other shape is ignored (never sent). */
export function getToken(): string | null {
  if (memoryOnly) return memoryToken
  try {
    const stored = window.localStorage.getItem(TOKEN_KEY)
    return isTokenFormat(stored) ? stored : null
  } catch {
    return memoryToken
  }
}

export function setToken(token: string): void {
  if (!isTokenFormat(token)) return
  memoryToken = token
  memoryOnly = false
  try {
    window.localStorage.setItem(TOKEN_KEY, token)
  } catch {
    memoryOnly = true
  }
  refresh()
}

export function clearToken(): void {
  memoryToken = null
  memoryOnly = false
  try {
    window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    // stockage inaccessible : il n'y a rien de plus à effacer que la mémoire
  }
  refresh()
}

export type AuthState = {
  /** The API answered 401: the lock screen replaces the app. Driven by the server, never by an empty store. */
  locked: boolean
  /** Code of the refusal that locked the app (`auth_required`, `invalid_token`, `http_401`…), else null. */
  lockReason: string | null
  hasToken: boolean
}

let state: AuthState = { locked: false, lockReason: null, hasToken: getToken() !== null }
const listeners = new Set<() => void>()

function update(next: Partial<AuthState>) {
  const merged = { ...state, ...next }
  if (merged.locked === state.locked && merged.lockReason === state.lockReason && merged.hasToken === state.hasToken) return
  state = merged
  for (const listener of [...listeners]) listener()
}

function refresh() {
  update({ hasToken: getToken() !== null })
}

export const getAuthState = (): AuthState => state

export function markLocked(reason: string): void {
  update({ locked: true, lockReason: reason, hasToken: getToken() !== null })
}

export function markUnlocked(): void {
  update({ locked: false, lockReason: null, hasToken: getToken() !== null })
}

/** Calls `listener` after each change of the auth state; returns the unsubscribe function. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

// Another tab stored or forgot the token: follow it.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === null || event.key === TOKEN_KEY) refresh()
  })
}

export const useAuth = (): AuthState => useSyncExternalStore(subscribe, getAuthState, getAuthState)
