import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { NowAsk, NowSnapshot } from '@/api'
import { formatDateTime } from '@/format'
import { approval, ask } from './fixtures'
import { NowView } from './NowView'

const empty: NowSnapshot = {
  source: 'nexus.db', measured_at: new Date().toISOString(), operation: null, auxiliaries: [],
  agents: [{ agent: 'helios', state: 'idle', task: null, title: null, run: null, since: null }],
  asks: [], blocks: [], done: [],
}
const needsHuman = (over: Partial<NowAsk> = {}): NowAsk => ask({
  kind: 'needs_human', agent: 'helios', subject: 'Publier la v2 ?', consequence: 'La v2 part chez les clients.',
  options: ['Avec la vidéo', 'Sans la vidéo'], approval: approval({ ref: 'nx-appr-2' }), event: 'nx-evt-2', ...over,
})

type Post = { url: string; body: Record<string, unknown> }
type Server = { now: NowSnapshot; posts: Post[]; nowReads: number; failNow: boolean; reply: (post: Post) => Response | Promise<Response> }

const ok = () => Response.json({ ok: true })
const refusal = (code: string, message: string, status = 409) => Response.json({ detail: { code, message } }, { status })

function serve(asks: NowAsk[]): Server {
  const srv: Server = { now: { ...empty, asks }, posts: [], nowReads: 0, failNow: false, reply: ok }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/nodes') return Response.json([])
    if (init?.method === 'POST') {
      const post = { url, body: JSON.parse(String(init.body)) }
      srv.posts.push(post)
      return srv.reply(post)
    }
    srv.nowReads += 1
    if (srv.failNow) return new Response('', { status: 500 })
    return Response.json(srv.now)
  }))
  return srv
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><NowView /></QueryClientProvider>)
  return client
}
const refetch = (client: QueryClient) => act(() => client.refetchQueries({ queryKey: ['now'] }))
const panel = () => screen.getByRole('complementary', { name: 'Système' })

async function open(subject: string | RegExp = 'Python ?') {
  const header = await screen.findByRole('button', { name: subject })
  if (header.getAttribute('aria-expanded') !== 'true') fireEvent.click(header)
  return header
}
const hoursFromNow = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString()

afterEach(() => vi.unstubAllGlobals())

// --- state chips -------------------------------------------------------------------------------

test('une demande sans approbation d\'avant le suivi ne se dit jamais « en attente » ni « à toi-même »', async () => {
  serve([ask({ approval: null })]); show()
  await screen.findByText('Python ?')
  expect(screen.getByText('sans suivi d\'approbation (demande antérieure au suivi)')).toBeInTheDocument()
  expect(within(panel()).queryByText(/en attente/i, { selector: '[data-chip]' })).toBeNull()
  expect(within(panel()).queryByText(/toi-même/)).toBeNull()
  expect(document.querySelector('[data-chip="pending"]')).toBeNull()
})

test('une demande que Loïc s\'adresse à lui seul n\'est pas dite « antérieure »', async () => {
  serve([ask({ agent: 'loic', approval: null })]); show()
  await screen.findByText('Python ?')
  expect(screen.getByText('demande que tu t\'adresses à toi-même : rien à décider ici')).toBeInTheDocument()
  expect(within(panel()).queryByText(/antérieure/)).toBeNull()
  expect(document.querySelector('[data-chip="pending"]')).toBeNull()
  expect(screen.queryByRole('textbox')).toBeNull()
})

