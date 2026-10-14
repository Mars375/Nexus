import type { HistoryEntry, Status } from '@/api'
import { ACTOR_NAME, STATUS_LABEL, actorName } from './vocabulary'

/** French labels (with article) of the fields `PATCH /api/tasks/{id}` can change: `UPDATABLE` in server/src/nexus/tasks/service.py. */
const FIELD_LABEL: Record<string, string> = {
  title: 'le titre',
  objective: 'l’objectif',
  human_owner: 'le propriétaire',
  lead_agent: 'l’agent principal',
  collaborators: 'les collaborateurs',
  next_action: 'la prochaine action',
  due_at: 'l’échéance',
  follow_up_at: 'la relance',
  expected_evidence: 'la preuve attendue',
  priority: 'la priorité',
  operation_role: 'le rôle d’opération',
  origin: 'l’origine',
  context: 'le contexte',
}

/** Beyond this many fields, the list would be longer than the sentence is useful. */
const MAX_LISTED_FIELDS = 3

function describeLead(actor: string, change: unknown): string {
  // `changes.lead_agent` is `[before, after]`. Only a known agent name is ever printed.
  if (!Array.isArray(change) || change.length !== 2) return 'a changé l’agent principal'
  const after: unknown = change[1]
  if (after === null) return 'a retiré l’agent principal'
  if (typeof after !== 'string' || !Object.hasOwn(ACTOR_NAME, after)) return 'a changé l’agent principal'
  return after === actor ? 'est devenu agent principal' : `a confié la tâche à ${actorName(after)}`
}

function statusLabel(status: unknown): string {
  // Only an own key of the table is a status: `toString` or `__proto__` would not be a label.
  return typeof status === 'string' && Object.hasOwn(STATUS_LABEL, status)
    ? STATUS_LABEL[status as Status].toLowerCase()
    : '?'
}

function joinFrench(items: string[]): string {
  return items.length < 2 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} et ${items[items.length - 1]}`
}

/** What happened, in French. Field values are never printed (they may hold a masked secret). */
export function describeHistory(entry: HistoryEntry): string {
  const c = entry.changes
  switch (entry.action) {
    case 'created':
      return 'a créé la tâche'
    case 'status': {
      // `changes.status` is `[from, to]`; anything else must not throw.
      if (!Array.isArray(c.status) || c.status.length !== 2) return 'a changé le statut'
      const [from, to] = c.status
      return `l'a passée de ${statusLabel(from)} à ${statusLabel(to)}`
    }
    case 'updated': {
      const keys = Object.keys(c)
      if (keys.length === 1 && keys[0] === 'lead_agent') return describeLead(entry.actor, c.lead_agent)
      if (keys.length === 1 && keys[0] === 'evidence') return 'a joint une preuve'
      if (keys.length > 1 && keys.includes('lead_agent')) {
        // Same rules as the single-key case for the lead part, then the other fields (unknown ones stay generic).
        const others = keys.filter((key) => key !== 'lead_agent')
        const otherLabels = others.map((key) => (Object.hasOwn(FIELD_LABEL, key) ? FIELD_LABEL[key] : null))
        const rest = others.length > MAX_LISTED_FIELDS || otherLabels.some((l) => l === null)
          ? others.length === 1 ? 'un champ' : 'plusieurs champs'
          : joinFrench(otherLabels as string[])
        const lead = describeLead(entry.actor, c.lead_agent)
        // « est devenu » takes « être »: the second verb needs its own auxiliary.
        return `${lead} et ${lead.startsWith('est ') ? 'a modifié' : 'modifié'} ${rest}`
      }
      const labels = keys.map((key) => (Object.hasOwn(FIELD_LABEL, key) ? FIELD_LABEL[key] : null))
      if (keys.length === 1) return labels[0] ? `a modifié ${labels[0]}` : 'a modifié un champ'
      if (keys.length <= MAX_LISTED_FIELDS && labels.every((l) => l !== null)) {
        return `a modifié ${joinFrench(labels as string[])}`
      }
      return 'a modifié plusieurs champs'
    }
    case 'commented':
      return 'a commenté'
    case 'linked':
      return 'a ajouté une dépendance'
    case 'unlinked':
      return 'a retiré une dépendance'
    case 'secret_redacted':
      return 'a collé un secret, masqué automatiquement'
    default:
      return entry.action
  }
}
