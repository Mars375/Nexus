# ARCHITECTURE — Nexus

**Version :** 0.1 (draft à valider)
**Date :** 2026-09-28

---

## 1. Vue d'ensemble

```text
┌─────────────────────────────────────────────────────────────────┐
│  SURFACES                                                        │
│  Page web locale (Maintenant · Travail · À ne pas oublier ·      │
│  Planning · Ressources)  ·  Telegram (alertes/rapports)          │
├─────────────────────────────────────────────────────────────────┤
│  CORE NEXUS (local, zéro LLM par défaut)                         │
│  · Modèle commun (Task/Agent/Run/Event/Artifact)                 │
│  · Corrélation multi-sources (par ids, jamais par recopie)       │
│  · Politiques (une op principale, unknown, preuves, gating)      │
│  · Bus d'événements (agents → tous)                              │
├─────────────────────────────────────────────────────────────────┤
│  ADAPTATEURS (un par source, remplaçables)                       │
│  hermes-kanban · hermes-cron · sessions · git · mail ·           │
│  calendar · quotas · nodes · memory-refs                         │
├─────────────────────────────────────────────────────────────────┤
│  SOURCES DE VÉRITÉ (restent chez leurs propriétaires)            │
│  Hermes (tâches/runs) · Cron (jobs) · Git (code) ·               │
│  sessions locales · Gmail/Calendrier · Hindsight (mémoire)       │
└─────────────────────────────────────────────────────────────────┘
```

## 2. Décision structurante : surcouche, pas remplacement