test('« en attente » seulement pour une approbation pending, gris pour les demandes traitées', async () => {
  const decided = { decided_by: 'loic' as const, decided_at: new Date().toISOString() }
  serve([
    ask({ event: 'nx-evt-1', subject: 'Q1', approval: approval({ ref: 'nx-appr-1' }) }),
    ask({ event: 'nx-evt-3', subject: 'Q3', approval: approval({ ref: 'nx-appr-3', status: 'answered', ...decided }) }),
    needsHuman({ event: 'nx-evt-4', subject: 'V4', approval: approval({ ref: 'nx-appr-4', status: 'approved', ...decided }) }),
    needsHuman({ event: 'nx-evt-5', subject: 'V5', approval: approval({ ref: 'nx-appr-5', status: 'rejected', ...decided }) }),
    ask({ event: 'nx-evt-6', subject: 'Q6', approval: approval({ ref: 'nx-appr-6', status: 'expired', expires_at: new Date(Date.now() - 60_000).toISOString() }) }),
  ]); show()
  await screen.findByText('Q1')
  const chip = (text: string) => within(panel()).getByText(text, { selector: '[data-chip]' })
  expect(chip('en attente')).toHaveAttribute('data-chip', 'pending')
  for (const [text, tone] of [['répondue', 'treated'], ['validée', 'treated'], ['refusée', 'treated'], ['expirée', 'treated']]) {
    expect(chip(text)).toHaveAttribute('data-chip', tone)
  }
  expect(within(panel()).getAllByText('en attente', { selector: '[data-chip]' })).toHaveLength(1)
})

test('une demande en attente avec échéance dit quand elle expire', async () => {
  serve([ask({ approval: approval({ expires_at: hoursFromNow(3) }) })]); show()
  expect(await screen.findByText('expire dans 3 h')).toBeInTheDocument()
})

test('une demande traitée dit qui a décidé et quand, sans formulaire', async () => {
  serve([ask({ approval: approval({ status: 'answered', decided_by: 'loic', decided_at: '2026-10-07T14:05:00+02:00' }) })]); show()
  await open()
  expect(screen.getByText(`Répondue par Loïc le ${formatDateTime('2026-10-07T14:05:00+02:00')}.`)).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Répondre' })).toBeNull()
})

test('le titre de la demande déplie son détail, au clavier comme à la souris', async () => {
  serve([ask({ body: 'Quelle version de Python cibler pour le pont ?' })]); show()
  const header = await screen.findByRole('button', { name: 'Python ?' })
  expect(header).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByText('Quelle version de Python cibler pour le pont ?')).toBeNull()
  header.focus()
  fireEvent.click(header) // Enter and Space on a button are clicks
  expect(header).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByText('Quelle version de Python cibler pour le pont ?')).toBeInTheDocument()
})

// --- question ----------------------------------------------------------------------------------

test('Répondre est désactivé tant que le texte est vide, avec la raison à côté', async () => {
  serve([ask()]); show()
  await open()
  const send = screen.getByRole('button', { name: 'Répondre' })
  expect(send).toBeDisabled()
  expect(screen.getByText('Écris une réponse pour pouvoir répondre.')).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: '   ' } })
  expect(send).toBeDisabled()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Python 3.13' } })
  expect(send).toBeEnabled()
  expect(screen.queryByText('Écris une réponse pour pouvoir répondre.')).toBeNull()
})

test('les champs de saisie reprennent les limites du serveur', async () => {
  serve([ask(), needsHuman()]); show()
  await open('Python ?'); await open('Publier la v2 ?')
  expect(screen.getByRole('textbox', { name: 'Ta réponse' })).toHaveAttribute('maxlength', '2000')
  expect(screen.getByRole('textbox', { name: /Note/ })).toHaveAttribute('maxlength', '2000')
})

test('une option de la question remplit la réponse sans l\'envoyer', async () => {
  const srv = serve([ask({ options: ['3.12', '3.13'] })]); show()
  await open()
  fireEvent.click(screen.getByRole('button', { name: '3.13' }))
  expect(screen.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('3.13')
  expect(srv.posts).toHaveLength(0)
  expect(screen.getByRole('button', { name: 'Répondre' })).toBeEnabled()
})

test('répondre envoie le texte à la route de la demande, puis relit Maintenant', async () => {
  const srv = serve([ask()]); show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: '  Python 3.13  ' } })
  const reads = srv.nowReads
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  await waitFor(() => expect(srv.posts).toEqual([{ url: '/api/approvals/nx-appr-1/answer', body: { text: '  Python 3.13  ' } }]))
  await waitFor(() => expect(srv.nowReads).toBeGreaterThan(reads))
})

