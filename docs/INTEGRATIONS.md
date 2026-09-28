# INTEGRATIONS — Nexus

**Version :** 0.2 (refonte : exécutants et sources derrière adaptateurs — ADR-011, ADR-013, ADR-016)
**Date :** 2026-09-28

---

## Principe

> **Nexus est autonome ; les systèmes externes sont branchés derrière des adaptateurs remplaçables.** Nexus possède ses tâches et événements. Les données externes restent chez leur propriétaire : Nexus les lit, les affiche, et agit dessus via l'adaptateur — avec gating et read-back pour toute action sortante.

Deux familles :

- **Exécutants** — à qui Nexus confie du travail (« confier à ») : Hermes, Claude Code, Codex, Orca.
- **Sources** — ce que Nexus lit et sur quoi il agit : chats, mail, agenda, Git, mémoire, infra, nœuds, quotas, cron.

---

## A. Exécutants

### 1. Hermes — agents de nœud (Phase 2)

**Rôle :** exécutant pour Helios, Mnēma et Aether (ADR-013).

**Vérifié le 2026-09-27/28 (lecture seule) :**

- Hermes Kanban est une file de travail **pour agents** : toute tâche assignée à un profil et `ready` est lancée par le dispatcher (60 s) ; `triage` passe par un décomposeur LLM (mode Auto, actif sur Helios) ; `review` lance un relecteur. C'est pourquoi les tâches Nexus n'y vivent pas (ADR-011).
- Machine d'états : claim atomique, heartbeat, reclaim, retry (`failure_limit=2`), stale timeout 14 400 s, circuit breaker.
- Tables : `tasks`, `task_runs`, `task_events`, `task_comments`, `task_links`, `task_attachments`, `kanban_notify_subs`.
- Surfaces : CLI `hermes kanban …`, API dashboard + WebSocket `/api/plugins/kanban/events?since=<event_id>&board=<slug>`.
- Statuts et événements relevés : [notes/2026-09-28-releve-enums-hermes-kanban.md](notes/2026-09-28-releve-enums-hermes-kanban.md).

**Adaptateur `hermes` :**

- `dispatch` : crée une tâche Hermes assignée au profil de l'agent choisi (`hermes kanban create … --assignee <profil> --idempotency-key <nx-run-id>`), sur un board dédié à Nexus (à créer, ex. `nexus`).
- `watch` : suit le run via WS/DB ; traduit `claimed`, `blocked`, `review_requested`, `completed` en événements Nexus ; reprend `metadata` de complétion comme preuves.
- Ne crée jamais de tâche Hermes sans « confier à » explicite.

### 2. Claude Code, Codex, Orca (Phase 2)

- Claude Code : sessions locales (`~/.claude`) ; Codex : `codex exec -p <profil>`, `~/.codex` ; Orca : CLI `orca`, worktrees/devcontainers.
- `dispatch` : lance une session non interactive sur la tâche (brief = objectif + contexte + preuves attendues) ; l'agent publie ses événements via l'API Nexus.
- `watch` : suit le processus/la session ; relie `run ↔ session ↔ artefacts`.
- **DONE ≠ preuve** : la preuve est relue, pas supposée.

## B. Sources

### 3. Chats et messagerie (Phase 3)

**Tous les canaux (ADR-018)**, chacun derrière son adaptateur, avec read-back après envoi :

| Canal | Lecture | Envoi | Usage |
|---|---|---|---|
| Chat natif Nexus | ✓ | ✓ | discussion dans l'app |
| Gateway Hermes | ✓ | ✓ | parler à Helios, Mnēma, Aether (ils y écoutent déjà) |
| Telegram | ✓ (dont le groupe « Hermes collective ») | ✓ | agents, alertes mobiles |
| WhatsApp | ✓ | ✓ (gated vers un tiers) | contacts, prise de rendez-vous |
| Sessions Hermes (`state.db`), Claude Code (`~/.claude`), Codex (`~/.codex`) | ✓ | — | historique des sessions d'agents |

- Les chats restent dans leur système ; Nexus en garde un index daté pour l'affichage et la recherche.
- Tout message vers un **tiers humain** est préparé puis envoyé sur go de Loïc (SECURITY §4).

**WhatsApp — contraintes à trancher avant d'implémenter :**

