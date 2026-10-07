# VIEWS — Nexus

**Version :** 0.2 (refonte : la seule app — ADR-016)
**Date :** 2026-09-28

---

## Principe

Chaque vue répond à **une question nommée** et permet d'**agir**. Pas de vue sans question. Toute donnée affichée montre sa **provenance** (source, id, lien vers l'origine) et sa **fraîcheur**. Nexus étant la seule application ouverte, une vue doit suffire sans aller ailleurs — le lien vers la source reste disponible, jamais obligatoire.

| Vue | Question | Phase |
|---|---|---|
| Maintenant | Qu'est-ce qui se passe en ce moment ? | 1 |
| Travail | Où en est tout le travail ? | 1 |
| Conversations | Qu'est-ce qui a été dit, et à qui je réponds ? | 3 |
| Inbox | Qu'est-ce qui attend une action de ma part ? | 4 |
| Planning | Qu'est-ce qui vient ? | 4 |
| Code | Où en sont les chantiers de code ? | 5 |
| Système | Dans quel état sont la mémoire, l'infra, les nœuds, les quotas ? | 5 |
| À ne pas oublier | Qu'est-ce qui risque de passer à la trappe ? | 6 |

---

## 1. Maintenant — « Qu'est-ce qui se passe en ce moment ? »

La page d'accueil. À lire en 5 secondes.

- Opération principale du moment (une seule) + tâches auxiliaires marquées comme telles ;
- Agents actifs : qui, sur quoi, depuis quand (runs en cours) ;
- Blocages actifs : quoi, depuis quand, relance prévue ;
- Ce qui attend Loïc : les demandes (`question`, `needs_human`) dont l'approbation est `pending`, de tout âge, et celles traitées ces 7 derniers jours ; la tuile et les balises de l'étage ne comptent que les demandes en attente ;
- Derniers `done` avec preuve ;
- Nœuds : Helios / Cortex / Synapse / Artémis (états honnêtes, `offline-by-design` assumé).

**Actions :** ouvrir une tâche, répondre à une question (texte libre, options proposées en raccourci), valider ou refuser une demande de validation (conséquence annoncée par l'agent affichée juste au-dessus des boutons, option à choisir quand il y en a au moins deux), confier une tâche (Phase 2). Nexus n'avertit ni ne réveille l'agent : il relit la décision lui-même (EVENT-PROTOCOL §6 ter).

## 2. Travail — « Où en est tout le travail ? »

Le tableau de tâches de Nexus, lisible par Loïc **et** par les agents.

- Colonnes = statuts Nexus (`backlog`, `todo`, `in_progress`, `blocked`, `review`, `done`) ;
- Cartes enrichies : objectif, propriétaire humain, agent principal, collaborateurs, prochaine action, échéance, blocages, dépendances, preuves attendues, run en cours ;
- Filtres : agent, statut, échéance, priorité, rôle (`main`/`auxiliary`) ;
- Historique d'une carte : événements, commentaires, runs, preuves, messages liés.

**Actions :** créer, déplacer, commenter, assigner — **sans jamais déclencher un agent**. Bouton explicite **« Confier à… »** (Phase 2) : choisir l'agent/exécutant, confirmer, suivre le run sur la carte.

## 3. Conversations — « Qu'est-ce qui a été dit, et à qui je réponds ? »

- **Lecture des chats existants** : Telegram (dont le groupe « Hermes collective »), WhatsApp, gateway Hermes, sessions Hermes, Claude Code et Codex — dans une liste unique, filtrable par agent, contact, canal, date ;
- Fil d'une conversation avec provenance de chaque message ;
- **Discussion** depuis Nexus sur le canal de la conversation (natif, gateway Hermes, Telegram, WhatsApp) ;
- **Contact d'un tiers** (ex. prise de rendez-vous) : message préparé, envoyé sur go de Loïc ;
- Liens conversation ↔ tâche.

**Actions :** répondre (gated selon le canal), créer une tâche depuis un message, lier un message à une tâche, marquer « promesse » ou « décision ».

## 4. Inbox — « Qu'est-ce qui attend une action de ma part ? »

- Mails à traiter (nécessite réponse, échéance) ;
- Questions d'agents et validations en attente ;
- Invitations et conflits d'agenda.

**Actions :** lire, trier, préparer une réponse (brouillon), créer une tâche ; **envoi toujours gated**.

## 5. Planning — « Qu'est-ce qui vient ? »

- Échéances et relances des tâches ;
- Événements du calendrier ;
- Jobs cron : dernier run, prochain run, échecs, `unknown` ;
- Rappels : ce qui sera relancé, quand.

## 6. Code — « Où en sont les chantiers de code ? »

- Repos, branches, worktrees (dont Orca) ;
- PR ouvertes, état des checks, diffs ;
- Liens commit ↔ tâche ↔ run (preuves).

## 7. Système — « Dans quel état sont la mémoire, l'infra, les nœuds, les quotas ? »

- **Mémoire** (Mnēma/Hindsight) : souvenirs et rapports utiles, rattachables à une tâche ;
- **Infrastructure** (Synapse) : services, santé, incidents ;
- **Nœuds** : santé, dernier contact ;
- **Quotas / budgets** : Go usage, crédits contenus, pools — état + fraîcheur ;
- **Exécutants** : Hermes, Claude, Codex, Orca — disponibles, sessions actives.

## 8. À ne pas oublier — le détecteur d'oublis

Chaque item = une **règle** visible, pas un jugement vague.

| # | Détection | Seuil par défaut |
|---|---|---|
| 1 | Tâche active **sans prochaine action** | immédiat |
| 2 | Échéance dépassée | temps réel |
| 3 | Tâche **dormante** (aucun événement) | > 7 jours |
| 4 | **Blocage** sans relance planifiée | > 48 h |
| 5 | **Promesse d'agent** non confirmée (claimed sans suite) | > 3 jours |
| 6 | **Engagement de Loïc** capté en conversation et non tracé | immédiat |
| 7 | **Décision** non tranchée (question/needs_human en attente) | > 48 h |
| 8 | **Mail** en attente de réponse (selon règles à définir) | à définir |
| 9 | **Job cron** non vérifié / dernier run en échec | au prochain passage |
| 10 | **Terminé sans preuve** (done sans evidence) | immédiat |
| 11 | **Tâche d'agent sans propriétaire humain** | immédiat |
| 12 | **Nœud injoignable** avec tâches dépendantes | > 24 h |

**Rendu :** chaque item → cause, âge, action proposée (relancer / vérifier / décider / abandonner explicitement).

## 9. Transversal

- **Recherche globale** : tâches, messages, mails, code — avec retour direct à la source.
- **Provenance partout** : `source: telegram:hermes-collective/8812 · mesuré il y a 32 s · [ouvrir]`.
- **États vides honnêtes** : « aucune donnée » ≠ « tout va bien » ≠ `unknown`.
- **Aucune animation sans état réel** : un élément bouge parce que la donnée a changé.
- **Utilisable sans LLM** : chaque vue répond même si tous les modèles sont indisponibles.

## 10. Hors périmètre des vues

- Statistiques décoratives sans action possible ;
- Vues qui déclenchent des actions non validées ;
- Toute exécution d'agent sans action explicite.
