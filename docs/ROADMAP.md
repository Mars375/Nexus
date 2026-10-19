# ROADMAP — Nexus

**Version :** 0.2 (refonte : application autonome — ADR-011)
**Date :** 2026-09-28
**Mise à jour d'état :** 2026-10-19

---

## Règles de progression

1. **Go explicite de Loïc** à la fin de chaque phase — rien n'avance par inertie.
2. **Chaque phase est utilisable seule** : elle apporte quelque chose qui sert au quotidien, même si la suivante n'arrive jamais.
3. **Une seule opération principale** à la fois ; les tâches auxiliaires sont marquées.
4. **Chaque phase se termine par une preuve** (fichier, log, capture, test), pas une déclaration.
5. **Réversibilité** : sauvegarde avant mutation ; plan de retour explicite.
6. **Aucun secret** ne circule ou ne se stocke, à aucune phase.

---

## Phase 0 — Fondations (terminée le 2026-09-28)

**Objectif :** le socle documentaire et les décisions structurantes.

**Livrables :**

- [x] Dépôt `F:/Projet/Nexus` + documentation (README, PRD, architecture, modèle, protocole, vues, intégrations, sécurité, roadmap, glossaire, inspirations, décisions) ;
- [x] Relevé lecture seule des enums/statuts réels de Hermes Kanban ([note](notes/2026-09-28-releve-enums-hermes-kanban.md)) ;
- [x] Stack tranchée : FastAPI + SQLite + UI web (ADR-014) ;
- [x] Refonte : Nexus application autonome, tâches dans `nexus.db` (ADR-011 à ADR-016) ;
- [x] Framework front : React + TypeScript + Vite ; application Windows via Tauri à terme (ADR-017) ;
- [x] Canaux de messagerie : tous, WhatsApp compris (ADR-018) ;
- [x] Relecture et validation de la refonte par Loïc (2026-09-28 : « tout est relu, on est bon »).

**Critère de sortie :** docs refondues validées par Loïc.

## Phase 1 — Noyau (en cours)

**Objectif :** Nexus existe et sert tous les jours, sans aucun LLM.

**Livrables :**

- Serveur FastAPI + `nexus.db` + sauvegarde de la base ;
- Tableau de tâches (vue **Travail**) : créer, déplacer, commenter, assigner, lier ;
- Vue **Maintenant** ;
- API locale d'événements (`POST /api/events`, read-back) ;
- Politiques : une op principale, preuve ou review, scan de secrets ;
- États des nœuds (lecture seule).

**Critère de sortie :** Loïc gère ses tâches dans Nexus au quotidien ; un agent lancé à la main déclare `claimed` → `done` + preuve via l'API ; « retrouver l'état d'une tâche < 30 s ».

### État au 2026-10-19

Le noyau est déjà utilisé au quotidien ; les dernières fusions dessinent un ensemble cohérent — dernier fusionné : `5bf3db9` (#89, découpage des tests de l'API des événements).

- **Tableau (Travail) :** thème « Salle orbitale » de bout en bout, focus de la première carte, fin du saut à l'ouverture des dialogues, police des toasts, agent principal affiché sur la carte, tâche terminée non modifiable + preuves jointes + tâche « suite » (PR #50, #51, #70, #71).
- **Vue Maintenant :** vue complète (PR #29) puis paysage d'étages/baies de 4 nœuds par étage, rotation, finitions, et trois temps de demandes reçues (modèle → réponses → répondre/valider/refuser depuis Maintenant) (PR #33, #35, #37, #52, #53, #54).
- **Temps réel (WebSocket) :** rafales, premier hello, validation par type, journal des requêtes sans valeur reçue, identifiant d'instance pour une base restaurée, URL de base de l'API côté front, handoff réel testé + refus 403, ticket avant tout flux, casse de l'en-tête Origin (PR #31, #38, #46, #48, #64, #68, #72, #75).
- **Service / API et sécurité :** durcissement des appels directs (types, longueurs), authentification par jeton d'acteur exigée partout + écran « Nexus verrouillé » + matrice de permissions (ADR-020) (PR #41, #43, #44, #55, #56, #60, #62).
- **Process agents :** conventions de branches/PR/langue, fusion automatique quand les relectures sont OK (sauf une PR touchant une migration, `DECISIONS.md` ou `AGENTS.md` : fusion par Loïc), routage de modèles (sonnet principal, architect/reviewer en Opus) (PR #34, #45, #73).

**Reste pour la sortie de Phase 1 :** #39 (découpage du code : tests de l'API des événements scindés par la PR #89, autres fichiers à suivre) et #86 (suivi des P3 de #74) ; #15, #17, #57, #58 et #59 sont faits (PR #80, #85, #74, #88 et #76) ; #47 (Tauri) attend le go de Loïc.

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

- Vue **Conversations** : lecture des chats (Telegram, WhatsApp, gateway Hermes, sessions Hermes, Claude Code, Codex) ;
- Recherche dans les chats ;
- Envoi sur tous les canaux (natif, gateway Hermes, Telegram, puis WhatsApp une fois son mode d'accès tranché) ;
- Contact de tiers (ex. prise de rendez-vous), gated ;
- Créer une tâche depuis un message.

**Critère de sortie :** Loïc n'ouvre plus Telegram ni WhatsApp pour suivre ou relancer ses agents ; un rendez-vous réel pris depuis Nexus.

## Jalon transversal — Application Windows

**Quand :** dès que le noyau (Phase 1) est stable, au moment choisi par Loïc ; ne bloque aucune phase.

**Livrables :** Tauri 2 encapsulant l'UI existante ; serveur FastAPI en sidecar ; origine de la WebView autorisée côté serveur (CORS REST + WebSocket, #47) ; icône de barre des tâches, notifications Windows, démarrage automatique ; installeur.

**Critère de sortie :** Nexus s'ouvre comme une application Windows, sans navigateur, avec les mêmes vues.

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

**Phase 1 :** boucler les issues restantes — #39 (premier morceau fusionné en #89) et #86 ; #47 (Tauri) attend le go de Loïc. Les PR ouvertes se fusionnent quand leurs relectures sont complètes (rappel : une PR touchant une migration, `DECISIONS.md` ou `AGENTS.md` se fusionne par Loïc).

---

## Risques de calendrier

- Le périmètre est large : chaque phase doit rester utilisable seule pour éviter l'effet tunnel.
- Les phases 2 et 6 dépendent de la disponibilité des nœuds (Artémis éteint).
- Aucun engagement de date : les critères de sortie commandent, pas le calendrier.