- **Hermes Kanban reste le moteur durable** des tâches exécutables (SQLite multi-boards, machine d'états, dispatcher, workers, runs, preuves — audité le 2026-09-27 : cycle `claim → spawn → surveillance → reclaim/retry`, heartbeat, fences de propriété).
- Nexus **lit** Hermes et les autres sources, **corrèle**, **affiche** ; il **écrit** uniquement via les surfaces natives (outils Kanban, comments/events, transitions) ou via des adaptateurs explicites.
- Aucune seconde base « vérité » : la base locale de Nexus est un **index de corrélation + cache**, reconstructible à tout moment depuis les sources.

## 3. Composants

### 3.1 Core Nexus

| Module | Rôle |
|---|---|
| `model` | Types communs (Task, Run, Event, Artifact, Approval…) et validations |
| `correlate` | Jointures par ids : tâche ↔ run ↔ session ↔ commit ↔ preuve |
| `policy` | Règles produit : une op principale, staleness, `unknown`, gating |
| `events` | Réception/normalisation/publication des événements d'agents |
| `views` | Calcul des vues (agrégations, détections « à ne pas oublier ») |

### 3.2 Adaptateurs

Chaque adaptateur expose la même interface minimale :

```text
probe()        → état de la source (joignable, fraîcheur, erreurs)
read(query)    → données normalisées + provenance
write(action)  → mutation gated (si supportée)
```

| Adaptateur | Source | Sens | Notes |
|---|---|---|---|
| `hermes-kanban` | `kanban.db` + CLI `hermes kanban` | R→(W) | cœur du MVP ; lecture via CLI/DB en lecture seule d'abord |
| `hermes-cron` | `cron/jobs.json`, `cron/executions.db` | R | jobs, dernier/prochain run, échecs |
| `sessions` | `state.db` (sessions/messages), dossiers de sessions Claude/Codex | R | lier runs et traces |
| `git` | repos locaux (F:/Projet/…), `gh` | R | commits, branches, preuves |
| `mail` | Gmail (via outils/skills existants) | R | à traiter seulement ; jamais d'envoi sans validation |
| `calendar` | Google Calendar (scopes existants) | R | échéances, événements |
| `quotas` | Go usage, crédits Higgsfield, pools | R | fenêtres 429, soldes |
| `nodes` | Tailscale/SSH, healthchecks | R | Helios, Cortex, Synapse, Artémis (éteint = `unknown` propre) |
| `memory-refs` | Hindsight (bank `helios`) | R | références contextuelles, pas de duplication |

### 3.3 Stockage local

- **`nexus.db` (SQLite)** — index de corrélation, cache, événements de coordination, politiques. Reconstructible.
- Rien de propriétaire n'y est dupliqué en dur : les données restent à la source, Nexus garde ids + snapshots datés.

### 3.4 Interface

- **Page web locale** (servie sur le poste de Loïc) : les 5 vues, recherche, provenance cliquable.
- **Telegram** (canal existant) : alertes, rapports périodiques, questions (le mobile passe par là).
- Pas d'exposition publique ; pas d'app mobile dédiée.

### 3.5 Bus d'événements

- Les agents publient leurs événements (claimed, progress, blocked, handoff…) — voir [EVENT-PROTOCOL.md](EVENT-PROTOCOL.md).
- Transport : d'abord via les surfaces natives Hermes (events/comments Kanban) ; bus local Nexus si besoin d'événements hors tâche (présence, coordination).
- Lecture temps réel : le dashboard Kanban expose déjà un WebSocket (`/api/plugins/kanban/events`) — pattern à réutiliser.

## 4. Flux

### 4.1 Lecture (MVP)

```text
adaptateurs → normalisation → corrélation → vues → page locale
                 ↑
          provenance + fraîcheur attachées à CHAQUE donnée
```

- Fréquences : kanban/cron ≈ 30–60 s (ou événementiel si dispo) ; git/sessions à la demande ; quotas ≈ 15 min.
- Un nœud injoignable → état `unknown` + dernière vérification, jamais d'erreur bloquante.

### 4.2 Écriture (v1+)

```text
action (humain ou agent)
  → validation politique (gating si sensible)
  → adaptateur de la source
  → read-back obligatoire (l'effet est relu et confirmé)
  → événement "done"/"failed" publié
```

- Toute mutation est : **réversible**, **sauvegardée avant**, **tracée**, **relue après**.

## 5. Frontières multi-nœuds

- **Règle Nexus :** chaque nœud applique ses changements locaux par son gardien (Cortex/Mnēma, Synapse/Aether, Helios, Artémis).
- Phase actuelle : lecture distante uniquement (SSH/Tailscale read-only) ; aucune mutation croisée.
- Artémis : éteint volontairement → considéré `offline by design`, données `unknown`, jamais « en panne ».

## 6. Sûreté de fonctionnement

- Nexus dégradé (source morte, parse error) → la vue affiche la dernière donnée connue **datée**, marquée périmée.
- Pas de dépendance unique : chaque adaptateur est indépendant et remplaçable.
- La page Maintenant doit rester utile même si 100 % des LLM sont indisponibles.

## 7. Stack proposée (à trancher en Phase 0)

| Option | Avantages | Inconvénients |
|---|---|---|
| **A. Serveur Python (FastAPI) + SQLite + UI web légère** | local, maîtrisé, testable ; cohérent avec l'existant | à construire |
| **B. Extension du dashboard Hermes existant** (plugin kanban) | réutilise l'existant | couplage fort à Hermes ; moins libre |
| **C. App statique + scripts** | minimal | limites d'agrégation temps réel |

**Recommandation :** A, avec réutilisation des patterns du dashboard Hermes (API + WS). Décision à valider avec Loïc en Phase 0.

## 8. Contraintes techniques connues (vérifiées 2026-09-27)

- Hermes v0.21.4 sur Helios ; board `default` vide ; dispatcher 60 s ; `failure_limit=2` ; stale timeout 14 400 s ; review auto ; auto-décomposition max 3/tick ; `max_in_progress` = non configuré (la politique « une op principale » sera portée par Nexus).
- Tables Kanban : `tasks`, `task_runs`, `task_events`, `task_comments`, `task_links`, `task_attachments`, `kanban_notify_subs`.
- Le détail exact des enums de statut sera relevé en Phase 0 par lecture seule de `hermes_cli/kanban_db.py` (aucune valeur devinée).
