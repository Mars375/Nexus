# PRD — Nexus

**Version :** 0.1 (draft à valider)
**Date :** 2026-09-28
**Auteur :** Helios (coordination)
**Statut :** proposition — attend le go de Loïc

---

## 1. Contexte

Loïc pilote un écosystème multi-nœuds (« Nexus ») composé de machines et d'agents :

- **Helios** — poste Windows, desktop/browser/projets/coordination locale ;
- **Mnēma (Cortex)** — mémoire, diagnostic, supervision ;
- **Aether (Synapse)** — homelab, architecture, services ;
- **Artémis** — usine de contenu (actuellement éteinte volontairement) ;
- **Exécutants** — Claude Code, Codex CLI, Orca, Hermes lui-même.

Le travail quotidien est fragmenté : conversations Telegram, sessions de code, cron jobs, mails, kanban Hermes, mémoire Hindsight, dashboards. Les états importants sont dispersés et parfois invisibles — y compris pour les agents entre eux.

## 2. Problème

1. **Oubli** — des tâches sont promesses ou décisions, et se perdent entre deux conversations.
2. **Opacité croisée** — un agent ne sait pas ce que font les autres ; Loïc ne sait pas qui travaille sur quoi.
3. **Dispersion** — « 300 onglets » : chaque outil a sa surface, aucune vue ne corrèle.
4. **Preuves absentes** — « terminé » est souvent déclaré sans artefact vérifiable.
5. **Silences** — blocages et attentes ne remontent pas ; personne ne relance.

## 3. Vision

> **Nexus est le centre de coordination et de mémoire opérationnelle partagé entre Loïc et ses agents.**

Il répond à tout moment à :

```text
Sur quoi travaillons-nous ?
Qui travaille sur quoi, maintenant ?
Qu'est-ce qui attend Loïc ?
Qu'est-ce qui est bloqué, et pourquoi ?
Qu'est-ce qui a réellement été terminé — avec quelle preuve ?
Qu'est-ce qui a été promis, et à qui ?
Qu'est-ce qui risque d'être oublié ?
```

## 4. Acteurs

| Acteur | Rôle dans Nexus |
|---|---|
| **Loïc** | Propriétaire, valideur final, destinataire des alertes |
| **Helios** | Coordinateur système ; un des exécutants |
| **Mnēma** | Référence mémoire/diagnostic ; synthèse et registre |
| **Aether** | Référence architecture/services ; gardien nœud Synapse |
| **Artémis** | Usine de contenu ; composant inclus, éteint volontairement |
| **Claude / Codex / Orca** | Exécutants de code (sessions, worktrees, PR) |
| **Hermes** | Moteur d'exécution durable (Kanban, Cron, délégation) |

## 5. Jobs-to-be-done

- **JTBD-1** — Quand une tâche naît dans une conversation, je veux qu'elle soit tracée au même endroit pour ne plus me reposer sur ma mémoire.
- **JTBD-2** — Quand un agent prend une tâche, je veux le voir (qui, quoi, quand) sans lui demander.
- **JTBD-3** — Quand quelque chose est bloqué, je veux le savoir avec la cause et la relance prévue — pas le découvrir par hasard.
- **JTBD-4** — Quand un agent déclare « terminé », je veux voir la preuve (commit, fichier, log, capture).
- **JTBD-5** — Quand j'ouvre mon poste le matin, je veux UNE page qui montre l'état réel de tout : tâches, jobs, mails à traiter, quotas, agents actifs.
- **JTBD-6** — Quand je dois décider, je veux que la décision et sa conséquence soient visibles pour tous les agents concernés.
- **JTBD-7** — Quand Artémis tourne (ou pas), je veux voir son état et ses productions sans deviner.

## 6. Principes produit (non négociables)

