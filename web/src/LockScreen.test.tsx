import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { clearToken, getAuthState, getToken, markLocked, markUnlocked, setToken } from './auth'
import { LockScreen } from './LockScreen'

const TOKEN = 'nxt_' + 'A'.repeat(43)

beforeEach(() => {
  clearToken()
  markUnlocked()
})

function renderLock() {
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  render(<QueryClientProvider client={client}><LockScreen /></QueryClientProvider>)
  return { invalidate }
}

const input = () => screen.getByLabelText('Jeton d’accès')

test('l’écran « Nexus verrouillé » a un titre, un champ mot de passe étiqueté, focalisé, et un bouton', () => {
  markLocked('auth_required')
  renderLock()
  expect(screen.getByRole('heading', { name: 'Nexus verrouillé' })).toBeInTheDocument()
  expect(input()).toHaveAttribute('type', 'password')
  expect(input()).toHaveAttribute('autocomplete', 'off')
  expect(input()).toHaveFocus()
  expect(screen.getByRole('button', { name: 'Déverrouiller' })).toBeInTheDocument()
  expect(screen.getByRole('alert')).toBeEmptyDOMElement()
})

test('la consigne montre la commande qui émet un jeton', () => {
  renderLock()
  expect(screen.getByText('nexus-token issue loic --label navigateur')).toBeInTheDocument()
  expect(screen.getByText('nexus-token issue loic --label navigateur').tagName).toBe('CODE')
  expect(screen.getByText('nexus-token issue loic --label navigateur')).toHaveClass('whitespace-nowrap')
})

test.each([
  ['auth_required', /exige un jeton d’accès/],
  ['invalid_token', /refusé le jeton/],
  ['http_401', /L’accès a été refusé \(401\)/],
])('le motif %s est expliqué', (reason, text) => {
  markLocked(reason)
  renderLock()
  expect(screen.getByRole('status')).toHaveTextContent(text)
})

test('un champ vide ou mal formé affiche une erreur qui nomme le champ sans recopier la valeur', async () => {
  const { invalidate } = renderLock()

  fireEvent.click(screen.getByRole('button', { name: 'Déverrouiller' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Jeton d’accès : le champ est obligatoire.')

  const secret = 'nxt_trop-court-SECRET'
  fireEvent.change(input(), { target: { value: secret } })
  fireEvent.click(screen.getByRole('button', { name: 'Déverrouiller' }))
  const alert = screen.getByRole('alert')
  expect(alert).toHaveTextContent(
    'Jeton d’accès : format invalide. Un jeton commence par nxt_, suivi de 43 lettres, chiffres, tirets (-) ou tirets bas (_).',
  )
  expect(alert.textContent).not.toContain('SECRET')
  expect(input()).toHaveAttribute('aria-invalid', 'true')
  expect(input()).toHaveAccessibleDescription(/format invalide/)
  expect(getToken()).toBeNull()
  expect(invalidate).not.toHaveBeenCalled()
})

test('un jeton bien formé est stocké, déverrouille et fait relire toutes les requêtes', async () => {
  markLocked('auth_required')
  const { invalidate } = renderLock()

  fireEvent.change(input(), { target: { value: `  ${TOKEN}\n` } }) // les espaces d’un copier-coller sont ignorés
  fireEvent.click(screen.getByRole('button', { name: 'Déverrouiller' }))

  expect(getToken()).toBe(TOKEN)
  expect(getAuthState().locked).toBe(false)
  expect(invalidate).toHaveBeenCalledTimes(1)
  expect(screen.queryByText(TOKEN)).toBeNull()
})

test('« Oublier le jeton » n’apparaît que si un jeton est stocké, et l’efface', async () => {
  markLocked('http_401')
  renderLock()
  expect(screen.queryByRole('button', { name: 'Oublier le jeton' })).toBeNull()

  act(() => setToken(TOKEN))
  const forget = await screen.findByRole('button', { name: 'Oublier le jeton' })
  fireEvent.click(forget)

  expect(getToken()).toBeNull()
  expect(screen.queryByRole('button', { name: 'Oublier le jeton' })).toBeNull()
  expect(document.body.textContent).not.toContain(TOKEN)
})
