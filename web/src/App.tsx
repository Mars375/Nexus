import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { Toaster } from 'sonner'
import { HealthStatus } from './HealthStatus'
import { WorkView } from './tasks/WorkView'

type View = 'maintenant' | 'travail'

const VIEWS: { id: View; label: string }[] = [
  { id: 'maintenant', label: 'Maintenant' },
  { id: 'travail', label: 'Travail' },
]

function currentView(): View {
  return window.location.hash === '#/maintenant' ? 'maintenant' : 'travail'
}

export default function App() {
  const [view, setView] = useState<View>(currentView)

  useEffect(() => {
    const onHash = () => setView(currentView())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1">
        <nav aria-label="Vues" className="flex w-44 shrink-0 flex-col gap-0.5 border-r border-line bg-surface p-2">
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
        </nav>
        <main className="flex min-w-0 flex-1 flex-col">
          {view === 'travail' ? (
            <WorkView />
          ) : (
            <div className="p-5">
              <h1 className="font-display text-lg font-semibold">Maintenant</h1>
              <p className="mt-2 max-w-prose text-sm text-muted">
                Bientôt ici : l'opération principale, les agents actifs, les blocages et ce qui
                t'attend.
              </p>
            </div>
          )}
        </main>
      </div>
      <HealthStatus />
      <Toaster position="bottom-center" offset={40} theme="system" richColors closeButton />
    </div>
  )
}
