# GLOSSARY — Nexus

**Date :** 2026-09-28

---

## Le système

- **Nexus** — le système de coordination personnel humain + agents : tâches, présence, événements, preuves, vues. Ce dépôt.
- **Nœud** — une machine de l'écosystème : Helios (poste), Cortex, Synapse, Artémis.
- **Gardien local** — l'agent qui applique les changements de son nœud et en répond (règle de frontière Nexus).
- **Nexus (le nom)** — retenu le 2026-09-27 ; « Orion Cockpit » est abandonné.

## Les acteurs

- **Loïc** — propriétaire ; valide les actions sensibles ; destinataire des alertes.
- **Helios** — agent du poste Windows : desktop, browser, projets, coordination.
- **Mnēma** — agent de Cortex : mémoire, diagnostic, supervision ; rapporteur.
- **Aether** — agent de Synapse : homelab, architecture, services.
- **Artémis** — agent de l'usine de contenu ; inclus dans le modèle, **éteint volontairement** (`offline-by-design`).
- **Exécutants** — Claude Code, Codex CLI, Orca : outils de code pilotables ; **Hermes** : moteur d'exécution durable.

## Le travail

- **Task / Carte** — unité de travail durable ; vit dans Hermes Kanban ; enrichie par Nexus (propriétaire, prochaine action, échéance, preuves).
- **Run** — une exécution concrète d'une tâche par un agent (session, durée, résultat).
- **Événement** — fait daté publié par un acteur (claimed, progress, blocked, handoff, done…), immuable.
- **Preuve / Artifact** — ce qui rend une clôture vérifiable : commit, fichier, log, capture, URL.
- **Blocker** — cause nommée qui empêche d'avancer + ce qui débloquerait + relance prévue.
- **Handoff** — transfert explicite : receveur, état, prochaine action.
- **Approval** — décision attendue de Loïc (ou d'un gardien), avec conséquence affichée.
- **Decision** — décision prise, tracée, opposable (journal des décisions).

## Politiques

- **Une seule opération principale** — au plus une tâche `main` ; les autres sont `auxiliary`, marquées.
- **`unknown`** — état pleinement assumé : « non vérifié ». Jamais « faux », jamais remplacé par une supposition.
- **`offline-by-design`** — nœud éteint volontairement (Artémis) : ce n'est pas une panne.
- **Preuve ou review** — un `done` sans preuve repasse en `review`.
- **Provenance** — source + id de chaque donnée affichée.
- **Fraîcheur** — âge de la donnée (`measured_at`) affiché systématiquement.
- **Gating** — action sensible nécessitant un go humain explicite à chaque fois.
- **Read-back** — relire l'effet d'une écriture pour confirmer qu'elle a bien eu lieu.

## Sources de vérité

- **Hermes Kanban** — le moteur des tâches exécutables (SQLite, dispatcher, runs, workers).
- **Cron** — le planificateur (jobs, exécutions).
- **Hindsight** — la mémoire longue (banks : `helios`, `mnema`…).
- **Board / Tenant** — frontières fortes / namespaces souples dans Hermes Kanban.
- **Dispatcher** — le composant Hermes qui claim et lance les tâches éligibles.
- **Daemon / Heartbeat / Reclaim** — mécanismes de surveillance et reprise des runs.

## Jargon interne

- **Le trio** — Helios, Mnēma, Aether (groupe « Hermes collective » sur Telegram).
- **L'usine** — Artémis et ses chaînes de production de contenu.
- **Le Nexus** — l'écosystème complet (machines + agents + Nexus le système).
- **`[REDACTED]`** — marqueur de toute valeur sensible retirée.