test('un double clic n\'envoie qu\'une requête', async () => {
  const srv = serve([ask()]); show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Oui' } })
  srv.reply = () => new Promise<Response>(() => {})
  const send = screen.getByRole('button', { name: 'Répondre' })
  // Same tick: React has not re-rendered the disabled button yet, only the in-flight guard can stop the second one.
  act(() => { fireEvent.click(send); fireEvent.click(send); fireEvent.click(send) })
  expect(srv.posts).toHaveLength(1)
  expect(await screen.findByText('Envoi…')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Répondre' })).toBeDisabled()
})

// --- needs_human -------------------------------------------------------------------------------

test('la conséquence est « annoncée par » l\'agent, jamais présentée comme un fait', async () => {
  serve([needsHuman()]); show()
  await open('Publier la v2 ?')
  expect(screen.getByText(/Conséquence annoncée par Helios/)).toBeInTheDocument()
  expect(screen.getByText(/La v2 part chez les clients\./)).toBeInTheDocument()
})

test('une conséquence absente est signalée en orange', async () => {
  serve([needsHuman({ consequence: null })]); show()
  await open('Publier la v2 ?')
  const flag = screen.getByText('Conséquence non précisée par l\'agent')
  expect(flag.className).toContain('text-attention')
})

test('les options sont des boutons radio dont la valeur est l\'indice d\'origine, un vide au milieu compris', async () => {
  serve([needsHuman({ options: ['Avec la vidéo', '', 'Sans la vidéo'] })]); show()
  await open('Publier la v2 ?')
  const radios = screen.getAllByRole('radio')
  expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual(['0', '2'])
  expect(screen.getByRole('radio', { name: 'Sans la vidéo' })).toHaveAttribute('value', '2')
})

test('avec deux options ou plus, Valider exige un choix et dit pourquoi ; Refuser reste possible', async () => {
  serve([needsHuman()]); show()
  await open('Publier la v2 ?')
  expect(screen.getByRole('button', { name: 'Valider' })).toBeDisabled()
  expect(screen.getByText('Choisis une option pour pouvoir valider.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Refuser' })).toBeEnabled()
  fireEvent.click(screen.getByRole('radio', { name: 'Sans la vidéo' }))
  expect(screen.getByRole('button', { name: 'Valider' })).toBeEnabled()
  expect(screen.queryByText('Choisis une option pour pouvoir valider.')).toBeNull()
})

test('une seule option non vide : pas de choix obligatoire', async () => {
  serve([needsHuman({ options: ['Seule', '  '] })]); show()
  await open('Publier la v2 ?')
  expect(screen.getByRole('button', { name: 'Valider' })).toBeEnabled()
})

test('valider envoie la décision, le choix et la note ; refuser n\'envoie pas le choix', async () => {
  const srv = serve([needsHuman()]); show()
  await open('Publier la v2 ?')
  fireEvent.click(screen.getByRole('radio', { name: 'Sans la vidéo' }))
  fireEvent.change(screen.getByRole('textbox', { name: /Note/ }), { target: { value: 'Go' } })
  fireEvent.click(screen.getByRole('button', { name: 'Valider' }))
  await waitFor(() => expect(srv.posts).toHaveLength(1))
  expect(srv.posts[0]).toEqual({ url: '/api/approvals/nx-appr-2/decision', body: { decision: 'approved', choice: 1, note: 'Go' } })
})

test('refuser n\'envoie ni choix ni note vide', async () => {
  const srv = serve([needsHuman()]); show()
  await open('Publier la v2 ?')
  fireEvent.click(screen.getByRole('radio', { name: 'Sans la vidéo' }))
  fireEvent.click(screen.getByRole('button', { name: 'Refuser' }))
  await waitFor(() => expect(srv.posts).toHaveLength(1))
  expect(srv.posts[0].body).toEqual({ decision: 'rejected' })
})

