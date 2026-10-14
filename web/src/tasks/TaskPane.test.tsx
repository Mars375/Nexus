import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { Task } from '@/api'
import { TaskPane } from './TaskPane'

const TASK: Task = {
  id: 'nx-task-1',
  title: 'Pont lecture',
  objective: 'Lire les runs',
  status: 'todo',
  human_owner: 'loic',
  lead_agent: null,
  collaborators: [],
  next_action: 'relever les tables',
  due_at: null,
  follow_up_at: null,
  block_cause: null,
  block_plan: null,
  drop_reason: null,
  expected_evidence: null,
  evidence: [],
  priority: 'normal',
  operation_role: null,
  origin: null,
  context: [],
  depends_on: [],
  follows: null,
  created_by: 'loic',
  created_at: '2026-09-28T10:00:00+02:00',
  updated_at: '2026-09-28T10:00:00+02:00',
  source: 'nexus.db',
  measured_at: '2026-09-28T10:00:00+02:00',
}

function renderPane(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  render(
    <QueryClientProvider client={client}>
      <TaskPane task={TASK} tasks={[TASK]} onClose={() => {}} onOpen={() => {}} onFollowUp={() => {}} />
    </QueryClientProvider>,
  )
  return client
}

afterEach(() => vi.unstubAllGlobals())

test('un premier chargement raté des détails le dit, au lieu d’une section vide', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('boom', { status: 500 })))

  renderPane()

  expect(await screen.findByText(/Impossible de lire les commentaires/)).toBeInTheDocument()
  expect(await screen.findByText(/Impossible de lire l’historique/)).toBeInTheDocument()
})

test('un rafraîchissement raté garde les détails connus, signalés comme non à jour', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const comment = { id: 'c1', author: 'loic', at: TASK.created_at, body: 'Premier jet' }
  const entry = { id: 1, actor: 'loic', at: TASK.created_at, action: 'created', changes: {} }
  client.setQueryData(['tasks', TASK.id, 'comments'], [comment])
  client.setQueryData(['tasks', TASK.id, 'history'], [entry])
  vi.stubGlobal('fetch', vi.fn(async () => new Response('boom', { status: 500 })))

  renderPane(client)
  await client.invalidateQueries()

  expect(await screen.findByText('Premier jet')).toBeInTheDocument()
  expect(await screen.findByText(/Commentaires non à jour/)).toBeInTheDocument()
  expect(await screen.findByText(/Historique non à jour/)).toBeInTheDocument()
})

test('un choix de dépendance devenu invalide reste affiché, avec sa raison, et bloque l’ajout', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json([])))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const current = { ...TASK, status: 'in_progress' as const }
  const prereq = { ...TASK, id: 'nx-task-2', title: 'Prérequis', status: 'dropped' as const }
  const other = { ...TASK, id: 'nx-task-3', title: 'Autre', status: 'dropped' as const }
  const pane = (tasks: Task[]) => (
    <QueryClientProvider client={client}>
      <TaskPane task={current} tasks={tasks} onClose={() => {}} onOpen={() => {}} onFollowUp={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(pane([current, prereq, other]))
  const picker = screen.getByLabelText('Tâche dont celle-ci dépend') as HTMLSelectElement
  const add = screen.getByRole('button', { name: 'Ajouter' })

  fireEvent.change(picker, { target: { value: 'nx-task-2' } })
  expect(add).toBeEnabled()

  // Un agent reprend le prérequis abandonné (dropped → backlog) pendant que Loïc hésite.
  rerender(pane([current, { ...prereq, status: 'backlog' }, other]))

  expect(picker.value).toBe('nx-task-2')
  expect(screen.getByRole('alert')).toHaveTextContent(/pas encore traitée/)
  expect(add).toBeDisabled()

  fireEvent.change(picker, { target: { value: 'nx-task-3' } })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(add).toBeEnabled()
})

test('un cycle apparu pendant la sélection est expliqué et bloque l’ajout', () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json([])))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const current = { ...TASK, status: 'todo' as const }
  const other = { ...TASK, id: 'nx-task-2', title: 'Autre', status: 'todo' as const }
  const pane = (tasks: Task[]) => (
    <QueryClientProvider client={client}>
      <TaskPane task={current} tasks={tasks} onClose={() => {}} onOpen={() => {}} onFollowUp={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(pane([current, other]))
  fireEvent.change(screen.getByLabelText('Tâche dont celle-ci dépend'), { target: { value: 'nx-task-2' } })

  // Un agent fait dépendre « Autre » de cette tâche : l'ajout créerait un cycle.
  rerender(pane([current, { ...other, depends_on: [current.id] }]))

  expect(screen.getByRole('alert')).toHaveTextContent(/cycle/)
  expect(screen.getByRole('button', { name: 'Ajouter' })).toBeDisabled()
})

