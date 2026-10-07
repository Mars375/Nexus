import clsx from 'clsx'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Toaster } from 'sonner'
import { clearToken, onUnlockedElsewhere, useAuth } from './auth'
import { HealthStatus } from './HealthStatus'
import { LockScreen } from './LockScreen'
import { useLiveUpdates } from './liveUpdates'
import { NowView } from './now/NowView'
import { WorkView } from './tasks/WorkView'
import { Button } from './ui'

type View = 'maintenant' | 'travail'

const VIEWS: { id: View; label: string }[] = [
  { id: 'maintenant', label: 'Maintenant' },
  { id: 'travail', label: 'Travail' },
]

function currentView(): View {
  const hash = window.location.hash
  return hash === '#/travail' || hash.startsWith('#/travail/') ? 'travail' : 'maintenant'
}

function openTaskFromHash(): string | null {
  return /^#\/travail\/(nx-task-\d+)$/.exec(window.location.hash)?.[1] ?? null
}

export default function App() {
  const [view, setView] = useState<View>(currentView)
  const [open, setOpen] = useState<string | null>(openTaskFromHash)
  const live = useLiveUpdates() // reste actif sous l'écran verrouillé : la connexion continue après le déverrouillage
  const { locked, hasToken } = useAuth()
  const client = useQueryClient()

  useEffect(() => {
    const onHash = () => { setView(currentView()); setOpen(openTaskFromHash()) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // Another tab stored a token while this one was locked: the views re-read their data.
  useEffect(() => onUnlockedElsewhere(() => { void client.invalidateQueries() }), [client])

  return (
    <>
      {/* The app stays mounted under the lock screen so drafts survive; `inert` blocks focus and clicks, `aria-hidden` hides it from screen readers. */}
      <div inert={locked} aria-hidden={locked || undefined} className="flex h-full flex-col">
        <div className="flex min-h-0 flex-1">
          <nav aria-label="Vues" className="orbital flex w-44 shrink-0 flex-col gap-0.5 border-r border-line bg-surface p-2">
            <p className="px-2.5 pt-1.5 pb-3 font-display text-base font-semibold tracking-tight">Nexus</p>
            {VIEWS.map(({ id, label }) => (
              <a
                key={id}
                href={`#/${id}`}
                aria-current={view === id ? 'page' : undefined}
                className={clsx(
                  'relative rounded-md px-2.5 py-1.5 text-sm transition-colors duration-100',
                  view === id ? 'bg-sunken font-medium text-ink' : 'text-muted hover:bg-sunken hover:text-ink',
                )}
              >
                {view === id && (
                  <span aria-hidden className="absolute inset-y-1.5 left-0 w-[3px] rounded-r bg-accent" />
                )}
                {label}
              </a>
            ))}
            {hasToken && (
              <Button
                variant="ghost"
                className="mt-auto justify-start px-2.5 text-xs"
                onClick={() => { clearToken(); void client.invalidateQueries() }}
              >
                Oublier le jeton
              </Button>
            )}
          </nav>
          <main className="flex min-w-0 flex-1 flex-col">
            {view === 'travail' ? (
              <WorkView openTask={open} />
            ) : (
              <NowView />
            )}
          </main>
        </div>
        <HealthStatus live={live} />
        <Toaster
          position="bottom-center"
          offset={40}
          theme="dark"
          richColors
          closeButton
          // sonner sets its own font stack on the toaster element: override it with the theme font.
          style={{ fontFamily: 'var(--font-orbital)' }}
        />
      </div>
      {locked && <LockScreen />}
    </>
  )
}