- **API officielle (WhatsApp Business Cloud API)** : conforme et stable, mais exige un numéro dédié (un numéro passé sur l'API ne s'utilise plus dans l'app WhatsApp), des modèles de message approuvés par Meta pour initier une conversation hors fenêtre de 24 h (cas typique d'une prise de rendez-vous), et un **webhook entrant joignable depuis Internet** pour recevoir les réponses.
- **Bibliothèques non officielles** (pilotage de WhatsApp Web) : utilisent le numéro personnel sans modèles, mais violent les conditions d'utilisation de WhatsApp — risque de bannissement du numéro.
- **Webhook entrant** : contredit le « rien d'exposé » ; option à étudier : tunnel limité à ce seul endpoint (ex. Cloudflare Tunnel), avec vérification de signature.

### 4. Hermes Cron (Phase 4)

- Sources : `cron/jobs.json`, `cron/executions.db` ; diagnostic `hermes cron doctor`.
- Nexus affiche : jobs actifs, dernier/prochain run, échecs, `unknown` (jamais de « OK » inventé).
- Contexte : des échecs 429 transitoires existent côté Cortex (quota Go) ; le retry/fallback est géré par les nœuds, Nexus **observe**.

### 5. Mail (Phase 4, règles à définir)

- Objectif : traiter les mails dans Nexus — lire, trier, préparer une réponse, créer une tâche.
- Les triages mail existent déjà côté Helios (jobs quotidiens) ; leur sortie est une source possible.
- Contraintes : **aucun envoi sans validation** ; minimisation du contenu sensible conservé.
- Scopes : le token Google vérifié (gog) couvre `calendar` et `drive.file` — **pas Gmail**. Accès Gmail à cadrer (nouveau scope = validation explicite, SECURITY §8).

### 6. Calendrier (Phase 4)

- Scope `calendar` (lecture vérifiée, 7 calendriers visibles). Rôle : événements, échéances, conflits. Création/modification gated.

### 7. Git / GitHub (Phase 5)

- Repos locaux (`F:/Projet/…`), commits, branches, worktrees ; `gh` pour PR, checks, diffs.
- Rôle : vue Code, preuves (commit/hash), liens depuis les cartes.

### 8. Mémoire — Mnēma / Hindsight (Phase 5)

- Banks : `helios` (Helios), `mnema`, etc.
- Nexus **affiche** les souvenirs et rapports utiles (ADR-016) ; la mémoire reste dans Hindsight.

### 9. Infrastructure — Synapse / Aether (Phase 5)

- Services, santé, incidents : lus et affichés dans la vue Système.
- Lecture Tailscale/SSH read-only ; jamais de mutation croisée sans le gardien du nœud.

### 10. Nœuds (Phase 1 → 5)

- Helios, Cortex, Synapse, Artémis : santé, dernier contact.
- Artémis : `offline-by-design` — jamais « en panne ». Aucun serveur permanent de ce côté sans décision.

### 11. Quotas & budgets (Phase 5)

- OpenCode Go : fenêtres de limite (HTTP 429) ; crédits Higgsfield ; autres pools via le registre de credentials (présence seulement — jamais de valeur).
- Politique : zéro paiement par défaut ; toute bascule payante = décision explicite.

### 12. Artémis — l'usine de contenu (Phase 6, éteint volontairement)

- Contrat à préparer (quand rallumé) : tâches de production + artefacts (épisodes, rapports de coûts) publiés au format Nexus.

## C. Matrice de statut

| Intégration | Famille | Sens | Phase | État |
|---|---|---|---|---|
| Nœuds | source | R | 1 | à brancher |
| Hermes | exécutant | dispatch + R | 2 | audit fait ; enums relevés |
| Claude / Codex / Orca | exécutant | dispatch + R | 2 | contrats à écrire |
| Chats et messagerie | source | R + envoi (gated vers un tiers) | 3 | tous les canaux (ADR-018) ; accès WhatsApp à trancher |
| Cron | source | R | 4 | sources connues |
| Mail | source | R (+ envoi gated) | 4 | scope Gmail à cadrer |
| Calendrier | source | R (+ écriture gated) | 4 | scope lecture OK |
| Git / GitHub | source | R | 5 | local + `gh` authentifié |
| Mnēma / Hindsight | source | R | 5 | banks connues |
| Synapse | source | R | 5 | à brancher |
| Quotas | source | R | 5 | mesures à brancher |
| Artémis | source/exécutant | R | 6 | éteint |