test('le panneau dit d’où viennent la tâche, ses commentaires et son historique', async () => {
  const now = new Date().toISOString()
  const comment = { id: 1, task: TASK.id, author: 'loic', body: 'noté', at: now, source: 'nexus.db', measured_at: now }
  const entry = { id: 1, task: TASK.id, actor: 'loic', at: now, action: 'created', changes: {}, source: 'nexus.db', measured_at: now }
  vi.stubGlobal('fetch', vi.fn(async (url: string) =>
    Response.json(String(url).endsWith('/comments') ? [comment] : [entry]),
  ))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TaskPane task={{ ...TASK, measured_at: now }} tasks={[TASK]} onClose={() => {}} onOpen={() => {}} onFollowUp={() => {}} />
    </QueryClientProvider>,
  )
  await waitFor(() =>
    expect(screen.getAllByText(/^source : nexus\.db · mesuré il y a/)).toHaveLength(3),
  )
})

test('le panneau dit qui est l’agent principal, et suit la donnée vivante', () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json([])))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const pane = (task: Task) => (
    <QueryClientProvider client={client}>
      <TaskPane task={task} tasks={[task]} onClose={() => {}} onOpen={() => {}} onFollowUp={() => {}} />
    </QueryClientProvider>
  )
  const { rerender } = render(pane(TASK))
  expect(screen.getByText('Aucun agent principal')).toBeInTheDocument()

  rerender(pane({ ...TASK, lead_agent: 'helios', updated_at: '2026-09-28T11:00:00+02:00' }))
  expect(screen.getByText('Agent principal : Helios')).toBeInTheDocument()
  expect(screen.queryByText('Aucun agent principal')).not.toBeInTheDocument()
})

test('le libellé de l’agent principal ignore le brouillon du formulaire', () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json([])))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const task = { ...TASK, lead_agent: 'helios' as const }
  render(
    <QueryClientProvider client={client}>
      <TaskPane task={task} tasks={[task]} onClose={() => {}} onOpen={() => {}} onFollowUp={() => {}} />
    </QueryClientProvider>,
  )
  fireEvent.change(screen.getByLabelText('Agent principal'), { target: { value: 'hermes' } })
  expect(screen.getByLabelText('Agent principal')).toHaveValue('hermes')
  expect(screen.getByText('Agent principal : Helios')).toBeInTheDocument()
  expect(screen.queryByText('Agent principal : Hermes')).not.toBeInTheDocument()
})

test('un agent principal inconnu ne plante pas le panneau', () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json([])))
  const odd = 'inconnu' as unknown as Task['lead_agent']
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TaskPane task={{ ...TASK, lead_agent: odd }} tasks={[TASK]} onClose={() => {}} onOpen={() => {}} onFollowUp={() => {}} />
    </QueryClientProvider>,
  )
  expect(screen.getByText('Agent principal : Agent inconnu')).toBeInTheDocument()
})

test('l’historique nomme le changement d’agent principal', async () => {
  const now = new Date().toISOString()
  const entry = {
    id: 1, task: TASK.id, actor: 'helios', at: now, action: 'updated',
    changes: { lead_agent: [null, 'helios'] }, source: 'nexus.db', measured_at: now,
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string) =>
    Response.json(String(url).endsWith('/comments') ? [] : [entry]),
  ))
  renderPane()
  expect(await screen.findByText('Helios est devenu agent principal')).toBeInTheDocument()
})

// --- Tâche terminée : lecture seule (#65, ADR-022) ---

const DONE: Task = {
  ...TASK,
  status: 'done',
  lead_agent: 'helios',
  next_action: 'relever les tables',
  expected_evidence: 'un commit',
  evidence: ['commit:abc'],
}

type Callbacks = { onOpen?: (id: string) => void; onFollowUp?: (id: string) => void }

function stubApi(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response> = () => Response.json([]),
) {
  const calls: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined })
    return handler(String(url), init)
  }))
  return calls
}

