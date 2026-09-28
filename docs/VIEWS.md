# VIEWS — Nexus

**Version :** 0.1 (draft à valider)
**Date :** 2026-09-28

---

## Principe

Chaque vue répond à **une question nommée**. Pas de vue sans question. Toute donnée affichée montre sa **provenance** (source, id, lien vers l'origine) et sa **fraîcheur**.

---

## 1. Maintenant — « Qu'est-ce qui se passe en ce moment ? »

La page d'accueil opérationnelle. À voir en 5 secondes.

**Contenu :**

- Opération principale du moment (une seule) + tâches auxiliaires marquées comme telles ;
- Agents actifs : qui, sur quoi, depuis quand (runs `running` côté Hermes + sessions) ;
- Blocages actifs : quoi, depuis quand, relance prévue ;
- Ce qui attend Loïc : validations (`needs_human`), questions (`question`), approbations `pending` ;
- Derniers `done` avec preuve (le pouls positif) ;
- Nœuds : Helios / Cortex / Synapse / Artémis (états honnêtes, `offline-by-design` assumé).

**Actions :** ouvrir une tâche, ouvrir la session liée, répondre à une question, valider/refuser (avec conséquence affichée).

## 2. Travail — « Le tableau de bord du travail »

Le Kanban complet, lisible par Loïc **et** par les agents.

**Contenu :**

- Boards et colonnes (statuts réels de la source) ;
- Cartes enrichies : objectif, propriétaire humain, agent principal, collaborateurs, prochaine action, échéance, blocages, dépendances, preuves attendues ;
- Filtres : par agent, statut, échéance, priorité, rôle (`main`/`auxiliary`) ;
- Historique d'une carte : événements, comments, runs, preuves.

**Actions :** créer, déplacer, commenter, assigner — **sans jamais déclencher un agent**. La logique d'exécution reste celle de Hermes (dispatcher), pas de Nexus.

## 3. À ne pas oublier — le détecteur d'oublis

La vue anti-oubli. Chaque item = une **règle** visible, pas un jugement vague.

**Détections (avec seuils par défaut, ajustables) :**

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

**Rendu :** chaque item → cause, âge, action proposée (relancer / vérifier / décider / abandonner explicite).

## 4. Planning — « Qu'est-ce qui vient ? »

**Contenu :**

- Échéances et relances des tâches (agenda simple) ;
- Jobs cron : dernier run, prochain run, échecs, `unknown` ;
- Événements calendrier (scopes existants) ;
- Rappels : ce qui sera relancé, quand.

## 5. Ressources — « Avec quoi on travaille ? »

**Contenu :**

- Quotas / budgets : Go usage, crédits contenus, pools — état + fraîcheur ;
- Sessions actives : Claude, Codex, Orca, Hermes — liées aux runs ;
- Repos / branches / worktrees : état des chantiers de code ;
- **Références contextuelles** (pas de duplication) :
  - dashboard **Mnēma** (mémoire, diagnostic) ;
  - dashboard **Synapse** (architecture, services) ;
- Nœuds : Santé globale, dernier contact.

## 6. Transversal

- **Recherche globale** : texte, id, agent, tâche — avec retour direct à la source d'origine.
- **Provenance partout** : `source: kanban:default#142 · mesuré il y a 32 s · [ouvrir]`.
- **États vides honnêtes** : « aucune donnée » ≠ « tout va bien » ≠ `unknown`.
- **Aucune animation sans état réel** : un élément bouge parce que la donnée a changé, pas pour faire vivant.
- **Accessibilité** : tout est lisible sans LLM ; chaque vue répond même si tous les modèles sont indisponibles.

## 7. Hors périmètre des vues

- Recopier les dashboards Synapse/Mnēma (simple référence contextuelle) ;
- Statistiques décoratives sans action possible ;
- Vues qui déclenchent des actions non validées.
