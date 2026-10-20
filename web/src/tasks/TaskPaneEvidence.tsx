import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, type Task } from '@/api'
import { useAuth } from '@/auth'
import { Button, inputClass } from '@/ui'
import { useAttachEvidence } from './queries'
import { Section } from './TaskPaneSection'

export function EvidenceList({ evidence }: { evidence: string[] }) {
  return (
    <ul className="grid gap-1 text-xs">
      {evidence.map((ref) => (
        <li key={ref} className="break-all">{ref}</li>
      ))}
    </ul>
  )
}

/** Longueur maximale d'une preuve (EVIDENCE_REF_MAX côté serveur), mesurée après dépouillement. */
const EVIDENCE_MAX = 512

/** Preuves d'une tâche terminée, toujours affichées, et « Joindre une preuve » (ajout seul). */
export function EvidenceSection({ task }: { task: Task }) {
  const attach = useAttachEvidence(task.id)
  const [text, setText] = useState('')
  // Un refus 401 n'a plus lieu d'être une fois le jeton saisi : on l'efface au déverrouillage.
  const { locked } = useAuth()
  const refusedAuth = attach.isError && attach.error instanceof ApiError && attach.error.status === 401
  const unlockable = useRef(false)
  unlockable.current = refusedAuth
  useEffect(() => {
    if (!locked && unlockable.current) attach.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seul le passage verrouillé -> déverrouillé compte
  }, [locked])
  // Une preuve par ligne : une virgule appartient à la preuve (un lien peut en contenir).
  const refs = text.split('\n').map((line) => line.trim()).filter(Boolean)
  // Le serveur compte des points de code, pas des unités UTF-16 : un émoji vaut un caractère.
  const tooLong = refs.some((ref) => [...ref].length > EVIDENCE_MAX)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (refs.length === 0 || tooLong || attach.isPending) return
    attach.mutate(refs, { onSuccess: () => setText('') })
  }

  return (
    <Section title="Preuves">
      {task.evidence.length > 0 ? (
        <EvidenceList evidence={task.evidence} />
      ) : (
        <p className="text-xs text-muted">
          {task.expected_evidence ? `Preuve attendue : ${task.expected_evidence} — aucune preuve jointe` : 'Aucune preuve jointe.'}
        </p>
      )}
      <form onSubmit={submit} className="mt-3 grid gap-2">
        <textarea
          className={inputClass}
          rows={2}
          value={text}
          // Figé pendant l'envoi : `reset()` détacherait la requête en vol (refus perdu, texte gardé
          // après un succès), et un succès viderait une retouche faite entre-temps.
          readOnly={attach.isPending}
          onChange={(e) => {
            setText(e.target.value)
            if (!attach.isPending) attach.reset()
          }}
          placeholder="Une preuve par ligne, par exemple commit:a1b2c3d"
          aria-label="Joindre une preuve"
        />
        <div className="flex items-center justify-end gap-3">
          {tooLong && <p className="text-xs text-danger">Une preuve ne dépasse pas {EVIDENCE_MAX} caractères.</p>}
          <Button type="submit" disabled={refs.length === 0 || tooLong || attach.isPending}>
            Joindre
          </Button>
        </div>
        {attach.isError && (
          <p role="alert" className="text-xs text-danger">
            {attach.error instanceof ApiError ? attach.error.message : 'Le serveur Nexus ne répond pas.'}
          </p>
        )}
      </form>
    </Section>
  )
}