1. Une carte Kanban n'est **pas** un appel LLM : créer/déplacer/commenter ne déclenche aucun agent.
2. Les sources de vérité restent leurs propriétaires (Hermes = tâches exécutables ; Cron = jobs ; etc.). Nexus corrèle, n'absorbe pas.
3. Chaque donnée affichée porte **provenance + fraîcheur**.
4. `unknown` reste `unknown` jusqu'à vérification. Aucune valeur inventée, jamais.
5. **Une seule opération principale** active à la fois ; les tâches auxiliaires sont marquées comme telles.
6. **Aucun secret** conservé : `[REDACTED]`, contrôles de présence uniquement.
7. Local-first, observabilité complète, aucun fournisseur unique requis.
8. Artémis est un composant du modèle, même éteint.

## 7. Périmètre

### 7.1 MVP (Phase 1 — lecture seule)

- Pont lecture vers **Hermes Kanban** (tâches, runs, événements, comments) ;
- Vues **Maintenant** et **Travail** sur données réelles ;
- Provenance/fraîcheur partout ;
- Zéro écriture, zéro LLM, zéro mise en danger des systèmes existants.

### 7.2 v1 (Phases 2–3)

- Écritures d'agents via le protocole d'événements (claimed, progress, blocked, handoff, done…) ;
- Vue **À ne pas oublier** (détecteur d'oublis) ;
- Vues **Planning** et **Ressources** (cron, quotas, sessions, Git) ;
- Inbox : mails à traiter, questions en attente de Loïc, validations.

### 7.3 Plus tard (Phases 4–5)

- Adaptateurs complets Claude / Codex / Orca (sessions et preuves automatisées) ;
- Artémis branché quand rallumé (tâches + artefacts de l'usine) ;
- Rapports périodiques, corrélations avancées, alertes proactives.

### 7.4 Hors périmètre

- Remplacer Hermes, Synapse ou Mnēma ; dupliquer leurs dashboards ;
- Lancer des agents automatiquement depuis le Kanban ;
- Stocker des secrets, tokens ou credentials ;
- Interface mobile native (Telegram reste la surface mobile) ;
- Exposer publiquement sur Internet.

## 8. Exigences fonctionnelles

| ID | Exigence | Phase |
|---|---|---|
| FR-1 | Lire Hermes Kanban en lecture seule (tâches, statuts, runs, événements, comments) | MVP |
| FR-2 | Afficher les cartes enrichies : objectif, propriétaire humain, agent principal, collaborateurs, prochaine action, échéance, blocages, dépendances, preuves attendues | MVP |
| FR-3 | Vue **Maintenant** : agents actifs, tâches en cours, blocages, attentes Loïc | MVP |
| FR-4 | Vue **Travail** : tableaux par board, filtres (agent, statut, échéance) | MVP |
| FR-5 | Provenance + fraîcheur sur chaque donnée (source, id, âge) | MVP |
| FR-6 | Protocole d'événements d'agents (voir EVENT-PROTOCOL.md) avec read-back vérifié | v1 |
| FR-7 | Vue **À ne pas oublier** avec règles de détection explicites (voir VIEWS.md) | v1 |
| FR-8 | Vue **Planning** : échéances, relances, cron (dernier/prochain run), échecs | v1 |
| FR-9 | Vue **Ressources** : quotas/budgets, sessions actives, repos/branches, refs Synapse/Mnēma | v1 |
| FR-10 | Inbox : mails à traiter, questions d'agents, validations en attente | v1 |
| FR-11 | Preuves : lier commit/fichier/log/capture à une tâche ; signaler « done sans preuve » | v1 |
| FR-12 | Recherche globale + filtres, avec retour à la source d'origine (lien) | v1 |
| FR-13 | Politique « une seule opération principale » appliquée et affichée | v1 |
| FR-14 | Adaptateurs d'exécution (Claude/Codex/Orca : sessions, worktrees, artefacts) | v2 |
| FR-15 | Intégration Artémis (état + productions) quand le nœud est allumé | v2 |

## 9. Exigences non fonctionnelles

- **NFR-1 — Zéro coût par défaut** : l'usage de base (consulter, déplacer, commenter) ne consomme aucun appel LLM.
- **NFR-2 — Local-first** : les données restent sur les machines de Loïc ; aucune sortie réseau non explicite.
- **NFR-3 — Observabilité** : chaque état est inspectable (source, fraîcheur, id, dernière vérification).
- **NFR-4 — Sécurité** : secrets jamais stockés ; gating des actions irréversibles (voir SECURITY.md).
- **NFR-5 — Réversibilité** : toute mutation est précédée d'une sauvegarde et d'un plan de retour.
- **NFR-6 — Extensibilité** : adaptateurs indépendants par source ; aucun fournisseur unique critique.
- **NFR-7 — Légèreté** : la vue Maintenant se charge en < 2 s sur le poste de Loïc.
- **NFR-8 — Résilience** : un nœud éteint (Artémis) produit des états `unknown` clairs, pas des erreurs bloquantes.

## 10. Politiques transverses

- **Une seule opération principale** — par défaut, une tâche « en cours » principale par humain ; les autres sont auxiliaires, marquées comme telles.
- **`unknown` assume** — tout état non vérifiable s'affiche `unknown` avec sa dernière tentative de contrôle.
- **Preuve d'abord** — une tâche importante se clôt avec preuve ; sinon elle va en `review`.
- **Silence autorisé** — un agent sans rien de nouveau ne publie rien (pas de bruit).
- **Frontière par nœud** — chaque nœud applique ses changements par son gardien local.

## 11. Métriques de succès

| Métrique | Cible | Mesure |
|---|---|---|
| Oublis | 0 promesse non tracée > 7 jours sans alerte | Rapport hebdo « À ne pas oublier » |
| Adoption | La page Maintenant est consultée quotidiennement | Logs d'accès locaux |
| Transparence | ≥ 80 % des runs d'agents déclarent `claimed` puis `done` + preuve | Événements |
| Hygiène | 0 secret en base (audit) ; 0 état affiché sans provenance | Audit SECURITY |
| Rapidité | Retrouver l'état d'une tâche < 30 s | Test utilisateur |

## 12. Risques & mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| Complexité qui retombe en « dashboard de plus » | Élevé | MVP strict lecture seule ; chaque vue répond à une question nommée |
| Double source de vérité | Élevé | Règle : on agrège, on ne duplique pas ; liens vers l'origine |
| Dérive en automatisation dangereuse | Élevé | Gating explicite ; rien d'irréversible sans go humain |
| Données périmées présentées comme fraîches | Moyen | Fraîcheur affichée systématiquement ; staleness visible |
| Dépendance à un outil temporaire | Moyen | Adaptateurs remplaçables ; doc des contrats |

## 13. Questions ouvertes

1. Stack exacte du serveur/UI local (à trancher en Phase 0 — voir ARCHITECTURE §7).
2. Emplacement des événements de coordination : Hermes natif vs base Nexus (voir DATA-MODEL §6).
3. Périmètre mail : quelles boîtes, quelles règles de confidentialité (le token Google actuel couvre `calendar` et `drive.file`, pas Gmail — voir INTEGRATIONS §5).
4. Cadence des rapports (quotidien ? hebdo ? les deux ?).
5. Critères exacts pour qu'une tâche « attend Loïc » (relance auto vs attente passive).

## 14. Annexes

- [ARCHITECTURE.md](ARCHITECTURE.md) — architecture technique
- [DATA-MODEL.md](DATA-MODEL.md) — entités et règles
- [EVENT-PROTOCOL.md](EVENT-PROTOCOL.md) — protocole d'événements
- [VIEWS.md](VIEWS.md) — spécification des vues
- [INTEGRATIONS.md](INTEGRATIONS.md) — sources et adaptateurs
- [ROADMAP.md](ROADMAP.md) — phasage et critères de sortie
- [SECURITY.md](SECURITY.md) — sécurité et permissions
