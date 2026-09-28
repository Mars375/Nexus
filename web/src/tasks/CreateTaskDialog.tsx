import { useState, type FormEvent } from 'react'
import type { Actor, Priority } from '@/api'
import { localInputToIso } from '@/format'
import { Button, Dialog, Field, inputClass } from '@/ui'
import { useCreateTask } from './queries'
import { ACTOR_NAME, ACTORS, PRIORITY_LABEL } from './vocabulary'

export function CreateTaskDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const create = useCreateTask()
  const empty = {
    title: '',
    objective: '',
    next_action: '',
    status: 'backlog' as 'backlog' | 'todo',
    lead_agent: '',
    priority: 'normal' as Priority,
    due_at: '',
    expected_evidence: '',
  }
  const [form, setForm] = useState(empty)
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const ready =
    form.title.trim() && form.objective.trim() && (form.status === 'backlog' || form.next_action.trim())

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      {
        title: form.title.trim(),
        objective: form.objective.trim(),
        status: form.status,
        next_action: form.next_action.trim() || null,
        lead_agent: (form.lead_agent || null) as Actor | null,
        priority: form.priority,
        due_at: localInputToIso(form.due_at),
        expected_evidence: form.expected_evidence.trim() || null,
      },
      {
        onSuccess: () => {
          setForm(empty)
          onOpenChange(false)
        },
      },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Nouvelle tâche"
      description="Créer une tâche ne lance aucun agent."
    >
      <form onSubmit={submit} className="grid gap-3">
        <Field label="Titre">
          <input className={inputClass} maxLength={200} value={form.title} onChange={(e) => set('title', e.target.value)} autoFocus />
        </Field>
        <Field label="Objectif" hint="En une phrase : à quoi on reconnaît que c'est fait.">
          <textarea className={inputClass} rows={2} value={form.objective} onChange={(e) => set('objective', e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Colonne">
            <select className={inputClass} value={form.status} onChange={(e) => set('status', e.target.value as 'backlog' | 'todo')}>
              <option value="backlog">Plus tard</option>
              <option value="todo">À faire</option>
            </select>
          </Field>
          <Field label="Priorité">
            <select className={inputClass} value={form.priority} onChange={(e) => set('priority', e.target.value as Priority)}>
              {(Object.keys(PRIORITY_LABEL) as Priority[]).map((p) => (
                <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>
              ))}
            </select>
          </Field>
          <Field label="Agent principal">
            <select className={inputClass} value={form.lead_agent} onChange={(e) => set('lead_agent', e.target.value)}>
              <option value="">Personne</option>
              {ACTORS.map((a) => (
                <option key={a} value={a}>{ACTOR_NAME[a]}</option>
              ))}
            </select>
          </Field>
          <Field label="Échéance">
            <input type="datetime-local" className={inputClass} value={form.due_at} onChange={(e) => set('due_at', e.target.value)} />
          </Field>
        </div>
        <Field
          label="Prochaine action"
          hint={form.status === 'todo' ? 'Obligatoire pour une tâche à faire.' : undefined}
        >
          <textarea className={inputClass} rows={2} value={form.next_action} onChange={(e) => set('next_action', e.target.value)} />
        </Field>
        <Field label="Preuve attendue" hint="Facultatif. Si renseignée, la tâche ne se clôt pas sans preuve.">
          <input className={inputClass} value={form.expected_evidence} onChange={(e) => set('expected_evidence', e.target.value)} />
        </Field>
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Annuler
          </Button>
          <Button type="submit" variant="primary" disabled={!ready || create.isPending}>
            Créer la tâche
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
