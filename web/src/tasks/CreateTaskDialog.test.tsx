import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Task } from '@/api'
import { clearToken, markLocked, markUnlocked } from '@/auth'
import { CreateTaskDialog } from './CreateTaskDialog'

const BASE: Task = {
  id: 'nx-task-7', title: 'Livraison initiale', objective: 'Livrer', status: 'done',
  human_owner: 'loic', lead_agent: null, collaborators: [], next_action: null,
  due_at: null, follow_up_at: null, block_cause: null, block_plan: null, drop_reason: null,
  expected_evidence: null, evidence: [], priority: 'normal', operation_role: null, origin: null,
  context: [], depends_on: [], follows: null, created_by: 'loic', created_at: '2026-09-28T10:00:00+02:00',
  updated_at: '2026-09-28T10:00:00+02:00', source: 'nexus.db', measured_at: '2026-09-28T10:00:00+02:00',
}
const SEVEN = BASE
const NINE = { ...BASE, id: 'nx-task-9', title: 'Autre livraison' }
const TASKS = [SEVEN, NINE]

let posts: unknown[] = []

beforeEach(() => {
  clearToken()
  markUnlocked()
  posts = []
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posts.push(JSON.parse(String(init.body)))
      return Response.json({ ...BASE, id: 'nx-task-20', title: 'créée' })
    }
    return Response.json([])
  }))
})
afterEach(() => vi.unstubAllGlobals())

function ui(follows: string | null) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CreateTaskDialog open follows={follows} tasks={TASKS} onOpenChange={() => {}} />
    </QueryClientProvider>
  )
}

const title = () => screen.getByLabelText('Titre') as HTMLInputElement
const fill = (value: string) => fireEvent.change(title(), { target: { value } })

test('une tâche de suite montre « Suite de nx-task-N — titre » en tête du formulaire', () => {
  render(ui('nx-task-7'))
  expect(screen.getByText('Suite de nx-task-7 — Livraison initiale')).toBeInTheDocument()
})

test('une tâche simple ne montre aucune ligne « Suite de »', () => {
  render(ui(null))
  expect(screen.queryByText(/Suite de/)).not.toBeInTheDocument()
})

