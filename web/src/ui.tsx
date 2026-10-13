import * as RadixDialog from '@radix-ui/react-dialog'
import clsx from 'clsx'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { useAuth } from '@/auth'
import type { Actor } from '@/api'
import { actorName } from '@/tasks/vocabulary'

const controlClass =
  'rounded-sm border border-line-strong bg-sunken text-ink ' +
  'placeholder:text-muted focus-visible:outline-2 focus-visible:outline-accent'

export const inputClass = `${controlClass} w-full min-w-0 px-2.5 py-1.5 text-sm`

/** Contrôle compact d'une barre d'outils (filtres). */
export const toolbarControlClass = `${controlClass} px-2 py-1 text-xs`

export function Button({
  variant = 'secondary',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' }) {
  return (
    <button
      type="button"
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-sm px-3 py-1.5 text-sm font-medium',
        'transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-50',
        variant === 'primary' && 'bg-accent text-on-accent hover:bg-accent/90',
        variant === 'secondary' && 'border border-line-strong bg-surface text-ink hover:bg-ink/10',
        variant === 'ghost' && 'text-muted hover:bg-ink/10 hover:text-ink',
        className,
      )}
      {...props}
    />
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="grid min-w-0 gap-1">
      <span className="font-orbital-display text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</span>
      {children}
      {hint && <span className="text-2xs text-muted">{hint}</span>}
    </label>
  )
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: ReactNode
}) {
  // The portal sits outside the inert app: a dialog left open would capture clicks and typing meant for the lock screen. The callers' drafts live above this component, so they survive the close.
  const { locked } = useAuth()
  return (
    <RadixDialog.Root open={open && !locked} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 bg-black/70 data-[state=open]:animate-[fade-in_120ms_ease-out]" />
        <RadixDialog.Content
          // Portail hors de l'élément `orbital` : la classe doit être portée ici (voir index.css).
          className={clsx(
            'orbital font-orbital fixed top-1/2 left-1/2 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2',
            'max-h-[calc(100vh-2rem)] overflow-y-auto rounded-sm border border-line-strong bg-surface p-5 shadow-2xl shadow-black/60',
            'data-[state=open]:animate-[dialog-in_160ms_cubic-bezier(0.2,0.8,0.2,1)]',
          )}
        >
          <RadixDialog.Title className="font-orbital-display text-lg font-semibold tracking-[0.04em]">{title}</RadixDialog.Title>
          {description ? (
            <RadixDialog.Description className="mt-1 text-xs text-muted">
              {description}
            </RadixDialog.Description>
          ) : (
            <RadixDialog.Description className="sr-only">{title}</RadixDialog.Description>
          )}
          <div className="mt-4">{children}</div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}

/** Marque d'identité d'un acteur : initiale sur sa couleur, nom complet au survol. */
export function AgentMark({ actor, withName = false }: { actor: Actor; withName?: boolean }) {
  const color = `var(--agent-${actor})`
  const name = actorName(actor)
  return (
    <span className="inline-flex max-w-full min-w-0 items-center gap-1.5" title={name}>
      <span
        aria-hidden
        className="grid size-5 shrink-0 place-items-center rounded-full border text-2xs font-semibold"
        style={{ color, borderColor: color }}
      >
        {name[0]}
      </span>
      {withName ? (
        <span className="truncate text-xs">{name}</span>
      ) : (
        <span className="sr-only">{name}</span>
      )}
    </span>
  )
}
