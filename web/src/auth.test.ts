import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import {
  TOKEN_KEY,
  clearToken,
  getAuthState,
  getToken,
  isTokenFormat,
  markLocked,
  markUnlocked,
  onUnlockedElsewhere,
  setToken,
  subscribe,
  takeFocusToRestore,
} from './auth'

const TOKEN = 'nxt_' + 'A'.repeat(43)

beforeEach(() => {
  clearToken()
  markUnlocked()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test('le format accepté est nxt_ suivi de 43 caractères base64url', () => {
  expect(isTokenFormat(TOKEN)).toBe(true)
  expect(isTokenFormat('nxt_' + 'a-_Z9'.repeat(8) + 'abc')).toBe(true)
  expect(isTokenFormat('nxt_' + 'A'.repeat(42))).toBe(false)
  expect(isTokenFormat('nxt_' + 'A'.repeat(44))).toBe(false)
  expect(isTokenFormat('abc_' + 'A'.repeat(43))).toBe(false)
  expect(isTokenFormat('nxt_' + 'é'.repeat(43))).toBe(false)
  expect(isTokenFormat(TOKEN + '\n')).toBe(false)
  expect(isTokenFormat(undefined)).toBe(false)
})

test('le jeton est gardé dans localStorage sous une seule clé, puis effacé', () => {
  expect(getToken()).toBeNull()
  setToken(TOKEN)
  expect(window.localStorage.getItem(TOKEN_KEY)).toBe(TOKEN)
  expect(getToken()).toBe(TOKEN)
  clearToken()
  expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull()
  expect(getToken()).toBeNull()
})

test("une valeur mal formée n'est ni stockée ni lue", () => {
  setToken('pas-un-jeton')
  expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull()
  window.localStorage.setItem(TOKEN_KEY, 'Bearer x\r\nX-Evil: 1')
  expect(getToken()).toBeNull()
})

test("un stockage qui lève ne casse rien : le jeton reste en mémoire pour la session", () => {
  const broken = {
    getItem: () => { throw new Error('SecurityError') },
    setItem: () => { throw new Error('QuotaExceededError') },
    removeItem: () => { throw new Error('SecurityError') },
  }
  vi.stubGlobal('localStorage', broken)

  expect(getToken()).toBeNull()
  expect(() => setToken(TOKEN)).not.toThrow()
  expect(getToken()).toBe(TOKEN)
  expect(() => clearToken()).not.toThrow()
  expect(getToken()).toBeNull()
})

test("une écriture refusée garde le jeton en mémoire même si la lecture marche", () => {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: () => { throw new Error('QuotaExceededError') },
    removeItem: (k: string) => { store.delete(k) },
  })
  setToken(TOKEN)
  expect(getToken()).toBe(TOKEN)
  clearToken()
  expect(getToken()).toBeNull()
})

test("les abonnés sont prévenus d'un changement, pas d'un état identique, et peuvent se désabonner", () => {
  const listener = vi.fn()
  const unsubscribe = subscribe(listener)

  setToken(TOKEN)
  expect(listener).toHaveBeenCalledTimes(1)
  expect(getAuthState().hasToken).toBe(true)
  setToken(TOKEN)
  expect(listener).toHaveBeenCalledTimes(1)
  markLocked('invalid_token')
  expect(listener).toHaveBeenCalledTimes(2)
  expect(getAuthState()).toMatchObject({ locked: true, lockReason: 'invalid_token' })
  markUnlocked()
  clearToken()
  expect(getAuthState()).toEqual({ locked: false, lockReason: null, hasToken: false })

  unsubscribe()
  const calls = listener.mock.calls.length
  setToken(TOKEN)
  expect(listener).toHaveBeenCalledTimes(calls)
})

test("l'absence de jeton ne verrouille pas l'application : seul le serveur le fait", () => {
  expect(getAuthState()).toEqual({ locked: false, lockReason: null, hasToken: false })
})

test("le jeton n'est jamais journalisé", () => {
  const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) => vi.spyOn(console, m))
  setToken(TOKEN)
  getToken()
  markLocked('invalid_token')
  clearToken()
  for (const spy of spies) expect(spy).not.toHaveBeenCalled()
})

function storageEvent(newValue: string | null) {
  window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue }))
}

test('un jeton bien formé arrivé d’un autre onglet déverrouille cet onglet et prévient les vues', () => {
  const unlocked = vi.fn()
  const off = onUnlockedElsewhere(unlocked)
  markLocked('invalid_token')

  storageEvent(TOKEN)

  expect(getAuthState().locked).toBe(false)
  expect(unlocked).toHaveBeenCalledTimes(1)
  off()
})

test('d’un autre onglet, une valeur mal formée ou un oubli ne déverrouille pas', () => {
  const unlocked = vi.fn()
  const off = onUnlockedElsewhere(unlocked)
  markLocked('auth_required')

  storageEvent('pas-un-jeton')
  storageEvent(null)

  expect(getAuthState().locked).toBe(true)
  expect(unlocked).not.toHaveBeenCalled()
  off()
})

test('un jeton venu d’un autre onglet ne prévient personne quand cet onglet n’est pas verrouillé', () => {
  const unlocked = vi.fn()
  const off = onUnlockedElsewhere(unlocked)

  storageEvent(TOKEN)

  expect(unlocked).not.toHaveBeenCalled()
  off()
})

test('déjà verrouillé, le premier motif reste et personne n’est prévenu de nouveau', () => {
  markLocked('invalid_token')
  const listener = vi.fn()
  const off = subscribe(listener)
  markLocked('auth_required')
  expect(getAuthState().lockReason).toBe('invalid_token')
  expect(listener).not.toHaveBeenCalled()
  off()
})

test('le focus d’avant le verrouillage est rendu une fois, au déverrouillage', () => {
  const button = document.createElement('button')
  document.body.append(button)
  button.focus()
  markLocked('invalid_token')
  markLocked('auth_required') // ne doit pas écraser l'élément mémorisé
  document.body.focus()
  markUnlocked()
  expect(takeFocusToRestore()).toBe(button)
  expect(takeFocusToRestore()).toBeNull()
  button.remove()
})