function paneFor(task: Task, tasks: Task[], client: QueryClient, cb: Callbacks = {}) {
  return (
    <QueryClientProvider client={client}>
      <TaskPane task={task} tasks={tasks} onClose={() => {}} onOpen={cb.onOpen ?? (() => {})} onFollowUp={cb.onFollowUp ?? (() => {})} />
    </QueryClientProvider>
  )
}

const newClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

test('une tâche terminée s’affiche en lecture seule : ni transition, ni champ, ni enregistrement', () => {
  stubApi()
  render(paneFor(DONE, [DONE], newClient()))

  expect(screen.getByText(/Cette tâche ne se modifie plus/)).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Avancer' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'En cours' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Enregistrer' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Titre')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Objectif')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Prochaine action')).not.toBeInTheDocument()
  expect(screen.queryByText('relever les tables')).not.toBeInTheDocument()
  // Les détails restent lisibles.
  const details = screen.getByRole('heading', { name: 'Détails' }).closest('section')!
  expect(within(details).getByText('Lire les runs')).toBeInTheDocument()
  expect(within(details).getByText('un commit')).toBeInTheDocument()
  // La ligne de l’agent principal (#70) n’apparaît qu’une fois.
  expect(screen.getAllByText('Agent principal : Helios')).toHaveLength(1)
})

test('le résumé d’une tâche terminée sans agent principal le dit une seule fois', () => {
  stubApi()
  const t = { ...DONE, lead_agent: null }
  render(paneFor(t, [t], newClient()))
  expect(screen.getAllByText('Aucun agent principal')).toHaveLength(1)
})

test('une tâche non terminée garde ses boutons, son formulaire et pas de section « Terminée »', () => {
  stubApi()
  render(paneFor(TASK, [TASK], newClient()))
  expect(screen.getByRole('button', { name: 'En cours' })).toBeInTheDocument()
  expect(screen.getByLabelText('Titre')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Ouvrir une tâche de suite' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Joindre une preuve')).not.toBeInTheDocument()
})

test('une tâche terminée garde ses commentaires et son historique', async () => {
  const now = new Date().toISOString()
  const comment = { id: 1, task: DONE.id, author: 'loic', body: 'noté après coup', at: now, source: 'nexus.db', measured_at: now }
  stubApi((url) => Response.json(url.endsWith('/comments') ? [comment] : []))
  render(paneFor(DONE, [DONE], newClient()))
  expect(await screen.findByText('noté après coup')).toBeInTheDocument()
  expect(screen.getByLabelText('Nouveau commentaire')).toBeInTheDocument()
})

test('les preuves d’une tâche terminée restent affichées, avec « Joindre une preuve »', () => {
  stubApi()
  render(paneFor(DONE, [DONE], newClient()))
  expect(screen.getByText('commit:abc')).toBeInTheDocument()
  expect(screen.getByLabelText('Joindre une preuve')).toBeInTheDocument()
})

test('terminée sans preuve : la preuve attendue et l’absence de preuve sont dites', () => {
  stubApi()
  const t = { ...DONE, evidence: [] }
  render(paneFor(t, [t], newClient()))
  expect(screen.getByText(/Preuve attendue : un commit — aucune preuve jointe/)).toBeInTheDocument()
  expect(screen.getByLabelText('Joindre une preuve')).toBeInTheDocument()
})

test('joindre une preuve : une par ligne, vide ensuite, et l’historique se relit', async () => {
  const calls = stubApi((_url, init) => (init?.method === 'POST' ? Response.json(DONE) : Response.json([])))
  render(paneFor(DONE, [DONE], newClient()))
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/history'))).toBe(true))
  const historyBefore = calls.filter((c) => c.url.endsWith('/history')).length

  const field = screen.getByLabelText('Joindre une preuve')
  fireEvent.change(field, { target: { value: ' commit:def \n\nhttps://example.test/a,b\n' } })
  fireEvent.click(screen.getByRole('button', { name: 'Joindre' }))

  await waitFor(() => expect(field).toHaveValue(''))
  const post = calls.find((c) => c.method === 'POST')!
  expect(post.url).toMatch(/\/api\/tasks\/nx-task-1\/evidence$/)
  // Une preuve par ligne ; une virgule appartient à la preuve (un lien peut en contenir).
  expect(post.body).toEqual({ evidence: ['commit:def', 'https://example.test/a,b'] })
  await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/history')).length).toBeGreaterThan(historyBefore))
})