test('Valider et Refuser sont désactivés pendant l\'envoi, une seule requête part', async () => {
  const srv = serve([needsHuman({ options: [] })]); show()
  await open('Publier la v2 ?')
  srv.reply = () => new Promise<Response>(() => {})
  const [valider, refuser] = [screen.getByRole('button', { name: 'Valider' }), screen.getByRole('button', { name: 'Refuser' })]
  act(() => { fireEvent.click(valider); fireEvent.click(refuser) })
  expect(srv.posts).toHaveLength(1)
  expect(await screen.findByText('Envoi…')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Valider' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Refuser' })).toBeDisabled()
})

// --- errors, drafts and changing data ----------------------------------------------------------

test('une erreur du serveur s\'affiche sous le formulaire avec son message, jamais le texte saisi', async () => {
  const srv = serve([ask()]); show()
  await open()
  const secret = 'texte-prive-de-loic'
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: secret } })
  srv.reply = () => refusal('answer_required', 'text : la réponse est vide')
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('text : la réponse est vide')
  expect(alert.textContent).not.toContain(secret)
  expect(screen.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue(secret) // the draft is kept
  expect(screen.getByRole('button', { name: 'Répondre' })).toBeEnabled() // and can be sent again
})

test('un serveur injoignable : message français générique, saisie conservée', async () => {
  const srv = serve([ask()]); show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'abc' } })
  srv.reply = () => { throw new TypeError('Failed to fetch') }
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Le serveur Nexus ne répond pas')
  expect(screen.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('abc')
})

test('le brouillon survit à la relecture de Maintenant', async () => {
  const srv = serve([ask(), needsHuman()]); const client = show()
  await open('Python ?'); await open('Publier la v2 ?')
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Ma réponse en cours' } })
  fireEvent.click(screen.getByRole('radio', { name: 'Avec la vidéo' }))
  fireEvent.change(screen.getByRole('textbox', { name: /Note/ }), { target: { value: 'Ma note' } })
  // the agent changes the data meanwhile: a new request arrives first, the order changes
  srv.now = { ...srv.now, measured_at: new Date().toISOString(), asks: [ask({ event: 'nx-evt-9', subject: 'Nouvelle', approval: approval({ ref: 'nx-appr-9' }) }), ...srv.now.asks.slice().reverse()] }
  await refetch(client)
  await screen.findByText('Nouvelle')
  expect(screen.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('Ma réponse en cours')
  expect(screen.getByRole('radio', { name: 'Avec la vidéo' })).toBeChecked()
  expect(screen.getByRole('textbox', { name: /Note/ })).toHaveValue('Ma note')
})

test('traitée entre-temps : bandeau, brouillon visible, envoi bloqué', async () => {
  const srv = serve([ask()]); const client = show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Ma réponse' } })
  srv.now = { ...srv.now, asks: [ask({ approval: approval({ status: 'answered', decided_by: 'loic', decided_at: new Date().toISOString() }) })] }
  await refetch(client)
  expect(await screen.findByText('Traitée entre-temps par Loïc : ta réponse n\'a pas été envoyée')).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('Ma réponse')
  expect(screen.getByRole('button', { name: 'Répondre' })).toBeDisabled()
})

test('expirée entre-temps : bandeau, brouillon visible, envoi bloqué', async () => {
  const srv = serve([needsHuman()]); const client = show()
  await open('Publier la v2 ?')
  fireEvent.click(screen.getByRole('radio', { name: 'Avec la vidéo' }))
  srv.now = { ...srv.now, asks: [needsHuman({ approval: approval({ ref: 'nx-appr-2', status: 'expired', expires_at: new Date(Date.now() - 1000).toISOString() }) })] }
  await refetch(client)
  expect(await screen.findByText('Expirée entre-temps : ta décision n\'a pas été envoyée')).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: 'Avec la vidéo' })).toBeChecked()
  expect(screen.getByRole('button', { name: 'Valider' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Refuser' })).toBeDisabled()
})

test('une demande expirée sans brouillon dit son échéance, sans formulaire', async () => {
  const expires = new Date(Date.now() - 3_600_000).toISOString()
  serve([ask({ options: ['3.12'], approval: approval({ status: 'expired', expires_at: expires }) })]); show()
  await open()
  expect(screen.getByText((t) => t.startsWith(`Expirée le ${formatDateTime(expires)}`))).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Répondre' })).toBeNull()
  expect(screen.queryByRole('button', { name: '3.12' })).toBeNull()
})

test('l\'échéance n\'est jamais annoncée pour une demande traitée', async () => {
  serve([ask({ approval: approval({ status: 'answered', expires_at: hoursFromNow(3), decided_by: 'loic', decided_at: new Date().toISOString() }) })]); show()
  await screen.findByText('Python ?')
  expect(screen.queryByText(/expire/)).toBeNull()
})

test('le brouillon d\'une demande traitée ailleurs est copiable, en lecture seule, et s\'efface', async () => {
  const srv = serve([ask()]); const client = show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Ma réponse' } })
  srv.now = { ...srv.now, asks: [ask({ approval: approval({ status: 'answered', decided_by: 'loic', decided_at: new Date().toISOString() }) })] }
  await refetch(client)
  const box = await screen.findByRole('textbox', { name: 'Ta réponse' })
  expect(box).toHaveAttribute('readonly')
  expect(box).not.toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Effacer le brouillon' }))
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.queryByText(/entre-temps/)).toBeNull()
})

