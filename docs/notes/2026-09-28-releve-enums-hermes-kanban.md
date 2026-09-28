# Relevé — enums réels de Hermes Kanban

**Date :** 2026-09-28
**Auteur :** Claude (lecture seule)
**Livrable :** ROADMAP Phase 0 — « relevé lecture seule des enums/statuts réels de `kanban_db.py` »

---

## Source lue

- Fichier : `C:\Users\Orion\AppData\Local\hermes\hermes-agent\hermes_cli\kanban_db.py`
- Binaire actif : `C:\Users\Orion\AppData\Local\hermes\bin\hermes.exe`
- **Réserve (`unknown`) :** le `pyproject.toml` de ce dossier indique `version = "0.0.0"` et `hermes --version` a échoué ; la doc mentionne la v0.21.4. Deux autres copies de `kanban_db.py` existent sous `installs/…/environments/…/workspace/`. Il n'est **pas vérifié** que le fichier lu correspond au code exécuté. À reconfirmer au début de la Phase 1 (lecture de `kanban.db` réel : `SELECT DISTINCT status FROM tasks`, `SELECT DISTINCT outcome FROM task_runs`, `SELECT DISTINCT kind FROM task_events`).

## Statuts de tâche

`VALID_STATUSES` (l. 103) :

```text
triage · todo · scheduled · ready · running · blocked · review · done · archived
```

- Statuts initiaux autorisés à la création directe (`VALID_INITIAL_STATUSES`, l. 104) : `running`, `blocked`.

## Types de blocage

`VALID_BLOCK_KINDS` (l. 107) : `dependency` · `needs_input` · `capability` · `transient` (ou `None` = blocage historique non typé).

- `BLOCK_RECURRENCE_LIMIT = 2` : après 2 cycles block → unblock → re-block pour la même raison, la tâche est routée vers `triage`.

## Résultats de run (`task_runs.outcome`)

Valeurs écrites dans le code : `completed` · `review_requested` · `changes_requested` · `blocked` · `dependency_wait` · `reclaimed` · `scheduled`.

Le dispatcher compte aussi (champs de tick, l. 232–233) : `spawned`, `crashed`, `stale`, `timed_out`, `auto_blocked`, `rate_limited`, `reclaimed`, `promoted`… Leur écriture exacte dans `task_runs.outcome` n'est pas relevée ici (à confirmer sur la base réelle).

## Types d'événements natifs (`task_events.kind`, non exhaustif)

`assigned` · `claimed` · `claim_rejected` · `claim_extended` · `dependency_wait` · `promoted` · `promoted_manual` · `reclaimed` · `completed` · `completion_blocked_hallucination` · `completion_blocked_empty_result` · `suspected_hallucinated_references` · `blocked` · `unblocked` · `review_requested` · `review_reopened` · `commented` · `attached` · `attachment_removed` · `edited` · `reprioritized` · `specified` · `scheduled` · `archived` · `archive_worker_termination` · `unlinked` · `descendant_invalidated` · `status`

## Conclusion tirée de ce relevé

La lecture du code et de la doc (`website/docs/user-guide/features/kanban.md`) montre que Hermes Kanban est une file de travail **pour agents** : une tâche assignée et `ready` est lancée par le dispatcher, `triage` passe par un décomposeur LLM, `review` lance un relecteur. Les tâches de Loïc ne peuvent donc pas y vivre sans violer ADR-003 → **ADR-011** : Nexus a ses propres tâches et statuts ; Hermes devient un exécutant (ADR-013).

## Usage de ce relevé

Ces valeurs servent à l'**adaptateur `hermes`** (Phase 2) :

- les statuts Hermes sont stockés dans `Run.native_status`, jamais comme statuts de tâche Nexus ;
- correspondance proposée vers `Run.status` : `triage`/`todo`/`scheduled`/`ready` → `dispatched` ; `running` → `running` ; `blocked` → `blocked` ; `review` → `review` ; `done` → `done` ; `archived` → `cancelled` ; outcome `crashed`/`timed_out` sans reprise → `failed` ;
- traduction d'événements : `claimed` → `claimed`, `blocked` → `blocked`, `review_requested` → `review`, `completed` → `done` (preuves reprises du `metadata`).
