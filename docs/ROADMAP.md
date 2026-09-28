# ROADMAP — Nexus

**Version :** 0.1
**Date :** 2026-09-28

---

## Règles de progression

1. **Go explicite de Loïc** à la fin de chaque phase — rien n'avance par inertie.
2. **Une seule opération principale** à la fois ; les tâches auxiliaires sont marquées.
3. **Chaque phase se termine par une preuve** (fichier, log, capture, test), pas une déclaration.
4. **Réversibilité** : sauvegarde avant mutation ; plan de retour explicite.
5. **Aucun secret** ne circule ou ne se stocke, à aucune phase.

---

## Phase 0 — Fondations (en cours)

**Objectif :** le socle documentaire et les décisions structurantes.

**Livrables :**

- [x] Dépôt `F:/Projet/Nexus` + documentation complète (README, PRD, architecture, modèle, protocole, vues, intégrations, sécurité, roadmap, glossaire, inspirations, décisions) ;
- [ ] Validation par Loïc du PRD et du modèle de données ;
- [ ] Arbitrage stack UI/serveur (ARCHITECTURE §7) ;
- [ ] Relevé lecture seule des enums/statuts réels de `kanban_db.py` ;
- [ ] Décision : événements dans surfaces natives Hermes vs `nexus.db`.

**Critère de sortie :** PRD + modèle validés ; stack tranchée ; relevé d'enums fait (preuve : note datée dans le dépôt).

## Phase 1 — Cockpit lecture seule (MVP)

**Objectif :** voir la vérité, sans rien écrire.

**Livrables :**

- Pont lecture Hermes Kanban → modèle Nexus (tâches, runs, events, comments) ;
- Vues **Maintenant** + **Travail** sur données réelles ;
- Provenance + fraîcheur sur chaque donnée ;
- Lien vers les sources (kanban, sessions) ;
- Handle honnête des nœuds injoignables (`unknown`, `offline-by-design`).

**Critère de sortie :** la page Maintenant est utilisable au quotidien avec données réelles vérifiées ; aucun LLM requis ; test utilisateur par Loïc (« retrouver l'état d'une tâche < 30 s »).

## Phase 2 — Les agents parlent (v1)

**Objectif :** le protocole d'événements en conditions réelles.

**Livrables :**

- Publication d'événements (claimed/progress/blocked/handoff/review/done) par les agents sur des tâches réelles ;
- Read-back vérifié ;
- Historique par carte : événements + comments + runs + preuves ;
- Politique « preuve ou review » active.

**Critère de sortie :** un run réel (ex. Helios + un exécutant) raconte son histoire complète, vérifiable de bout en bout, sans intervention de Loïc pour la traçabilité.

## Phase 3 — Anti-oubli, Planning, Ressources, Inbox (v1)

**Objectif :** Nexus commence à **protéger du risque d'oubli**.

**Livrables :**

- Vue **À ne pas oublier** : 12 détections (voir VIEWS §3) sur données réelles ;
- Vue **Planning** : échéances, relances, cron (dernier/prochain run, échecs, `unknown`) ;
- Vue **Ressources** : quotas, sessions, repos, refs Mnēma/Synapse ;
- Inbox : mails à traiter + questions/validations en attente ;
- Rapports périodiques (cadence à fixer).

**Critère de sortie :** sur 2 semaines, tout oubli significatif a été détecté par une règle nommée avant d'avoir un impact — avec comptage des faux positifs.

## Phase 4 — Adaptateurs d'exécution (v2)

**Objectif :** Claude, Codex, Orca au même niveau que les agents natifs.

**Livrables :**

- Contrats d'exécution par outil (recevoir une tâche, publier événements, livrer preuves) ;
- Liaison sessions ↔ runs ↔ commits ↔ preuves ;
- Worktrees Orca : état des variantes et livrables ;
- Artémis : intégration de son état et de ses productions (quand rallumé), sans serveur permanent.

**Critère de sortie :** un chantier de code bout en bout (tâche → exécution externe → preuve → clôture) tracé dans Nexus sans copie manuelle.

## Phase 5 — Consolidation

**Objectif :** rendre le système durablement utile, pas envahissant.

**Livrables :**

- Rapports et alertes affinés (bruit réduit à zéro) ;
- Fusion/reprise robuste après coupures (nœud éteint, source morte) ;
- Revue d'hygiène : secrets, données périmées, dérives de sources ;
- Documentation à jour + journal des décisions tenu.

**Critère de sortie :** revue périodique passant par Nexus uniquement ; les 300 onglets ne reviennent pas.

---

## Prochaine action immédiate

**Phase 0 :** faire valider ce dossier par Loïc (PRD + modèle), puis relever en lecture seule les enums de statut réels de Hermes Kanban et trancher la stack.

---

## Risques de calendrier

- Les phases 2–4 dépendent de la disponibilité des nœuds (Artémis éteint = v2 partielle).
- Aucun engagement de date : les critères de sortie commandent, pas le calendrier.
