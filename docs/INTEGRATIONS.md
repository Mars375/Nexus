# INTEGRATIONS — Nexus

**Version :** 0.1 (draft à valider)
**Date :** 2026-09-28

---

## Principe

> **Agréger sans dupliquer.** Chaque source reste propriétaire de ses données ; Nexus lit, corrèle, référence. Les écritures passent par les surfaces natives, avec gating et read-back.

---

## 1. Hermes Kanban — le moteur des tâches (P0/MVP)

**Vérifié le 2026-09-27 (audit lecture seule) :**

- SQLite multi-boards, machine d'états complète : `création → triage/todo/ready/blocked → claim atomique → running + task_run → complete/review/block/crash/timeout`, avec heartbeat, fences de propriété, reclaim, retry.
- Tables : `tasks`, `task_runs`, `task_events`, `task_comments`, `task_links`, `task_attachments`, `kanban_notify_subs`.
- Dispatcher : toutes les 60 s ; `failure_limit=2` ; stale timeout 14 400 s ; review automatique ; auto-décomposition ≤ 3/tick ; `max_in_progress` non configuré ; board `default` vide (état initial sain).
- Surfaces d'intégration : CLI `hermes kanban …`, outils agent (Kanban tools), API dashboard + WebSocket `/api/plugins/kanban/events?since=<event_id>&board=<slug>`.

**Nexus :**

- MVP : lecture (tâches, runs, events, comments) → vues Maintenant/Travail. Lecture première via CLI/DB **en lecture seule**.
- v1 : écritures via les outils natifs (events/comments/transitions), read-back obligatoire.
- Le mapping exact des enums de statut sera relevé en Phase 0 (lecture seule de `kanban_db.py`) — aucune valeur devinée.

## 2. Hermes Cron — le planificateur (v1)

- Sources : `cron/jobs.json`, `cron/executions.db` ; diagnostic `hermes cron doctor`.
- Nexus affiche : jobs actifs, dernier/prochain run, échecs, états `unknown` (jamais de « OK » inventé).
- Contexte connu : des échecs 429 transitoires existent côté Cortex (quota Go) ; le retry/fallback est géré par les nœuds, Nexus **observe**.
- Rappel : le comportement mémoire des jobs cron est version-dépendant — à revérifier au moment de l'intégration.

## 3. Sessions & délégaions (v1 → v2)

- `state.db` (sessions/messages) pour les traces Hermes ; dossiers de délégation (`cache/delegation/live/…`).
- Claude Code : sessions locales (`~/.claude`) ; Codex : `~/.codex` ; Orca : worktrees/devcontainers.
- Délégation standard actuelle : `codex exec -p <profil>` (ex. brief non interactif) — à aligner avec le protocole d'événements.
- Nexus relie `run ↔ session ↔ artefacts` ; **DONE ≠ preuve** : la preuve est relue, pas supposée.

## 4. Git / GitHub (v1)

- Repos locaux (`F:/Projet/…`), commits, branches, worktrees ; `gh` CLI pour les PR/issues si besoin.
- Rôle : preuves de code (commit/hash), état des chantiers, liens depuis les cartes.

## 5. Mail (v1, règles à définir)

- Les triages mail existent déjà côté Helios (jobs quotidiens) ; Nexus s'y **réfère** au lieu de recréer un client mail.
- Objectif : surface « mails à traiter » (nécessite réponse / échéance) dans Maintenant + À ne pas oublier.
- Contraintes : lecture seule par défaut ; **aucun envoi sans validation** ; ne jamais stocker de contenu sensible au-delà du nécessaire.
- Note scopes : le token Google vérifié (gog) couvre `calendar` et `drive.file` — **pas Gmail**. Le périmètre mail passe par d'autres voies (jobs dédiés) ; à cadrer en Phase 0.

## 6. Calendrier (v1)

- Scopes existants : `calendar` (lecture vérifiée, 7 calendriers visibles). Rôle : échéances, événements, conflits.

## 7. Quotas & budgets (v1)

- OpenCode Go : fenêtres de limite (HTTP 429) observées ; état à afficher avec fraîcheur.
- Contenus : crédits de génération (Higgsfield) ; solde et coûts par épisode.
- Autres pools : via le registre de credentials (présence seulement — jamais de valeur affichée).
- Politique : zéro paiement par défaut ; toute bascule payante = décision explicite.

## 8. Mnēma / Hindsight — la mémoire (v1, référence)

- Bank active : `helios` (Helios) ; autres banks selon nœud (`mnema`, etc.).
- Nexus **référence** (liens contextuels vers souvenirs/rapports) ; il ne duplique pas le contenu mémoire.
- Les rapports Mnēma restent dans leurs surfaces ; Nexus pointe dessus.

## 9. Synapse / Aether — l'architecture (v1, référence)

- Dashboard existant → référence contextuelle uniquement.
- État du nœud : lecture (Tailscale/SSH read-only) ; jamais de mutation croisée sans le gardien du nœud.

## 10. Artémis — l'usine de contenu (v2, éteint volontairement)

- État `offline-by-design` : jamais « en panne », affiché tel quel.
- Contrat à préparer (quand rallumé) : tâches de production + artefacts (épisodes, rapports de coûts) publiés au format Nexus.
- Rappel : aucun serveur permanent ne doit rester actif de ce côté sans décision.

## 11. Exécutants : Claude / Codex / Orca / Hermes (v2)

- Claude Code, Codex CLI et Orca sont des **exécutants** derrière des contrats communs, sans confusion d'identité.
- Chacun peut, à terme : recevoir une tâche, publier `claimed/working/progress/blocked/handoff/done`, livrer des preuves.
- Deux vitesses : (a) agents Hermes natifs (Helios/Mnēma/Aether) qui utilisent déjà les outils Kanban ; (b) CLI externes (Claude/Codex/Orca) qui passeront par un adaptateur dédié en v2.

## 12. Matrice de statut

| Intégration | Sens | Phase | État |
|---|---|---|---|
| Hermes Kanban | R (→W) | MVP | audit fait ; pont à construire |
| Hermes Cron | R | v1 | sources connues |
| Sessions | R | v1 | sources connues |
| Git | R | v1 | local |
| Mail | R | v1 | règles à définir |
| Calendrier | R | v1 | scope lecture OK |
| Quotas | R | v1 | mesures à brancher |
| Mnēma / Synapse | Réf | v1 | liens |
| Artémis | R/É | v2 | éteint |
| Claude / Codex / Orca | R/W | v2 | contrats à écrire |