test('le bouton « Joindre » est désactivé sans preuve lisible, ou avec une ligne trop longue, motif à côté', () => {
  stubApi()
  render(paneFor(DONE, [DONE], newClient()))
  const field = screen.getByLabelText('Joindre une preuve')
  const button = screen.getByRole('button', { name: 'Joindre' })
  expect(button).toBeDisabled()

  fireEvent.change(field, { target: { value: '  \n  ' } })
  expect(button).toBeDisabled()

  fireEvent.change(field, { target: { value: 'x'.repeat(513) } })
  expect(button).toBeDisabled()
  expect(screen.getByText(/512 caractères/)).toBeInTheDocument()

  fireEvent.change(field, { target: { value: 'x'.repeat(512) } })
  expect(button).toBeEnabled()
  expect(screen.queryByText(/512 caractères/)).not.toBeInTheDocument()
})

test('une preuve refusée (déjà jointe par un agent) s’affiche sous le formulaire et garde le texte saisi', async () => {
  stubApi((_url, init) =>
    init?.method === 'POST'
      ? new Response(JSON.stringify({ detail: { code: 'evidence_unchanged', message: 'evidence : déjà jointe à la tâche' } }), { status: 409 })
      : Response.json([]),
  )
  render(paneFor(DONE, [DONE], newClient()))
  const field = screen.getByLabelText('Joindre une preuve')
  fireEvent.change(field, { target: { value: 'commit:abc' } })
  fireEvent.click(screen.getByRole('button', { name: 'Joindre' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('evidence : déjà jointe à la tâche')
  expect(field).toHaveValue('commit:abc')

  // Retoucher le texte efface le message périmé.
  fireEvent.change(field, { target: { value: 'commit:abcd' } })
  expect(screen.queryByText('evidence : déjà jointe à la tâche')).not.toBeInTheDocument()
})

test('une tâche terminée n’a ni « Retirer » ni sélecteur de dépendance', () => {
  stubApi()
  const prereq = { ...TASK, id: 'nx-task-2', title: 'Prérequis', status: 'done' as const }
  const other = { ...TASK, id: 'nx-task-3', title: 'Autre', status: 'done' as const }
  const t = { ...DONE, depends_on: ['nx-task-2'] }
  render(paneFor(t, [t, prereq, other], newClient()))
  expect(screen.getByText('Prérequis')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Retirer' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Tâche dont celle-ci dépend')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Ajouter' })).not.toBeInTheDocument()
})

test('un choix de dépendance en attente survit à la clôture : invalide, motif, abandon explicite', () => {
  stubApi()
  const client = newClient()
  const current = { ...TASK, status: 'in_progress' as const }
  const other = { ...TASK, id: 'nx-task-3', title: 'Autre', status: 'done' as const }
  const { rerender } = render(paneFor(current, [current, other], client))
  fireEvent.change(screen.getByLabelText('Tâche dont celle-ci dépend'), { target: { value: 'nx-task-3' } })
  expect(screen.getByRole('button', { name: 'Ajouter' })).toBeEnabled()

  // Un agent clôt la tâche pendant que le choix est fait mais pas ajouté.
  const closed = { ...current, status: 'done' as const, updated_at: '2026-09-28T11:00:00+02:00' }
  rerender(paneFor(closed, [closed, other], client))

  const picker = screen.getByLabelText('Tâche dont celle-ci dépend') as HTMLSelectElement
  expect(picker.value).toBe('nx-task-3')
  expect(screen.getByRole('alert')).toHaveTextContent('Cette tâche est terminée : ses dépendances ne changent plus.')
  expect(screen.getByRole('button', { name: 'Ajouter' })).toBeDisabled()
  expect(screen.queryByRole('option', { name: 'Ajouter une dépendance…' })).not.toBeInTheDocument()

  fireEvent.change(picker, { target: { value: '' } })
  expect(screen.queryByLabelText('Tâche dont celle-ci dépend')).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('« Ouvrir une tâche de suite » demande la boîte de création pour cette tâche', () => {
  stubApi()
  const onFollowUp = vi.fn()
  render(paneFor(DONE, [DONE], newClient(), { onFollowUp }))
  fireEvent.click(screen.getByRole('button', { name: 'Ouvrir une tâche de suite' }))
  expect(onFollowUp).toHaveBeenCalledWith('nx-task-1')
})

test('« Suivie par » liste les suites, calculées sur la liste complète, et les ouvre', () => {
  stubApi()
  const onOpen = vi.fn()
  const a = { ...TASK, id: 'nx-task-5', title: 'Correctif A', status: 'in_progress' as const, follows: 'nx-task-1' }
  const b = { ...TASK, id: 'nx-task-6', title: 'Correctif B', status: 'todo' as const, follows: 'nx-task-1' }
  const unrelated = { ...TASK, id: 'nx-task-7', title: 'Sans rapport', follows: 'nx-task-9' }
  render(paneFor(DONE, [DONE, a, b, unrelated], newClient(), { onOpen }))

  const list = screen.getByText(/Suivie par/).closest('section')!
  expect(within(list).getByRole('button', { name: /Correctif A/ })).toHaveTextContent('En cours')
  expect(within(list).getByRole('button', { name: /Correctif B/ })).toHaveTextContent('À faire')
  expect(within(list).queryByText(/Sans rapport/)).not.toBeInTheDocument()
  fireEvent.click(within(list).getByRole('button', { name: /Correctif B/ }))
  expect(onOpen).toHaveBeenCalledWith('nx-task-6')
})

test('une tâche de suite affiche « Suite de nx-task-N », avec le titre, et ouvre la tâche suivie', () => {
  stubApi()
  const onOpen = vi.fn()
  const followed = { ...DONE, id: 'nx-task-7', title: 'Livraison initiale' }
  const t = { ...TASK, id: 'nx-task-8', follows: 'nx-task-7' }
  render(paneFor(t, [t, followed], newClient(), { onOpen }))
  fireEvent.click(screen.getByRole('button', { name: /Suite de nx-task-7 — Livraison initiale/ }))
  expect(onOpen).toHaveBeenCalledWith('nx-task-7')
})

test('la tâche suivie absente de la liste ne plante pas : seule la référence est montrée', () => {
  stubApi()
  const t = { ...TASK, id: 'nx-task-8', follows: 'nx-task-7' }
  render(paneFor(t, [t], newClient()))
  expect(screen.getByRole('button', { name: 'Suite de nx-task-7' })).toBeInTheDocument()
})

test('la tâche se termine pendant un brouillon : il est gardé, l’envoi désactivé avec son motif, et on peut l’abandonner', () => {
  stubApi()
  const client = newClient()
  const { rerender } = render(paneFor(TASK, [TASK], client))
  fireEvent.change(screen.getByLabelText('Titre'), { target: { value: 'Titre retouché' } })
  expect(screen.getByRole('button', { name: 'Enregistrer' })).toBeEnabled()

  const closed = { ...TASK, status: 'done' as const, updated_at: '2026-09-28T11:00:00+02:00' }
  rerender(paneFor(closed, [closed], client))

  expect(screen.getByLabelText('Titre')).toHaveValue('Titre retouché')
  expect(screen.getByRole('button', { name: 'Enregistrer' })).toBeDisabled()
  expect(screen.getByText(/Cette tâche vient d’être terminée : tes modifications ne peuvent plus être enregistrées/)).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Abandonner le brouillon' }))
  expect(screen.queryByLabelText('Titre')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Enregistrer' })).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Détails' })).toBeInTheDocument()
  expect(screen.getByText('Lire les runs')).toBeInTheDocument()
})

test('la tâche se termine sans brouillon : le panneau bascule en lecture seule', () => {
  stubApi()
  const client = newClient()
  const { rerender } = render(paneFor(TASK, [TASK], client))
  expect(screen.getByLabelText('Titre')).toBeInTheDocument()

  const closed = { ...TASK, status: 'done' as const, updated_at: '2026-09-28T11:00:00+02:00' }
  rerender(paneFor(closed, [closed], client))

  expect(screen.queryByLabelText('Titre')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Enregistrer' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Ouvrir une tâche de suite' })).toBeInTheDocument()
})

test('le message d’une tâche terminée sans preuve ne propose plus de la rouvrir', () => {
  stubApi()
  const t = { ...DONE, evidence: [], expected_evidence: null }
  render(paneFor(t, [t], newClient()))
  expect(screen.queryByText(/rouvre-la/)).not.toBeInTheDocument()
})

test('l’historique d’une tâche de suite nomme la tâche suivie', async () => {
  const now = new Date().toISOString()
  const entry = {
    id: 1, task: TASK.id, actor: 'loic', at: now, action: 'created',
    changes: { follows: [null, 'nx-task-7'] }, source: 'nexus.db', measured_at: now,
  }
  stubApi((url) => Response.json(url.endsWith('/history') ? [entry] : []))
  render(paneFor(TASK, [TASK], newClient()))
  expect(await screen.findByText('Loïc a créé la tâche, suite de nx-task-7')).toBeInTheDocument()
})
