# EVENT-PROTOCOL — Nexus

**Version :** 0.2 (transport via l'API Nexus — ADR-011, ADR-015)
**Date :** 2026-09-28

---

## 1. But

Un langage commun, structuré et visible par tous (Loïc + agents), pour que chacun puisse déclarer :

```text
ce qu'il prend        → claimed
ce qu'il fait         → working / progress
ce qui le bloque      → blocked
ce qu'il demande      → question / needs_human
ce qu'il transfère    → handoff
ce qui est vérifiable → review / done
ce qui a échoué       → failed
ce qu'il ignore       → unknown
```

Règles générales :

- Un événement = un fait daté, **immuable**, attribué à son acteur.
- **Silence autorisé** : pas de nouveau → pas d'événement (pas de bruit).
- **Read-back obligatoire** : l'émetteur vérifie que l'événement est visible de tous avant de le considérer publié.
- Aucun secret dans un événement ; `[REDACTED]` sinon.
- Les événements ne déclenchent **aucun agent** : ils informent.

## 2. Enveloppe

```json
{
  "v": 1,
  "id": "evt_20260928_helios_0007",
  "at": "2026-09-28T07:46:00+02:00",
  "task": "nx-task-142",
  "run": "nx-run-31",
  "actor": "helios",
  "kind": "progress",
  "subject": "Adaptateur Hermes : lecture des runs OK",
  "body": "Runs du board default lus ; structure validée sur les tables tasks et task_runs.",
  "payload": { "percent": 40 },
  "evidence": ["commit:a1b2c3d", "file:F:/Projet/Nexus/docs/ARCHITECTURE.md"],
  "needs": []
}
```

| Champ | Requis | Notes |
|---|---|---|
| `v` | ✓ | version du protocole |
| `id` | ✓ | unique, local à l'acteur |
| `at` | ✓ | ISO-8601 avec fuseau |
| `task` | opt | réf tâche Nexus (`nx-task-…`) ; `null` pour un événement de coordination |
| `run` | opt | réf run Nexus (`nx-run-…`) quand l'événement concerne un travail confié |
| `actor` | ✓ | `loic`, `helios`, `mnema`, `aether`, `artemis`, `claude`, `codex`, `orca`, `hermes` |
| `kind` | ✓ | voir §3 |
| `subject` | ✓ | une ligne lisible |
| `body` | opt | détail court |
| `payload` | opt | données du kind |
| `evidence` | opt* | *requis pour `done` |
| `needs` | opt* | *requis pour `question`, `needs_human`, `handoff` |

## 3. Kinds

| Kind | Sens | Requis en plus | Exemple |
|---|---|---|---|
| `claimed` | « je prends cette tâche » | — | `^ claimed #142 par helios` |
| `working` | début d'exécution (run) | `payload.run_ref` | `^ working #142, session tmux …` |
| `progress` | avancement notable | `payload.percent` ou description | `^ 40 % : parse OK` |
| `question` | question à un acteur | `needs` + question explicite | `^ question → mnema : quel scope ?` |
| `blocked` | bloqué | cause + `payload.follow_up_at` ou plan | `^ bloqué : SSH artemis timeout` |
| `needs_human` | décision de Loïc requise | décision attendue + options | `^ validation : publier l'épisode ?` |
| `handoff` | transfert de responsabilité | receveur + prochaine action | `^ handoff → aether : reste à poser la clé` |
| `review` | prêt pour revue | quoi vérifier + où | `^ review : PR #12, diff court` |
| `done` | terminé | `evidence` non vide | `^ done : commit a1b2c3d + tests verts` |
| `failed` | échec | cause + effet | `^ failed : 429 Go, run non exécuté` |
| `unknown` | état non vérifiable | dernière vérification | `^ unknown : run non confirmé depuis 2 h` |

## 4. Règles par kind

- **claimed** — avant de commencer à travailler ; un claim remplace le précédent (dernier claim gagne, il est daté).
- **working** — ouvre un run ; un seul run actif par agent et par tâche.
- **progress** — pas plus d'un par étape significative ; pas de spam.
- **question / needs_human** — doit nommer le destinataire (`needs`) et être actionnable : pas de « ça avance ? ».
- **blocked** — doit dire : cause, impact, ce qui débloquerait, relance prévue. Sinon c'est `unknown`.
- **handoff** — doit dire : receveur, état exact, prochaine action, ce qui est déjà fait. Un handoff sans prochaine action est refusé.
- **review** — doit pointer la preuve à examiner.
- **done** — sans `evidence` → transformé en `review` automatiquement (règle « preuve ou review »).
- **failed** — cause exacte quand connue ; effets de bord constatés.
- **unknown** — honnête : ce qu'on ne peut pas vérifier, avec la dernière date de contrôle.

## 5. Exemples réels (cible)

Prise en charge :

```json
{ "v": 1, "id": "evt_0001", "at": "2026-09-28T09:05:00+02:00",
  "task": "nx-task-7", "actor": "helios", "kind": "claimed",
  "subject": "Je prends l'API d'événements", "needs": [] }
```

Blocage :

```json
{ "v": 1, "id": "evt_0002", "at": "2026-09-28T11:22:00+02:00",
  "task": "nx-task-7", "actor": "helios", "kind": "blocked",
  "subject": "SSH Artémis injoignable",
  "body": "Timeout Tailscale. Impact : pas de lecture de l'usine. Déblocage : nœud rallumé par Loïc.",
  "payload": { "follow_up_at": "2026-09-29T09:00:00+02:00" }, "needs": ["loic"] }
```

Terminé avec preuve :

```json
{ "v": 1, "id": "evt_0003", "at": "2026-09-28T17:40:00+02:00",
  "task": "nx-task-7", "actor": "helios", "kind": "done",
  "subject": "API d'événements livrée",
  "evidence": ["commit:f00db4r", "log:artifacts/smoke-read-20260928.txt"] }
```

## 6. Transport

- **API locale Nexus (Phase 1) :** un agent publie par `POST /api/events` ; Nexus valide (champs requis, anti-patterns §7, scan de secrets) puis écrit dans `nexus.db`. C'est le chemin des agents lancés ailleurs (ADR-015 b).
- **Adaptateurs d'exécution (Phase 2) :** pour un travail confié, l'adaptateur traduit les événements natifs en événements Nexus (`origin` = nom de l'adaptateur). Ex. Hermes : `claimed` → `claimed`, `blocked` → `blocked`, `review_requested` → `review`, `completed` → `done` (preuves reprises du `metadata` de complétion).
- **Read-back :** l'émetteur relit l'événement (`GET /api/events/<id>`) et confirme sa visibilité ; tant que ce n'est pas confirmé, il reste `unknown` côté émetteur.
- **Diffusion :** l'UI reçoit les nouveaux événements par WebSocket ; les alertes urgentes (`needs_human`, `blocked` critique) partent aussi sur Telegram.

## 6 bis. Effets sur la tâche (implémentés en Phase 1)

Un événement valide est **toujours enregistré** (c'est un fait déclaré). Ses effets sur la tâche passent par les règles des tâches ; un effet refusé est consigné dans `effects` avec sa raison, sans faire échouer la publication.

| Kind | Effet sur la tâche |
|---|---|
| `claimed` | l'émetteur devient agent principal |
| `working` | passage en `in_progress` (ouvre le run) |
| `blocked` | passage en `blocked` avec cause, plan, relance |
| `review` | passage en `review` |
| `done` | passage en `done` avec les preuves (sans preuve : l'événement est stocké en `review`) |
| `handoff` | le destinataire devient agent principal ; la prochaine action est mise à jour |
| `progress`, `question`, `needs_human`, `failed`, `unknown` | aucun changement d'état : visibles dans l'historique et les vues |

Une clôture (`done`, `review`, `blocked`, `handoff`, `failed`) doit nommer son run (`run` ou `payload.run_ref`). Si elle vise un autre run que le run actif de l'agent (ex. `done(r1)` arrivé après `working(r2)`) ou n'en nomme aucun alors qu'un run est actif, elle est enregistrée mais ne modifie pas la tâche et ne ferme pas le run actif. Un seul run actif par agent et par tâche ; un `handoff` nomme **un seul** destinataire.

Autres garanties : un renvoi du même `id` par le même acteur est une relecture (pas de doublon) ; un même `id` réutilisé pour un autre contenu est refusé ; le même fait republié dans les 10 minutes est refusé comme bruit ; les secrets sont masqués avant écriture ; un identifiant d'événement ou une référence de run qui contient un secret est refusé (masqué, il ne serait plus unique).

Exemple exécutable : `uv run python -m nexus.demo_agent --task nx-task-1 --actor helios --evidence commit:…` (`server/src/nexus/demo_agent.py`).

## 7. Anti-patterns (refusés)

- « done » sans preuve.
- « handoff » sans receveur ni prochaine action.
- Question sans destinataire.
- Événement-bruit (je répète la même chose toutes les 5 min).
- Modifier un événement passé au lieu d'en publier un rectificatif.
- Publier un secret, même partiellement.
