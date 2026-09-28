# ROADMAP — Nexus

**Version :** 0.2 (refonte : application autonome — ADR-011)
**Date :** 2026-09-28

---

## Règles de progression

1. **Go explicite de Loïc** à la fin de chaque phase — rien n'avance par inertie.
2. **Chaque phase est utilisable seule** : elle apporte quelque chose qui sert au quotidien, même si la suivante n'arrive jamais.
3. **Une seule opération principale** à la fois ; les tâches auxiliaires sont marquées.
4. **Chaque phase se termine par une preuve** (fichier, log, capture, test), pas une déclaration.
5. **Réversibilité** : sauvegarde avant mutation ; plan de retour explicite.
6. **Aucun secret** ne circule ou ne se stocke, à aucune phase.

---

## Phase 0 — Fondations (en cours)

**Objectif :** le socle documentaire et les décisions structurantes.

**Livrables :**

- [x] Dépôt `F:/Projet/Nexus` + documentation (README, PRD, architecture, modèle, protocole, vues, intégrations, sécurité, roadmap, glossaire, inspirations, décisions) ;
- [x] Relevé lecture seule des enums/statuts réels de Hermes Kanban ([note](notes/2026-09-28-releve-enums-hermes-kanban.md)) ;
- [x] Stack tranchée : FastAPI + SQLite + UI web (ADR-014) ;
- [x] Refonte : Nexus application autonome, tâches dans `nexus.db` (ADR-011 à ADR-016) ;
- [ ] Relecture et validation de la refonte par Loïc ;
- [ ] Choix du framework front.

**Critère de sortie :** docs refondues validées ; framework front choisi.

## Phase 1 — Noyau

**Objectif :** Nexus existe et sert tous les jours, sans aucun LLM.

**Livrables :**

- Serveur FastAPI + `nexus.db` + sauvegarde de la base ;
- Tableau de tâches (vue **Travail**) : créer, déplacer, commenter, assigner, lier ;
- Vue **Maintenant** ;
- API locale d'événements (`POST /api/events`, read-back) ;
- Politiques : une op principale, preuve ou review, scan de secrets ;
- États des nœuds (lecture seule).

**Critère de sortie :** Loïc gère ses tâches dans Nexus au quotidien ; un agent lancé à la main déclare `claimed` → `done` + preuve via l'API ; « retrouver l'état d'une tâche < 30 s ».

## Phase 2 — Exécution

**Objectif :** confier du travail aux agents depuis Nexus et le suivre.

**Livrables :**

- « Confier à » sur une carte ;
- Adaptateurs `hermes` (Helios, Mnēma, Aether), `claude-code`, `codex`, `orca` ;
- Suivi des runs (événements traduits, preuves rapatriées) ;
- Historique par carte : événements + runs + preuves.

**Critère de sortie :** une tâche confiée à Helios (via Hermes) et une à Codex racontent leur histoire complète dans Nexus, vérifiable de bout en bout, sans copie manuelle.

## Phase 3 — Conversations

**Objectif :** voir et mener les discussions dans Nexus.

**Livrables :**

- Vue **Conversations** : lecture des chats Telegram, sessions Hermes, Claude Code, Codex ;
- Recherche dans les chats ;
- Canal d'envoi tranché, puis discussion avec les agents depuis Nexus ;
- Créer une tâche depuis un message.

**Critère de sortie :** Loïc n'ouvre plus Telegram pour suivre ou relancer ses agents.

## Phase 4 — Inbox et planning

**Objectif :** mails et agenda traités dans Nexus.

**Livrables :**

- Vue **Inbox** : mails à traiter, questions et validations ; brouillons (envoi gated) ;
- Vue **Planning** : échéances, calendrier, cron ;
- Accès Gmail cadré (scope validé).

**Critère de sortie :** une semaine de mails et d'agenda traitée depuis Nexus.

## Phase 5 — Code et système

**Objectif :** le reste de l'écosystème visible dans Nexus.

**Livrables :**

- Vue **Code** : repos, branches, worktrees, PR, checks, diffs ;
- Vue **Système** : mémoire Mnēma/Hindsight, services Synapse, nœuds, quotas, exécutants.

**Critère de sortie :** Loïc n'ouvre plus les dashboards Mnēma et Synapse pour le suivi courant.

## Phase 6 — Anti-oubli et consolidation

**Objectif :** Nexus protège activement du risque d'oubli.

**Livrables :**

- Vue **À ne pas oublier** : 12 détections (VIEWS §8) sur données réelles ;
- Rapports périodiques et alertes Telegram (bruit réduit à zéro) ;
- Artémis : état et productions (quand rallumé), sans serveur permanent ;
- Revue d'hygiène : secrets, données périmées, dérives de sources.

**Critère de sortie :** sur 2 semaines, tout oubli significatif a été détecté par une règle nommée avant d'avoir un impact — avec comptage des faux positifs. Revue périodique passant par Nexus uniquement ; les 300 onglets ne reviennent pas.

---

## Prochaine action immédiate

**Phase 0 :** relecture de la refonte par Loïc, choix du framework front, puis go Phase 1.

---

## Risques de calendrier

- Le périmètre est large : chaque phase doit rester utilisable seule pour éviter l'effet tunnel.
- Les phases 2 et 6 dépendent de la disponibilité des nœuds (Artémis éteint).
- Aucun engagement de date : les critères de sortie commandent, pas le calendrier.
