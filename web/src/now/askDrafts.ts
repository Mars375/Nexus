import { useCallback, useState } from 'react'

/** What Loïc has typed or ticked on an ask and not sent yet. */
export type AskDraft = { text: string; note: string; choice: number | null }

export const EMPTY_DRAFT: AskDraft = { text: '', note: '', choice: null }

/** True once the draft holds something worth warning about if the ask changes under it. */
export const hasDraft = (d: AskDraft): boolean => d.text.trim() !== '' || d.note.trim() !== '' || d.choice !== null

/**
 * Drafts by approval reference, kept above the cards: a refetch, a live update or a reordered
 * list never discards what is being typed (review checklist §6). Plain React state: nothing is
 * stored by the browser.
 */
export function useAskDrafts() {
  const [drafts, setDrafts] = useState<Readonly<Record<string, AskDraft>>>({})
  const patch = useCallback((ref: string, change: Partial<AskDraft>) => {
    setDrafts((all) => ({ ...all, [ref]: { ...(all[ref] ?? EMPTY_DRAFT), ...change } }))
  }, [])
  const clear = useCallback((ref: string) => {
    setDrafts((all) => {
      const { [ref]: _gone, ...rest } = all
      return rest
    })
  }, [])
  return { drafts, patch, clear }
}