test('une suite envoie follows avec le reste ; une tâche simple n’envoie aucune clé follows', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = (f: string | null) => (
    <QueryClientProvider client={client}>
      <CreateTaskDialog open follows={f} tasks={TASKS} onOpenChange={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(view('nx-task-7'))
  fill('Correctif')
  fireEvent.change(screen.getByLabelText(/^Objectif/), { target: { value: 'Corriger' } })
  fireEvent.click(screen.getByRole('button', { name: 'Créer la tâche' }))
  await waitFor(() => expect(posts).toHaveLength(1))
  expect(posts[0]).toMatchObject({ title: 'Correctif', follows: 'nx-task-7' })

  rerender(view(null))
  fill('Simple')
  fireEvent.change(screen.getByLabelText(/^Objectif/), { target: { value: 'Faire' } })
  fireEvent.click(screen.getByRole('button', { name: 'Créer la tâche' }))
  await waitFor(() => expect(posts).toHaveLength(2))
  expect(posts[1]).not.toHaveProperty('follows')
})

test('un brouillon par cible : le brouillon simple et celui d’une suite ne se mélangent pas', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = (f: string | null) => (
    <QueryClientProvider client={client}>
      <CreateTaskDialog open follows={f} tasks={TASKS} onOpenChange={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(view(null))
  fill('A')

  rerender(view('nx-task-7'))
  expect(title()).toHaveValue('')
  expect(screen.getByText(/Suite de nx-task-7/)).toBeInTheDocument()
  fill('B')

  rerender(view(null))
  expect(title()).toHaveValue('A')
  expect(screen.queryByText(/Suite de/)).not.toBeInTheDocument()

  rerender(view('nx-task-7'))
  expect(title()).toHaveValue('B')

  // Deux suites de tâches différentes : deux brouillons.
  rerender(view('nx-task-9'))
  expect(title()).toHaveValue('')
  fill('C')
  rerender(view('nx-task-7'))
  expect(title()).toHaveValue('B')
  rerender(view('nx-task-9'))
  expect(title()).toHaveValue('C')
})

test('une création réussie ne vide que le brouillon de sa cible', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = (f: string | null) => (
    <QueryClientProvider client={client}>
      <CreateTaskDialog open follows={f} tasks={TASKS} onOpenChange={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(view(null))
  fill('A simple')

  rerender(view('nx-task-7'))
  fill('B suite')
  fireEvent.change(screen.getByLabelText(/^Objectif/), { target: { value: 'Corriger' } })
  fireEvent.click(screen.getByRole('button', { name: 'Créer la tâche' }))
  await waitFor(() => expect(posts).toHaveLength(1))
  await waitFor(() => expect(title()).toHaveValue(''))

  rerender(view(null))
  expect(title()).toHaveValue('A simple')
})

test('la cible choisie à l’envoi est celle du brouillon, même si la boîte change de cible avant la réponse', async () => {
  let release: () => void = () => {}
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posts.push(JSON.parse(String(init.body)))
      await new Promise<void>((resolve) => { release = resolve })
      return Response.json({ ...BASE, id: 'nx-task-20' })
    }
    return Response.json([])
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = (f: string | null) => (
    <QueryClientProvider client={client}>
      <CreateTaskDialog open follows={f} tasks={TASKS} onOpenChange={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(view('nx-task-7'))
  fill('B suite')
  fireEvent.change(screen.getByLabelText(/^Objectif/), { target: { value: 'Corriger' } })
  fireEvent.click(screen.getByRole('button', { name: 'Créer la tâche' }))
  await waitFor(() => expect(posts).toHaveLength(1))

  rerender(view(null))
  fill('A simple')
  await act(async () => release())

  // Le brouillon simple, lui, n'a pas été vidé par la réussite de la suite.
  await waitFor(() => expect(title()).toHaveValue('A simple'))
  rerender(view('nx-task-7'))
  expect(title()).toHaveValue('')
})

test('verrouillage pendant une suite : au retour, même cible, même brouillon, même follows', async () => {
  render(ui('nx-task-7'))
  fill('Brouillon suite')

  act(() => markLocked('invalid_token'))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  act(() => markUnlocked())

  expect(screen.getByText(/Suite de nx-task-7/)).toBeInTheDocument()
  expect(title()).toHaveValue('Brouillon suite')
  fireEvent.change(screen.getByLabelText(/^Objectif/), { target: { value: 'Corriger' } })
  fireEvent.click(screen.getByRole('button', { name: 'Créer la tâche' }))
  await waitFor(() => expect(posts).toHaveLength(1))
  expect(posts[0]).toMatchObject({ follows: 'nx-task-7', title: 'Brouillon suite' })
})

test('une tâche suivie absente de la liste garde la référence, sans titre inventé', () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CreateTaskDialog open follows="nx-task-99" tasks={TASKS} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
  expect(screen.getByText('Suite de nx-task-99')).toBeInTheDocument()
})

test('pendant l’envoi, les champs sont figés : le serveur reçoit le texte d’origine', async () => {
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posts.push(JSON.parse(String(init.body)))
      await gate
      return Response.json({ ...BASE, id: 'nx-task-20', title: 'créée' })
    }
    return Response.json([])
  }))
  render(ui(null))
  // The live region is mounted empty first, so its later text is announced.
  expect(screen.getByRole('status')).toHaveTextContent(/^$/)
  fill('Original')
  fireEvent.change(screen.getByLabelText(/^Objectif/), { target: { value: 'Faire' } })
  fireEvent.click(screen.getByRole('button', { name: 'Créer la tâche' }))
  await waitFor(() => expect(posts).toHaveLength(1))
  await waitFor(() => expect(title()).toHaveAttribute('readonly'))
  expect(screen.getByLabelText(/^Objectif/)).toHaveAttribute('readonly')
  expect(screen.getByLabelText(/^Prochaine action/)).toHaveAttribute('readonly')
  expect(screen.getByLabelText(/^Preuve attendue/)).toHaveAttribute('readonly')
  expect(screen.getByLabelText('Colonne')).toBeDisabled()
  expect(screen.getByLabelText('Priorité')).toBeDisabled()
  expect(screen.getByLabelText('Agent principal')).toBeDisabled()
  expect(screen.getByLabelText('Échéance')).toHaveAttribute('readonly')
  expect(posts[0]).toMatchObject({ title: 'Original' })
  expect(screen.getByRole('status')).toHaveTextContent('Envoi en cours…')
  await act(async () => { release() })
})

test('annuler puis rouvrir la même cible pendant l’envoi : tout reste figé, la réponse vide le brouillon sans perdre de saisie', async () => {
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posts.push(JSON.parse(String(init.body)))
      await gate
      return Response.json({ ...BASE, id: 'nx-task-20', title: 'créée' })
    }
    return Response.json([])
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const closes: boolean[] = []
  const view = (open: boolean, f: string | null) => (
    <QueryClientProvider client={client}>
      <CreateTaskDialog open={open} follows={f} tasks={TASKS} onOpenChange={(o) => closes.push(o)} />
    </QueryClientProvider>
  )
  const { rerender } = render(view(true, 'nx-task-7'))
  fill('Premier')
  fireEvent.change(screen.getByLabelText(/^Objectif/), { target: { value: 'Faire' } })
  fireEvent.click(screen.getByRole('button', { name: 'Créer la tâche' }))
  await waitFor(() => expect(posts).toHaveLength(1))

  rerender(view(false, 'nx-task-7'))
  rerender(view(true, 'nx-task-7'))
  // Rouverte sur la même cible : figée, aucune saisie possible avant la réponse.
  expect(title()).toHaveAttribute('readonly')
  expect(screen.getByLabelText(/^Objectif/)).toHaveAttribute('readonly')
  expect(screen.getByRole('button', { name: 'Créer la tâche' })).toBeDisabled()
  // Changer de cible pendant l'envoi : le formulaire de l'autre cible est figé aussi.
  rerender(view(true, 'nx-task-9'))
  expect(title()).toHaveAttribute('readonly')
  expect(posts).toHaveLength(1)
  // Le gel dit pourquoi, même sur une cible pour laquelle rien n'a été envoyé.
  expect(screen.getByRole('status')).toHaveTextContent('Envoi en cours…')

  rerender(view(true, 'nx-task-7'))
  await act(async () => { release() })
  await waitFor(() => expect(closes).toContain(false))
  expect(title().value).toBe('')
  expect(title()).not.toHaveAttribute('readonly')
  expect(screen.queryByText('Envoi en cours…')).toBeNull()
})
