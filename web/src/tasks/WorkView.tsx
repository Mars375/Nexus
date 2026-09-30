import { useMemo, useState } from 'react'
import type { Actor, Priority, Role, Status } from '@/api'
import { listProvenance } from '@/freshness'
import { Provenance } from '@/Provenance'
import { useNow } from '@/useNow'
import { Button, toolbarControlClass } from '@/ui'
import { Board } from './Board'
import { CreateTaskDialog } from './CreateTaskDialog'
import { applyFilters, NO_FILTER, type Due, type Filters } from './filters'
import { useTasks } from './queries'
import { TaskPane } from './TaskPane'
import { ACTOR_NAME, ACTORS, BOARD_STATUSES, PRIORITY_LABEL, ROLE_LABEL, STATUS_LABEL } from './vocabulary'

export function WorkView() {
  const tasks = useTasks()
  const now = useNow(60_000)
  const [filters, setFilters] = useState<Filters>(NO_FILTER)
  const [openId, setOpenId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const set = <K extends keyof Filters>(key: K, value: Filters[K]) =>
    setFilters((f) => ({ ...f, [key]: value }))

  const provenance = tasks.data ? listProvenance(tasks.data, 'tasks', tasks.dataUpdatedAt) : null
  const all = useMemo(() => tasks.data ?? [], [tasks.data])
  const visible = useMemo(() => applyFilters(all, filters, now), [all, filters, now])
  const statuses = filters.status
    ? [filters.status]
    : filters.showDropped
      ? [...BOARD_STATUSES, 'dropped' as const]
      : BOARD_STATUSES
  const open = all.find((t) => t.id === openId) ?? null
  const filtered = JSON.stringify(filters) !== JSON.stringify(NO_FILTER)

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-2 px-5 pt-5 pb-4">
          <h1 className="mr-3 font-display text-lg font-semibold">Travail</h1>
          <FilterSelect label="Filtrer par agent" value={filters.agent} onChange={(v) => set('agent', v as Actor | '')}>
            <option value="">Tous les agents</option>
            {ACTORS.map((a) => (
              <option key={a} value={a}>{ACTOR_NAME[a]}</option>
            ))}
          </FilterSelect>
          <FilterSelect label="Filtrer par statut" value={filters.status} onChange={(v) => set('status', v as Status | '')}>
            <option value="">Tous les statuts</option>
            {[...BOARD_STATUSES, 'dropped' as const].map((s) => (
              <option key={s} value={s}>{STATUS_LABEL[s]}</option>
            ))}
          </FilterSelect>
          <FilterSelect label="Filtrer par priorité" value={filters.priority} onChange={(v) => set('priority', v as Priority | '')}>
            <option value="">Toutes priorités</option>
            {(Object.keys(PRIORITY_LABEL) as Priority[]).map((p) => (
              <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>
            ))}
          </FilterSelect>
          <FilterSelect label="Filtrer par rôle" value={filters.role} onChange={(v) => set('role', v as Role | '')}>
            <option value="">Tous les rôles</option>
            {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </FilterSelect>
          <FilterSelect label="Filtrer par échéance" value={filters.due} onChange={(v) => set('due', v as Due)}>
            <option value="">Toutes échéances</option>
            <option value="overdue">En retard</option>
            <option value="week">Dans les 7 jours</option>
          </FilterSelect>
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={filters.showDropped}
              onChange={(e) => set('showDropped', e.target.checked)}
            />
            Abandonnées
          </label>
          {filtered && (
            <Button variant="ghost" onClick={() => setFilters(NO_FILTER)}>
              Effacer les filtres
            </Button>
          )}
          <Button variant="primary" className="ml-auto" onClick={() => setCreating(true)}>
            Nouvelle tâche
          </Button>
        </header>

        {provenance && (
          <p className="px-5 pb-2">
            <Provenance source={provenance.source} measuredAt={provenance.measuredAt} kind="tasks" />
          </p>
        )}

        {tasks.isPending && <p className="px-5 text-sm text-muted">Chargement des tâches…</p>}
        {tasks.isError && !tasks.data && (
          <p className="px-5 text-sm text-danger">
            Impossible de lire les tâches : le serveur Nexus ne répond pas.
          </p>
        )}
        {/* Un rafraîchissement raté garde le tableau connu, signalé comme non à jour (ADR-005). */}
        {tasks.isError && tasks.data && (
          <p role="status" className="px-5 pb-2 text-xs text-attention">
            Tableau non à jour : le dernier rafraîchissement a échoué, nouvel essai dans quelques
            secondes.
          </p>
        )}
        {tasks.data && all.length === 0 && (
          <div className="px-5 py-10 text-sm">
            <p className="font-medium">Aucune tâche pour l'instant.</p>
            <p className="mt-1 text-muted">Crée la première : elle restera ici, sans lancer d'agent.</p>
            <Button variant="primary" className="mt-4" onClick={() => setCreating(true)}>
              Nouvelle tâche
            </Button>
          </div>
        )}
        {tasks.data && all.length > 0 && (
          <Board tasks={visible} allTasks={all} statuses={statuses} onOpen={setOpenId} />
        )}
      </div>

      {/* Clé par tâche : brouillons et commentaires en cours ne passent jamais d'une tâche à l'autre. */}
      {open && <TaskPane key={open.id} task={open} tasks={all} onClose={() => setOpenId(null)} />}
      <CreateTaskDialog open={creating} onOpenChange={setCreating} />
    </div>
  )
}

function FilterSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
}) {
  return (
    <select
      aria-label={label}
      className={`${toolbarControlClass} ${value ? 'border-ink/50 font-medium' : ''}`}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {children}
    </select>
  )
}
