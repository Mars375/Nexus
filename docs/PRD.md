# PRD — Nexus

**Version :** 0.2 (refonte : application autonome — ADR-011)
**Date :** 2026-09-28
**Auteur :** Helios (v0.1), refonte Claude avec Loïc (v0.2)
**Statut :** direction validée par Loïc ; texte à relire

---

## 1. Contexte

Loïc pilote un écosystème multi-nœuds (« le Nexus ») composé de machines et d'agents :

- **Helios** — poste Windows, desktop/browser/projets/coordination locale ;
- **Mnēma (Cortex)** — mémoire, diagnostic, supervision ;
- **Aether (Synapse)** — homelab, architecture, services ;
- **Artémis** — usine de contenu (actuellement éteinte volontairement) ;
- **Exécutants** — Claude Code, Codex CLI, Orca, et Hermes (moteur sur lequel tournent Helios, Mnēma et Aether).

Le travail quotidien est fragmenté : conversations Telegram, sessions de code, cron jobs, mails, agenda, dashboards Mnēma et Synapse, mémoire Hindsight. Les états importants sont dispersés et parfois invisibles — y compris pour les agents entre eux.

## 2. Problème

1. **Oubli** — des tâches, promesses ou décisions se perdent entre deux conversations.
2. **Opacité croisée** — un agent ne sait pas ce que font les autres ; Loïc ne sait pas qui travaille sur quoi.
3. **Dispersion** — « 300 onglets » : chaque outil a sa surface, aucune ne corrèle.
4. **Preuves absentes** — « terminé » est souvent déclaré sans artefact vérifiable.
5. **Silences** — blocages et attentes ne remontent pas ; personne ne relance.

## 3. Vision

> **Nexus est le centre de contrôle de Loïc et de ses agents : la seule application à ouvrir.**

