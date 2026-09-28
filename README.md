# Nexus

> Le système de coordination personnel humain + agents.

Nexus est la couche locale qui réunit Loïc et tous ses agents — Helios, Mnēma, Aether/Synapse, Artémis, Claude Code, Codex, Orca, Hermes — autour d'un espace unique : tâches, présence, messages, preuves, planning, quotas, mails. Sans dupliquer les systèmes existants. Sans lancer de LLM par défaut.

## Le problème

- Trop d'onglets, trop de conversations parallèles, trop d'états invisibles.
- Des tâches se perdent ; des promesses d'agents s'oublient ; des blocages restent silencieux.
- Personne — ni l'humain ni les agents — ne peut répondre vite à : *qui travaille sur quoi ? qui attend qui ? qu'est-ce qui est bloqué ? qu'est-ce qui a réellement été terminé ?*

## Ce que Nexus est, n'est pas

| C'est | Ce n'est pas |
|---|---|
| Un espace de coordination + mémoire opérationnelle partagée | Un chatbot |
| Une surcouche d'agrégation au-dessus des sources de vérité | Un remplacement de Hermes / Synapse / Mnēma |
| Un Kanban utilisable sans aucun appel LLM | Un lanceur automatique de LLM |
| Un endroit où chaque état a une source et une fraîcheur | Un dashboard d'animations non vérifiables |

## Architecture en une image

```text
Loïc + agents (Helios, Mnēma, Aether, Artémis, Claude, Codex, Orca)
                         ↓
        NEXUS — coordination locale
     (tâches, événements, preuves, vues, alertes)
                         ↓
Hermes Kanban · Cron · Git · sessions · mails · calendrier · quotas
                         ↓
références contextuelles → Mnēma (mémoire) · Synapse (architecture)
```

## Principes fondateurs

1. **Une carte ≠ un appel LLM.** Créer, déplacer ou commenter une tâche ne déclenche aucun agent.
2. **Les sources de vérité restent chez leurs propriétaires.** Nexus corrèle et affiche ; il ne recopie pas.
3. **Chaque donnée affichée porte sa provenance** (source + fraîcheur).
4. **`unknown` reste `unknown`** jusqu'à vérification — jamais de valeur inventée.
5. **Une seule opération principale active** à la fois.
6. **Aucun secret stocké** — toute valeur sensible est remplacée par `[REDACTED]`.
7. **Local, observable, inspectable** — pas de dépendance à un fournisseur unique.
8. **Artémis fait partie du modèle**, même éteint volontairement.

## Documents

- [docs/PRD.md](docs/PRD.md) — le produit : besoin, périmètre, exigences
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — comment c'est construit
- [docs/DATA-MODEL.md](docs/DATA-MODEL.md) — Task / Agent / Run / Event / Artifact…
- [docs/EVENT-PROTOCOL.md](docs/EVENT-PROTOCOL.md) — ce que les agents publient
- [docs/VIEWS.md](docs/VIEWS.md) — Maintenant, Travail, À ne pas oublier, Planning, Ressources
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — Hermes, Cron, Git, mails, sessions, quotas, Synapse, Mnēma, Artémis
- [docs/ROADMAP.md](docs/ROADMAP.md) — phases et critères de sortie
- [docs/SECURITY.md](docs/SECURITY.md) — secrets, permissions, gating
- [docs/INSPIRATIONS.md](docs/INSPIRATIONS.md) — ce qu'on prend (et évite) ailleurs
- [docs/GLOSSARY.md](docs/GLOSSARY.md) — vocabulaire
- [DECISIONS.md](DECISIONS.md) — journal des décisions
- `AGENTS.md` — règles pour les agents qui contribuent *(à ajouter après approbation de Loïc)*

## Statut

- **2026-09-28** — Phase 0 : fondations documentaires (ce dépôt).
- Prochaine étape : validation du PRD + du modèle de données par Loïc, puis pont lecture seule vers Hermes Kanban.

## Périmètre du dépôt

Ce dépôt contient la **documentation de conception** de Nexus. Le code viendra en Phase 1 (voir [docs/ROADMAP.md](docs/ROADMAP.md)). Les critères de chaque phase sont vérifiables et passent par un go explicite de Loïc.