test('un envoi sans réponse du serveur relit Maintenant et n\'affirme pas que rien n\'est parti', async () => {
  const srv = serve([ask()]); show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Ma réponse' } })
  const reads = srv.nowReads
  srv.reply = () => {
    // the server committed, the answer was lost on the way
    srv.now = { ...srv.now, asks: [ask({ approval: approval({ status: 'answered', decided_by: 'loic', decided_at: new Date().toISOString() }) })] }
    throw new TypeError('Failed to fetch')
  }
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  expect(await screen.findByText(/Traitée entre-temps par Loïc : l'envoi n'a pas eu de réponse, vérifie que c'est bien ta réponse/)).toBeInTheDocument()
  expect(srv.nowReads).toBeGreaterThan(reads)
  expect(screen.queryByText(/n'a pas été envoyée/)).toBeNull()
})

test('tout refus du serveur relit Maintenant, même un conflit de version', async () => {
  const srv = serve([ask()]); show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Ma réponse' } })
  srv.reply = () => refusal('approval_concurrent_update', 'la demande change sans cesse : relis et réessaie')
  const reads = srv.nowReads
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  await screen.findByRole('alert')
  await waitFor(() => expect(srv.nowReads).toBeGreaterThan(reads))
})

test('« Réponse envoyée. » reste affiché après un succès, même si la relecture échoue', async () => {
  const srv = serve([ask()]); show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Ma réponse' } })
  srv.reply = () => { srv.failNow = true; return ok() }
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  expect(await screen.findByText('Réponse envoyée.')).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).toBeNull()
})

test('le focus va à l\'alerte après une erreur et au message d\'état après un succès', async () => {
  const srv = serve([ask(), needsHuman({ options: [] })]); show()
  await open('Python ?'); await open('Publier la v2 ?')
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'abc' } })
  srv.reply = () => refusal('answer_required', 'text : la réponse est vide')
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  const alert = await screen.findByRole('alert')
  await waitFor(() => expect(alert).toHaveFocus())
  srv.reply = ok
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  const done = await screen.findByText('Réponse envoyée.')
  await waitFor(() => expect(done).toHaveFocus())
})

