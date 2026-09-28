# DATA-MODEL — Nexus

**Version :** 0.1 (draft à valider)
**Date :** 2026-09-28

---

## 1. Conventions

- **Ids** — les objets natifs gardent leur id d'origine (`kanban:default#<id>`, `cron:<job>`, `commit:<sha>`…). Les objets propres à Nexus utilisent le préfixe `nx-`.
- **Temps** — ISO-8601 avec fuseau (Europe/Paris). Toute donnée affichée porte `measured_at` (fraîcheur) et `source` (provenance).
- **`unknown`** — valeur pleine et assumée : elle signifie « non vérifié », jamais « faux » ni « vide ».
- **Secrets** — interdits ; remplacés par `[REDACTED]` partout (schéma, logs, export).

## 2. Entités

### 2.1 Node (nœud)

| Champ | Type | Notes |
|---|---|---|
| `id` | str | `helios`, `cortex`, `synapse`, `artemis` |
| `kind` | enum | `workstation`, `homelab`, `content-factory` |
| `status` | enum | `online`, `offline`, `offline-by-design`, `unknown` |
| `last_check_at` | ts | dernière vérification |
| `guardian_agent` | ref | qui applique les changements locaux |

### 2.2 Agent

| Champ | Type | Notes |
|---|---|---|
| `id` | str | `loic` (humain), `helios`, `mnema`, `aether`, `artemis`, `claude`, `codex`, `orca`, `hermes` |
| `kind` | enum | `human`, `node-agent`, `executor` |
| `node` | ref Node | son nœud d'attache |
| `capabilities` | list | ce qu'il peut faire (exécuter, publier, browser…) |
| `presence` | enum | `idle`, `working`, `blocked`, `offline`, `unknown` |

### 2.3 Task (tâche)

L'unité de travail durable. Vit dans **Hermes Kanban** ; Nexus l'enrichit conceptuellement.

| Champ | Requis | Notes |
|---|---|---|
| `id` | ✓ | id kanban |
| `title`, `objective` | ✓ | objectif clair, une phrase |
| `status` | ✓ | selon source ; sinon `unknown` |
| `human_owner` | ✓ | humain responsable (souvent Loïc) |
| `lead_agent` | — | agent principal |
| `collaborators` | — | autres agents mobilisés |
| `next_action` | ✓* | *obligatoire pour toute tâche active |
| `due_at` / `review_at` | — | échéance / relance |
| `blockers` | — | liste (voir Blocker) |
| `depends_on` | — | ids de tâches |
| `context` | — | liens (sessions, repos, docs, conversations) |
| `expected_evidence` | — | ce qui prouvera la clôture |
| `events` | — | journal (voir Event) |
| `priority` | — | `low`, `normal`, `high`, `critical` |
| `operation_role` | — | `main` ou `auxiliary` (politique une op principale) |

### 2.4 Run

Une exécution concrète (agent, session, durée, résultat).

| Champ | Notes |
|---|---|
| `id` | id natif (Hermes run, session Claude/Codex…) |
| `task` | ref Task |
| `agent`, `executor` | qui, avec quel outil (claude/codex/orca/hermes) |
| `started_at`, `ended_at` | |
| `outcome` | `success`, `failed`, `blocked`, `unknown` |
| `artifacts` | refs (commits, fichiers, logs, captures) |
| `session_ref` | lien vers la session/transcript |

### 2.5 Event

Message structuré publié par un acteur (voir [EVENT-PROTOCOL.md](EVENT-PROTOCOL.md)).

| Champ | Notes |
|---|---|
| `id`, `at` | |
| `task` | ref Task (ou null pour présence/coordination) |
| `actor` | qui publie |
| `kind` | `claimed` `working` `progress` `question` `blocked` `needs_human` `handoff` `review` `done` `failed` `unknown` |
| `subject`, `body` | court, puis détail |
| `payload` | données spécifiques au kind |
| `evidence` | refs |
| `needs` | destinataires attendus (pour question/needs_human/handoff) |

### 2.6 Artifact / Evidence

