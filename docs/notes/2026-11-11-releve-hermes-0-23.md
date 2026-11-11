# Relevé — Hermes Kanban 0.23.0 avant l'adaptateur `hermes`

**Date :** 2026-11-11
**Auteur :** Claude (lecture seule : aide de la CLI et code source ; aucune commande n'a écrit dans Hermes)
**Livrable :** ROADMAP Phase 2, lot F (ADR-023) — mettre à jour le [relevé du 2026-09-28](2026-09-28-releve-enums-hermes-kanban.md) avant d'écrire l'adaptateur.

---

## Version lue

- `hermes --version` : **Hermes Agent v0.23.0 (2026.9.24)**, installé par git dans `C:\Users\Orion\AppData\Local\hermes\hermes-agent` ; la réserve du relevé de septembre (version inconnue) est levée.
- Code lu : `hermes_cli/kanban*.py` (le module `kanban_db.py` est désormais découpé en `kanban_db_*.py`, `kanban_workflow.py`, `kanban_output.py`) et `gateway/kanban_watchers_dispatcher.py`.
- Profils sur cette machine : **Helios** seul (`hermes profile list`). Mnēma et Aether vivent sur d'autres nœuds ; ils ne sont pas joignables par cette CLI locale.

## Tableaux (boards)

- Un seul tableau existe : `default`, vide. Le tableau `nexus` reste à créer (feu vert de Loïc le 2026-11-11) : `hermes kanban boards create nexus --name Nexus`, **sans** `--switch`.
- Chaque tableau a sa base (`<racine>/kanban/boards/<slug>/`), ses espaces de travail et son tour de dispatch : une tâche du tableau `nexus` ne touche jamais `default`.
- **Ne jamais lancer `boards switch` / `use`** : cela change le tableau actif de toutes les commandes de Helios. L'adaptateur passe `--board nexus` à chaque appel.
- Le dispatcher intégré à la passerelle (`gateway`, en marche pour Helios) énumère les tableaux **à chaque tour** : un tableau créé est pris en charge sans redémarrage. Intervalle par défaut : 60 s (`kanban.dispatch_interval_seconds`).
- `kanban.review_dispatch: true` dans la configuration de Helios : une tâche passée en `review` lance un relecteur Hermes.

## Création d'une tâche (`hermes kanban --board nexus create …`)

Options confirmées en 0.23.0 :

- `--assignee <profil>` ; `--idempotency-key <clé>` (une tâche non archivée portant la clé est **renvoyée** au lieu d'être recréée : la clé `nx-run-<n>` rend le dispatch rejouable) ;
- `--body-file -` (corps lu sur l'entrée standard : le brief ne passe ni par la ligne de commande ni par un fichier) ;
- `--max-runtime <durée>` (au-delà, le dispatcher arrête le worker **et remet la tâche en file**) ; `--max-retries N` (disjoncteur : `1` bloque au premier échec, sans nouvel essai) ;
- `--workspace scratch|worktree|dir:<chemin>`, `--branch`, `--model`/`--provider`, `--goal`, `--skill`, `--created-by` ;
- `--json` : la tâche créée, avec notamment `id`, `status`, `assignee`, `created_at`, `result`, `last_failure_error`.
- Sans `--triage` ni `--initial-status`, une tâche assignée est prête et **part au tour suivant du dispatcher** ; `--triage` la ferait passer par le décomposeur LLM : l'adaptateur ne l'utilise pas.

## Lecture d'une tâche

- `hermes kanban --board nexus show <id> --json` renvoie `task` (dont `status`, `result`, `completed_at`, `last_failure_error`), `latest_summary`, `comments`, `events` (`kind`, `payload`, `created_at`, `run_id`) et `runs` (`id`, `profile`, `status`, `outcome`, `summary`, `error`, `metadata`, `worker_pid`, `started_at`, `ended_at`).
- `hermes kanban watch` suit les événements de tous les tableaux par sondage (`--interval`, `--kinds`) ; l'adaptateur peut se contenter de `show --json` à chaque tour du superviseur Nexus, sans connexion persistante.
- Annulation : `hermes kanban --board nexus archive <id>` ; un worker en cours est arrêté (événement `archive_worker_termination`).

## Statuts, issues de run et événements (0.23.0)

- **Statuts de tâche** (`kanban_workflow.py`) : `triage`, `todo`, `scheduled`, `ready`, `running`, `blocked`, `review`, `done`, plus `archived`. Inchangés depuis septembre.
- **Statuts initiaux** autorisés à la création : `running`, `blocked` (inchangé). Types de blocage : `dependency`, `needs_input`, `capability`, `transient` (inchangé).
- **Issues de run (`task_runs.outcome`)** écrites par le code : `completed`, `review_requested`, `changes_requested`, `blocked`, `scheduled`, `reclaimed`, et désormais confirmées : `crashed`, `gave_up`, `spawn_failed`, `stale`, `timed_out`.
- **Événements (`task_events.kind`)** vus dans le code, en plus de la liste de septembre : `spawned`, `gave_up`, `timed_out`, `stale`, `changes_requested`, `linked`, `parents_not_done`, `reclaim_deferred`, `reconciled`, `respawn_guarded`, `skipped_nonspawnable`, `worker_lost`, `worker_registered`, `pr_acceptance`. Une liste qui s'allonge à chaque version : l'adaptateur ignore un type inconnu au lieu d'échouer.
- **Fin de run** : `complete --metadata '<JSON>'` range les faits structurés (ex. `changed_files`, `tests_run`) sur le run qui se ferme ; `--summary` / `--result` donnent le résumé. C'est là que l'adaptateur lit les preuves, **relues et non supposées**.

## Correspondance proposée pour l'adaptateur (à valider par `architect`)

| Hermes | `Run.status` Nexus |
|---|---|
| `triage`, `todo`, `scheduled`, `ready` | `dispatched` |
| `running` | `running` |
| `blocked` | `blocked` |
| `review` | `review` |
| `done` avec run `completed` | `done` (preuves tirées de `metadata`, sinon `review`) |
| `archived` | `cancelled` |
| run `gave_up`, `spawn_failed`, ou disjoncteur ouvert | `failed` |

Points ouverts pour le cadrage de l'adaptateur :

1. `--max-runtime` **remet la tâche en file** au lieu de l'échouer : avec `--max-retries 1`, un dépassement bloque la tâche ; le superviseur Nexus garde de toute façon sa propre durée maximale (ADR-023).
2. `review_dispatch: true` : un `review` côté Hermes lance un relecteur Hermes, pas Loïc. Nexus doit-il laisser cette relecture se faire, ou créer ses tâches de façon à l'éviter ?
3. Un `done` sans `metadata` exploitable finit en `review` côté Nexus (même règle que Codex : DONE ≠ preuve).
4. Les profils Mnēma et Aether : une CLI locale ne les atteint pas. Le premier adaptateur ne vise que Helios ; les autres nœuds demandent un accès distant à cadrer (SSH ou API de leur passerelle).