test('une région live est toujours montée dans la carte, même repliée', async () => {
  serve([ask()]); show()
  await screen.findByText('Python ?')
  expect(document.querySelector('article[data-ask] [aria-live="polite"]')).not.toBeNull()
})

test('409 déjà traitée : la demande est relue et le bandeau apparaît, la saisie reste', async () => {
  const srv = serve([ask()]); show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Ma réponse' } })
  srv.now = { ...srv.now, asks: [ask({ approval: approval({ status: 'answered', decided_by: 'loic', decided_at: new Date().toISOString() }) })] }
  srv.reply = () => refusal('approval_already_decided', 'déjà répondue par loic le 07/10/2026 à 14:05')
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  expect(await screen.findByText(/Traitée entre-temps par Loïc/)).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent('déjà répondue par loic')
  expect(screen.getByRole('textbox', { name: 'Ta réponse' })).toHaveValue('Ma réponse')
})

test('409 expirée : la demande est relue et le bandeau « Expirée entre-temps » apparaît', async () => {
  const srv = serve([ask()]); show()
  await open()
  fireEvent.change(screen.getByRole('textbox', { name: 'Ta réponse' }), { target: { value: 'Ma réponse' } })
  srv.now = { ...srv.now, asks: [ask({ approval: approval({ status: 'expired', expires_at: new Date(Date.now() - 1000).toISOString() }) })] }
  srv.reply = () => refusal('approval_expired', 'cette demande a expiré')
  fireEvent.click(screen.getByRole('button', { name: 'Répondre' }))
  expect(await screen.findByText(/Expirée entre-temps/)).toBeInTheDocument()
})

// --- tile, list, floor -------------------------------------------------------------------------

test('la tuile ne compte que les demandes en attente', async () => {
  serve([
    ask({ event: 'nx-evt-1' }),
    ask({ event: 'nx-evt-2', approval: approval({ ref: 'nx-appr-2', status: 'answered', decided_by: 'loic', decided_at: new Date().toISOString() }) }),
    ask({ event: 'nx-evt-3', approval: null }),
    ask({ event: 'nx-evt-4', approval: approval({ ref: 'nx-appr-4', status: 'expired' }) }),
  ]); show()
  expect(await screen.findByRole('group', { name: 'Demandes en attente' })).toHaveTextContent('1')
})

test('sans demande en attente la tuile dit 0 et n\'est pas orange', async () => {
  serve([ask({ approval: null })]); show()
  const tile = await screen.findByRole('group', { name: 'Demandes en attente' })
  expect(tile).toHaveTextContent('0')
  expect(tile.innerHTML).not.toContain('text-attention')
})

test('liste vide : on dit qu\'il n\'y a rien en attente ni traité récemment', async () => {
  serve([]); show()
  expect(await screen.findByText('Aucune demande en attente ni traitée récemment.')).toBeInTheDocument()
})

test('la balise du poste et les fiches de la table ne comptent que les demandes en attente', async () => {
  serve([
    ask({ event: 'nx-evt-1', agent: 'mnema', subject: 'Une' }),
    ask({ event: 'nx-evt-2', agent: 'helios', subject: 'Deux', approval: approval({ ref: 'nx-appr-2', status: 'approved', decided_by: 'loic', decided_at: new Date().toISOString() }) }),
    ask({ event: 'nx-evt-3', agent: 'helios', subject: 'Trois', approval: null }),
  ]); show()
  await screen.findByText('Une')
  expect(document.querySelector('[data-ticket="nx-evt-1"]')).not.toBeNull()
  expect(document.querySelector('[data-ticket="nx-evt-2"]')).toBeNull()
  expect(document.querySelector('[data-ticket="nx-evt-3"]')).toBeNull()
  expect(document.querySelector('[data-agent="helios"]')!.getAttribute('data-wait')).toBe('false')
  expect(screen.getByText('1 demande')).toBeInTheDocument()
})