C'est une application autonome — ni surcouche, ni copie d'un outil existant — avec son propre modèle et ses propres tâches. On y trouve les tâches, les discussions avec les agents (et l'historique des chats existants), les mails, l'agenda, le code, la mémoire et l'infrastructure. Les outils existants y sont branchés derrière des adaptateurs remplaçables.

Nexus répond à tout moment à :

```text
Sur quoi travaillons-nous ?
Qui travaille sur quoi, maintenant ?
Qu'est-ce qui attend Loïc ?
Qu'est-ce qui est bloqué, et pourquoi ?
Qu'est-ce qui a réellement été terminé — avec quelle preuve ?
Qu'est-ce qui a été promis, et à qui ?
Qu'est-ce qui risque d'être oublié ?
Qu'est-ce qui a été dit, où, et par qui ?
```

## 4. Acteurs

| Acteur | Rôle dans Nexus |
|---|---|
| **Loïc** | Propriétaire, valideur final, destinataire des alertes |
| **Helios / Mnēma / Aether** | Agents de nœud (sur Hermes) : exécutent, publient, discutent |
| **Artémis** | Usine de contenu ; composant inclus, éteint volontairement |
| **Claude / Codex / Orca** | Exécutants de code (sessions, worktrees, PR) |
| **Hermes** | Moteur d'exécution des agents de nœud ; branché comme exécutant |

## 5. Jobs-to-be-done

- **JTBD-1** — Quand une tâche naît dans une conversation, je veux qu'elle soit tracée au même endroit pour ne plus me reposer sur ma mémoire.
- **JTBD-2** — Quand un agent prend une tâche, je veux le voir (qui, quoi, quand) sans lui demander.
- **JTBD-3** — Quand quelque chose est bloqué, je veux le savoir avec la cause et la relance prévue — pas le découvrir par hasard.
- **JTBD-4** — Quand un agent déclare « terminé », je veux voir la preuve (commit, fichier, log, capture).
- **JTBD-5** — Quand j'ouvre mon poste le matin, je veux UNE page qui montre l'état réel de tout.
- **JTBD-6** — Quand je décide, je veux que la décision et sa conséquence soient visibles pour tous les agents concernés.
- **JTBD-7** — Quand je veux faire faire quelque chose à un agent, je veux le lui confier depuis la carte et suivre son travail sans changer d'outil.
- **JTBD-8** — Quand je cherche ce qui a été dit, je veux relire les chats (Telegram, sessions Hermes/Claude/Codex) et y répondre depuis Nexus.
- **JTBD-9** — Quand un mail ou un événement d'agenda demande une action, je veux le traiter depuis Nexus.
- **JTBD-10** — Quand Artémis tourne (ou pas), je veux voir son état et ses productions sans deviner.

## 6. Principes produit (non négociables)

1. **Autonomie** : Nexus possède ses tâches, événements, approbations et décisions (`nexus.db`). Aucun outil externe n'est sa colonne vertébrale.
2. **Une carte n'est pas un appel LLM** : créer/déplacer/commenter ne déclenche aucun agent. « Confier à » un agent est une action explicite.
3. **La seule app** : les informations utiles s'affichent dans Nexus. Les données externes (mails, commits, chats) restent chez leur propriétaire ; Nexus les lit et agit via adaptateur.
4. Chaque donnée affichée porte **provenance + fraîcheur**.
5. `unknown` reste `unknown` jusqu'à vérification. Aucune valeur inventée, jamais.
6. **Une seule opération principale** active à la fois ; les tâches auxiliaires sont marquées comme telles.
7. **Aucun secret** conservé : `[REDACTED]`, contrôles de présence uniquement.
8. **Rien d'irréversible sans go** : envoi, publication, suppression, dépense.
9. Local-first, observabilité complète, aucun fournisseur unique requis.
10. Artémis est un composant du modèle, même éteint.

## 7. Périmètre

### 7.1 Phase 1 — Noyau (MVP)

- Tableau de tâches Nexus (créer, déplacer, commenter, assigner — zéro LLM) ;
- Vue **Maintenant** ;
- API locale d'événements : un agent lancé ailleurs déclare `claimed`, `progress`, `blocked`, `done`… avec read-back ;
- Provenance/fraîcheur partout.

### 7.2 Phases 2–3 — Exécution et conversations

- « Confier à » Hermes (Helios/Mnēma/Aether), Claude Code, Codex, Orca ; suivi des runs et des preuves ;
- Vue **Conversations** : lecture des chats existants, puis discussion avec les agents depuis Nexus.

### 7.3 Phases 4–5 — Inbox, code, système

- **Inbox** : mails à traiter, agenda, questions et validations en attente ;
- **Code** : repos, branches, worktrees, PR, diffs ;
- **Système** : mémoire (Mnēma/Hindsight), infrastructure (Synapse), nœuds, quotas.

### 7.4 Phase 6 — Anti-oubli et consolidation

- Vue **À ne pas oublier** (détecteur d'oublis), rapports périodiques, alertes ;
- Artémis branché quand rallumé.

### 7.5 Hors périmètre

- Exécuter une tâche sans action explicite ;
- Envoyer, publier, supprimer ou dépenser sans go de Loïc ;
- Stocker des secrets, tokens ou credentials ;
- Devenir la source de vérité des données externes (mails, commits, chats d'autres outils) ;
- Interface mobile native (Telegram reste la surface d'alerte mobile) ;
- Exposer publiquement sur Internet.

## 8. Exigences fonctionnelles

| ID | Exigence | Phase |
|---|---|---|
| FR-1 | Tableau de tâches Nexus : créer, déplacer, commenter, assigner, lier — sans aucun appel LLM | 1 |
| FR-2 | Cartes enrichies : objectif, propriétaire humain, agent principal, collaborateurs, prochaine action, échéance, blocages, dépendances, preuves attendues | 1 |
| FR-3 | Vue **Maintenant** : opération principale, agents actifs, blocages, attentes Loïc, derniers `done` avec preuve | 1 |
| FR-4 | API locale d'événements d'agents (EVENT-PROTOCOL) avec read-back | 1 |
| FR-5 | Provenance + fraîcheur sur chaque donnée (source, id, âge) | 1 |
| FR-6 | Politique « une seule opération principale » appliquée et affichée | 1 |
| FR-7 | « Confier à » un exécutant (Hermes, Claude, Codex, Orca) depuis une carte ; suivi du run | 2 |
| FR-8 | Preuves : lier commit/fichier/log/capture à une tâche ; « done sans preuve » → `review` | 2 |
| FR-9 | Vue **Conversations** : lecture des chats existants (Telegram, sessions Hermes/Claude/Codex) | 3 |
| FR-10 | Discuter avec un agent depuis Nexus ; créer une tâche depuis un message | 3 |
| FR-11 | **Inbox** : mails à traiter, questions d'agents, validations en attente ; brouillons de réponse (envoi gated) | 4 |
| FR-12 | Agenda : événements, échéances, conflits | 4 |
| FR-13 | Vue **Code** : repos, branches, worktrees, PR, diffs | 5 |
| FR-14 | Vue **Système** : mémoire Mnēma/Hindsight, services Synapse, nœuds, quotas | 5 |
| FR-15 | Vue **À ne pas oublier** avec règles de détection explicites (VIEWS §8) | 6 |
| FR-16 | Recherche globale (tâches, chats, mails, code) avec retour à la source | 3→6 |
| FR-17 | Intégration Artémis (état + productions) quand le nœud est allumé | 6 |

## 9. Exigences non fonctionnelles

- **NFR-1 — Zéro coût par défaut** : l'usage de base (consulter, déplacer, commenter) ne consomme aucun appel LLM.
- **NFR-2 — Local-first** : les données restent sur les machines de Loïc ; aucune sortie réseau non explicite.
- **NFR-3 — Observabilité** : chaque état est inspectable (source, fraîcheur, id, dernière vérification).
- **NFR-4 — Sécurité** : secrets jamais stockés ; gating des actions irréversibles (SECURITY.md).
- **NFR-5 — Réversibilité** : toute mutation externe est précédée d'une sauvegarde ou d'un plan de retour.
- **NFR-6 — Indépendance** : chaque source ou exécutant est derrière un adaptateur remplaçable ; Nexus fonctionne si l'un d'eux disparaît.
- **NFR-7 — Légèreté** : la vue Maintenant se charge en < 2 s sur le poste de Loïc.
- **NFR-8 — Résilience** : un nœud éteint (Artémis) ou une source morte produit des états `unknown` clairs, pas des erreurs bloquantes.

## 10. Politiques transverses

- **Une seule opération principale** — une tâche `in_progress` principale par humain ; les autres sont auxiliaires, marquées comme telles.
- **`unknown` assumé** — tout état non vérifiable s'affiche `unknown` avec sa dernière tentative de contrôle.
- **Preuve d'abord** — une tâche importante se clôt avec preuve ; sinon elle va en `review`.
- **Silence autorisé** — un agent sans rien de nouveau ne publie rien.
- **Frontière par nœud** — chaque nœud applique ses changements par son gardien local.

## 11. Métriques de succès

| Métrique | Cible | Mesure |
|---|---|---|
| Seule app | Loïc n'ouvre plus Telegram/dashboards pour suivre le travail | Auto-évaluation hebdo + logs d'accès locaux |
| Oublis | 0 promesse non tracée > 7 jours sans alerte | Rapport « À ne pas oublier » |
| Transparence | ≥ 80 % des runs d'agents déclarent `claimed` puis `done` + preuve | Événements |
| Hygiène | 0 secret en base (audit) ; 0 état affiché sans provenance | Audit SECURITY |
| Rapidité | Retrouver l'état d'une tâche < 30 s | Test utilisateur |

## 12. Risques & mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| Périmètre trop large (« tout ») | Élevé | Phases strictes ; chaque phase utilisable seule ; go de Loïc à chaque sortie |
| Retomber en « dashboard de plus » | Élevé | Chaque vue répond à une question nommée et permet d'agir |
| Dérive en automatisation dangereuse | Élevé | Aucune exécution sans action explicite ; gating des actions sortantes |
| Données externes périmées présentées comme fraîches | Moyen | Fraîcheur affichée systématiquement |
| Dépendance à un outil externe | Moyen | Adaptateurs remplaçables ; contrats documentés |
| Contenus sensibles (chats, mails) exposés | Moyen | Local uniquement ; minimisation ; pas d'export |

## 13. Questions ouvertes

1. Framework front de l'UI web (ADR-014).
2. Canal d'envoi des messages aux agents depuis Nexus (gateway Hermes, bot Telegram, API propre).
3. Périmètre mail : quelles boîtes, quelles règles de confidentialité (le token Google actuel couvre `calendar` et `drive.file`, pas Gmail — voir INTEGRATIONS §5).
4. Cadence des rapports (quotidien ? hebdo ? les deux ?).
5. Critères exacts pour qu'une tâche « attend Loïc » (relance auto vs attente passive).

## 14. Annexes

- [ARCHITECTURE.md](ARCHITECTURE.md) — architecture technique
- [DATA-MODEL.md](DATA-MODEL.md) — entités et règles
- [EVENT-PROTOCOL.md](EVENT-PROTOCOL.md) — protocole d'événements
- [VIEWS.md](VIEWS.md) — spécification des vues
- [INTEGRATIONS.md](INTEGRATIONS.md) — exécutants et sources
- [ROADMAP.md](ROADMAP.md) — phasage et critères de sortie
- [SECURITY.md](SECURITY.md) — sécurité et permissions