| Champ | Notes |
|---|---|
| `id`, `kind` | `commit`, `file`, `url`, `log`, `screenshot`, `report`, `video` |
| `ref` | chemin/URL/hash |
| `task`, `run` | rattachement |
| `hash` | optionnel (intégrité) |
| `created_by`, `at` | |

### 2.7 Message

Communication structurée entre acteurs (question/réponse/handoff/note), visible de tous.

| Champ | Notes |
|---|---|
| `id`, `thread`, `from`, `to[]` | |
| `task` | ref optionnelle |
| `kind` | `question`, `answer`, `handoff`, `note`, `decision` |
| `body`, `at` | |

### 2.8 Approval (validation)

Toute décision attendue de Loïc (ou d'un gardien) est un objet explicite.

| Champ | Notes |
|---|---|
| `id`, `what` | ce qui est demandé |
| `requested_by`, `at` | |
| `status` | `pending`, `approved`, `rejected`, `expired` |
| `decided_by`, `decided_at` | |
| `consequence` | ce qui se passera après approbation |

### 2.9 Decision (décision)

| Champ | Notes |
|---|---|
| `id`, `statement` | décision prise |
| `context`, `decided_by`, `at` | |
| `affects` | tâches/agents concernés |
| `status` | `active`, `superseded`, `reversed` |

### 2.10 Quota

| Champ | Notes |
|---|---|
| `source` | `opencode-go`, `higgsfield`, `openrouter`, … |
| `window`, `used`, `limit` | fenêtre, consommation, plafond |
| `measured_at` | fraîcheur (obligatoire) |
| `state` | `ok`, `near-limit`, `exhausted`, `unknown` |

## 3. Enums de statut (tâche)

Proposition Nexus (le mapping exact vers Hermes sera relevé en Phase 0, lecture seule) :

```text
backlog → todo → ready → in_progress → review → done
                    ↘ blocked ↗         ↘ failed
                    ↘ dropped            ↘ unknown
```

- `in_progress` : au plus **une opération principale** par humain.
- `review` : terminé déclaré mais preuve manquante ou validation requise.
- `unknown` : état non vérifié (source injoignable, run non confirmé).

## 4. Relations (schéma)

```text
Node 1─* Agent
Human 1─* Task (human_owner)
Task 1─* Run 1─* Artifact
Task 1─* Event
Task *─* Task (depends_on)
Message *─1 Task
Approval *─1 Task (optionnel)
Decision *─* Task
```

## 5. Règles de données

1. **Provenance obligatoire** — toute donnée a `source` + `measured_at`.
2. **Pas de double écriture** — on modifie une tâche dans sa source (Hermes), pas dans deux endroits.
3. **Immutabilité des événements** — un événement publié ne se réécrit pas ; on en publie un nouveau (correction).
4. **Preuve ou review** — une tâche `done` sans `expected_evidence` fourni repasse en `review`.
5. **Secrets interdits** — validation automatique à l'écriture ; toute correspondance sensible → `[REDACTED]` + alerte.
6. **`unknown` honnête** — jamais de valeur par défaut qui masque l'incertitude.

## 6. Où vivent les données

| Donnée | Propriétaire | Nexus |
|---|---|---|
| Tâches exécutables, runs, events kanban | Hermes (`kanban.db`) | lit (MVP), écrit via natif (v1) |
| Jobs cron, exécutions | Hermes cron | lit |
| Sessions, transcripts | état local par nœud | lit/référence |
| Code, commits | Git | lit/référence |
| Mails | Gmail | lit (règles à définir) |
| Calendrier | Google Calendar | lit |
| Mémoire | Hindsight (bank `helios` / `mnema`) | référence |
| Corrélations, politiques, événements hors tâche | **Nexus** (`nexus.db`) | propriétaire |

**Question ouverte n°2 (PRD) :** les événements liés aux tâches doivent-ils être écrits dans les surfaces natives Hermes (recommandé — une seule source) ou dans `nexus.db` ? Arbitrage en Phase 0.
