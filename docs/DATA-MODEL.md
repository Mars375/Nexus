# DATA-MODEL — Nexus

**Version :** 0.2 (refonte : application autonome — ADR-011, ADR-012)
**Date :** 2026-09-28

---

## 1. Conventions

- **Ids** — les objets propres à Nexus utilisent le préfixe `nx-` (`nx-task-42`, `nx-evt-…`). Les objets externes gardent leur id d'origine, préfixé par leur système (`hermes:default#t_abcd`, `commit:<sha>`, `telegram:<chat>/<msg>`, `gmail:<thread>`…).
- **Temps** — ISO-8601 avec fuseau (Europe/Paris). Toute donnée affichée porte `measured_at` (fraîcheur) et `source` (provenance).
- **`unknown`** — valeur pleine et assumée : elle signifie « non vérifié », jamais « faux » ni « vide ».
- **Secrets** — interdits ; remplacés par `[REDACTED]` partout (schéma, logs, export).
- **Propriété** — une entité est soit **native** (source de vérité : `nexus.db`), soit **externe** (Nexus en garde un snapshot daté, la vérité reste à la source).

## 2. Entités

### 2.1 Node (nœud) — native

| Champ | Type | Notes |
|---|---|---|
| `id` | str | `helios`, `cortex`, `synapse`, `artemis` |
| `kind` | enum | `workstation`, `homelab`, `content-factory` |
| `status` | enum | `online`, `offline`, `offline-by-design`, `unknown` |
| `last_check_at` | ts | dernière vérification |
| `guardian_agent` | ref | qui applique les changements locaux |

### 2.2 Agent — native

| Champ | Type | Notes |
|---|---|---|
| `id` | str | `loic` (humain), `helios`, `mnema`, `aether`, `artemis`, `claude`, `codex`, `orca` |
| `kind` | enum | `human`, `node-agent`, `executor` |
| `node` | ref Node | son nœud d'attache |
| `executor` | ref Executor | par où on le fait travailler (ex. `helios` → `hermes`) |
| `capabilities` | list | ce qu'il peut faire (exécuter, publier, browser…) |
| `presence` | enum | `idle`, `working`, `blocked`, `offline`, `unknown` |

### 2.3 Executor (exécutant) — native

Un système capable d'exécuter du travail confié par Nexus, derrière un adaptateur.

| Champ | Notes |
|---|---|
| `id` | `hermes`, `claude-code`, `codex`, `orca` |
| `agents` | agents joignables par cet exécutant (ex. `hermes` → `helios`, `mnema`, `aether`) |
| `status` | `available`, `unavailable`, `unknown` (+ `measured_at`) |

### 2.4 Task (tâche) — native

L'unité de travail durable. Vit dans **`nexus.db`** (ADR-012).

| Champ | Requis | Notes |
|---|---|---|
| `id` | ✓ | `nx-task-<n>` |
| `title`, `objective` | ✓ | objectif clair, une phrase |
| `status` | ✓ | voir §3 |
| `human_owner` | ✓ | humain responsable (souvent Loïc) |
| `lead_agent` | — | agent principal (humain ou agent) |
| `collaborators` | — | autres agents mobilisés |
| `next_action` | ✓* | *obligatoire pour toute tâche active |
| `due_at` / `follow_up_at` | — | échéance / relance |
| `blockers` | — | liste (voir Blocker) |
| `depends_on` | — | ids de tâches |
| `context` | — | liens (conversations, repos, docs, mails) |
| `expected_evidence` | — | ce qui prouvera la clôture |
| `priority` | — | `low`, `normal`, `high`, `critical` |
| `operation_role` | — | `main` ou `auxiliary` (politique une op principale) |
| `origin` | — | d'où vient la tâche (message, mail, décision…) |
| `follows` | — | « suite de nx-task-N » (colonne `follows_id`, ADR-022) : la tâche qui corrige une tâche `done`, jamais une autre ; facultatif, posé à la création ou par `PATCH` tant que la tâche n'est pas close ; ce n'est pas une dépendance (aucun blocage) |

### 2.5 Run — native (miroir d'un travail externe)

Une exécution concrète, créée par « confier à » ou déclarée par un agent.

| Champ | Notes |
|---|---|
| `id` | `nx-run-<n>` |
| `task` | ref Task |
| `agent`, `executor` | qui, par quel exécutant |
| `external_ref` | id chez l'exécutant (ex. `hermes:default#t_abcd`, session Claude) |
| `started_at`, `ended_at` | |
| `status` | `dispatched`, `running`, `blocked`, `review`, `done`, `failed`, `cancelled`, `unknown` |
| `native_status` | valeur brute de l'exécutant (ex. Hermes `running`, outcome `crashed`) |
| `artifacts` | refs (commits, fichiers, logs, captures) |

### 2.6 Event — native

Fait structuré publié par un acteur (voir [EVENT-PROTOCOL.md](EVENT-PROTOCOL.md)). Immuable.

| Champ | Notes |
|---|---|
| `id`, `at` | |
| `task`, `run` | refs (ou null pour présence/coordination) |
| `actor` | qui publie |
| `kind` | `claimed` `working` `progress` `question` `blocked` `needs_human` `handoff` `review` `done` `failed` `unknown` ; `answer` (réservé à Nexus, écrit par `POST /api/approvals/…`, EVENT-PROTOCOL §3) |
| `subject`, `body` | court, puis détail |
| `payload` | données spécifiques au kind |
| `evidence` | refs |
| `needs` | destinataires attendus (question/needs_human/handoff) |
| `origin` | `api` (agent direct) ou adaptateur (`hermes`, `codex`…). Distinct de la provenance `source` (où la donnée a été lue), portée par toute réponse |

### 2.7 Conversation — native ou externe

| Champ | Notes |
|---|---|
| `id` | `nx-conv-<n>` (native) ou id externe (`telegram:<chat>`, `hermes-session:<id>`, `claude-session:<id>`…) |
| `source` | `nexus`, `telegram`, `hermes`, `claude-code`, `codex` |
| `participants` | acteurs |
| `title` | |
| `task` | ref optionnelle |
| `last_message_at`, `measured_at` | |

### 2.8 Message — native ou externe

| Champ | Notes |
|---|---|
| `id`, `conversation`, `from`, `to[]`, `at` | |
| `kind` | `chat`, `question`, `answer`, `handoff`, `note`, `decision` |
| `body` | contenu (secrets → `[REDACTED]`) |
| `task` | ref optionnelle (tâche née du message, ou liée) |

### 2.9 Artifact / Evidence — native (référence)

| Champ | Notes |
|---|---|
| `id`, `kind` | `commit`, `file`, `url`, `log`, `screenshot`, `report`, `video` |
| `ref` | chemin/URL/hash |
| `task`, `run` | rattachement |
| `hash` | optionnel (intégrité) |
| `created_by`, `at` | |

### 2.10 Approval (validation) — native

Toute décision attendue de Loïc (ou d'un gardien) est un objet explicite (ADR-019). Une approbation est l'**état de décision** d'une demande : une `question` ou un `needs_human` dont `needs` contient un humain. Elle naît avec l'événement (adressé à au moins un humain **autre que son auteur**), dans la même transaction (`POST /api/events` consigne sa référence dans `effects`, EVENT-PROTOCOL §6 bis). Table `approvals`, référence `nx-appr-<n>`.

| Champ | Notes |
|---|---|
| `id` | `nx-appr-<n>` |
| `request_event` | l'événement de demande (`nx-evt-<n>`), unique : une demande, une approbation |
| `ask_kind` | `question` ou `needs_human`, recopié de l'événement |
| `status` | stocké : `pending`, `approved`, `rejected`, `answered` ; **`expired` n'est jamais stocké** (voir ci-dessous) |
| `expires_at` | optionnel : copie typée de `payload.expires_at`, un instant (jamais du texte) |
| `response_event` | l'événement de réponse (`kind` `answer`, EVENT-PROTOCOL §3), unique, nul tant que personne n'a décidé |
| `version` | verrou optimiste, comme `Task` : deux décisions simultanées ne gagnent pas toutes les deux |

Ce qui est demandé n'est **pas recopié** : `what` (sujet, détail), `requested_by` (acteur), `at` (date), la tâche, les options et la `consequence` se lisent dans l'événement de demande, immuable (règle 3 du §5). `decided_by` et `decided_at` se lisent de même dans l'événement de réponse. Une seule source de vérité : le contenu de la demande ne peut pas diverger de son approbation.

- **`answered`** : la demande était une `question` et quelqu'un y a répondu en texte. **`approved` / `rejected`** : la décision binaire d'un `needs_human`. Quand il propose au moins 2 options, approuver exige de dire laquelle (`choice`, l'indice de l'option). Pas de statut « retirée » : une demande dépassée se corrige par un nouvel événement.
- **`expired` est calculé à la lecture**, avec l'horloge du serveur (`nexus.clock.now()`) : une approbation `pending` dont `expires_at` est atteint (`expires_at <= maintenant`, bornes comprises) est renvoyée `expired`. Rien n'est écrit : pas de tâche de fond, pas d'horloge à synchroniser. Une **première** réponse ou décision reçue après l'échéance, pour une approbation encore `pending`, est refusée (409 `approval_expired`) ; le rejeu identique d'une réponse déjà enregistrée renvoie l'état existant, même après l'échéance (une approbation traitée ne devient jamais `expired`). Les instants se comparent en UTC.
- **`expires_at`** (`payload.expires_at`, ISO-8601 **avec** fuseau, texte) est fixé par l'agent, sans valeur par défaut, au moins 1 minute et au plus 30 jours après la réception. Une demande sans échéance attend sans limite.
- **`consequence`** (`payload.consequence`, texte de 1 000 caractères au plus) est obligatoire pour tout **nouveau** `needs_human`, facultative pour une `question`. Elle est **annoncée par le demandeur et non vérifiée par Nexus** (ADR-005) : l'interface la présente comme « annoncée par <agent> », jamais comme un fait.
- **Pas de rétroremplissage** : les demandes publiées avant la migration 0004 n'ont pas d'approbation.
- Écriture : `POST /api/approvals/<ref>/answer` (une `question`) et `POST /api/approvals/<ref>/decision` (un `needs_human`) ; ils écrivent l'événement `answer` et mettent à jour la ligne dans une seule transaction, sous le verrou de version (EVENT-PROTOCOL §6 ter). Seul un destinataire humain décide, jamais le demandeur ; une approbation `expired` est refusée (409).
- Lecture : `GET /api/approvals` (filtres `status`, `task`, `limit` ; `status=expired` filtre sur le statut effectif) et `GET /api/approvals/<nx-appr-n>`. Chaque réponse porte `source` (`nexus.db`) et `measured_at`.

### 2.10 bis ActorToken (jeton d'acteur) — native

Un acteur s'authentifie par un jeton porteur (ADR-020). Table `actor_tokens`, référence `nx-tok-<n>`. Le jeton en clair n'est jamais stocké.

| Champ | Notes |
|---|---|
| `id` | `nx-tok-<n>` |
| `actor` | l'acteur du jeton (un de `ACTORS`) |
| `label` | à quoi sert le jeton (1 à 64 caractères, sans secret) |
| `token_hash` | SHA-256 hexadécimal du jeton, **jamais le jeton** ; unique |
| `created_at` | instant d'émission |
| `revoked_at` | nul tant que le jeton est actif ; une révocation prend effet dès la requête suivante |
| `last_used_at` | dernière requête authentifiée (jeton valide et acteur d'en-tête concordant ; une route qui refuse ensuite la demande ne l'efface pas), mise à jour au plus une fois par 5 minutes ; nul tant que le jeton n'a pas servi (diagnostic seulement, jamais l'authentification) |

### 2.11 Decision (décision) — native

| Champ | Notes |
|---|---|
| `id`, `statement` | décision prise |
| `context`, `decided_by`, `at` | |
| `affects` | tâches/agents concernés |
| `status` | `active`, `superseded`, `reversed` |

### 2.12 Entités externes indexées

Snapshots datés, jamais source de vérité : `MailThread` (Gmail), `CalendarEvent`, `Commit` / `Branch` / `PullRequest` (Git/GitHub), `MemoryRef` (Hindsight), `Service` (Synapse), `CronJob`, `Quota`. Chacune porte `source`, `external_id`, `measured_at`.

`Quota` : `source` (`opencode-go`, `higgsfield`, `openrouter`…), `window`, `used`, `limit`, `measured_at`, `state` (`ok`, `near-limit`, `exhausted`, `unknown`).

## 3. Statuts de tâche

Propres à Nexus (ADR-012) :

```text
backlog → todo → in_progress → review → done
             ↘ blocked ↗
             ↘ dropped
```

- `in_progress` : au plus **une opération principale** par humain (garanti par un index unique). Le rôle `main`/`auxiliary` n'a de sens qu'en cours : il est effacé quand la tâche en sort.
- `blocked` : une cause, **et** une relance prévue ou ce qui débloquerait. Un blocage sans relance reste permis s'il a un plan ; la vue « À ne pas oublier » le signale après 48 h (VIEWS §8).
- `review` : terminé déclaré mais preuve manquante ou validation requise.
- `dropped` : abandon explicite et motivé (jamais silencieux). Seule reprise permise : `dropped → backlog`.
- `done` : **final** (ADR-022). Aucune transition n'en sort ; ni champ, ni dépendance de la tâche ne change (409 `task_done`, seulement si la requête change quelque chose). Restent possibles : commenter et compléter les preuves (`POST /api/tasks/<ref>/evidence`, ajout seul). Un problème trouvé ensuite se règle dans une tâche de suite (`follows`). Les dépendances **sur** une tâche close restent résolues.
- **Dépendances** : une tâche n'entre en `in_progress`, `review` ou `done` que si toutes ses dépendances sont `done` ou `dropped`.
- Transitions autorisées : `server/src/nexus/tasks/rules.py` (`TRANSITIONS`).
- **Champs de transition** : `POST /api/tasks/<ref>/status` répond **422** si un champ fourni ne s'applique pas au statut visé (par exemple `reason` hors `dropped`, `evidence` hors `review`/`done`) ; `next_action` s'applique partout. Le service refait le contrôle (`field_inapplicable`) pour les appels directs, sans jamais ignorer le champ en silence.
- Une tâche Nexus n'est jamais `unknown` : Nexus en est la source. `unknown` s'applique aux runs, nœuds et données externes non vérifiés.
- Les statuts natifs des exécutants (ex. Hermes `triage`, `ready`, `running`, `archived`) restent au niveau du run (`native_status`).

## 4. Relations (schéma)

```text
Node 1─* Agent *─1 Executor
Human 1─* Task (human_owner)
Task 1─* Run 1─* Artifact
Task 1─* Event
Task *─* Task (depends_on)
Task *─0..1 Task (follows)
Conversation 1─* Message *─0..1 Task
Approval 1─1 Event (demande) ; Approval 0..1─1 Event (réponse) ; Approval *─0..1 Task, via l'événement de demande
Decision *─* Task
```

## 5. Règles de données

1. **Provenance obligatoire** — toute donnée a `source` + `measured_at`.
2. **Une seule source par donnée** — une tâche se modifie dans Nexus ; un mail dans Gmail (via adaptateur). Jamais deux écritures concurrentes.
3. **Immutabilité des événements** — un événement publié ne se réécrit pas ; on en publie un nouveau (correction).
4. **Preuve ou review** — une tâche qui déclare une preuve attendue (`expected_evidence`, c.-à-d. une tâche « importante », PRD §10) et qu'on clôt sans preuve passe en `review`. Un agent, lui, doit toujours joindre une preuve à un événement `done` (EVENT-PROTOCOL §4). Une preuve vide ne compte pas.
5. **Secrets interdits** — validation automatique à l'écriture ; toute correspondance sensible → `[REDACTED]` + alerte.
6. **`unknown` honnête** — jamais de valeur par défaut qui masque l'incertitude.
7. **Cache ≠ vérité** — un snapshot externe affiche toujours sa fraîcheur et peut être reconstruit.

## 6. Où vivent les données

| Donnée | Propriétaire | Nexus |
|---|---|---|
| Tâches, événements, runs, approbations, décisions, empreintes des jetons d'acteur | **Nexus** (`nexus.db`) | propriétaire |
| Conversations nées dans Nexus | **Nexus** | propriétaire |
| Travail confié à Hermes / Claude / Codex / Orca | l'exécutant | suit via `Run.external_ref` |
| Chats Telegram, sessions Hermes/Claude/Codex | leur système | lit, indexe ; envoie via adaptateur (gated) |
| Mails | Gmail | lit, indexe ; brouillons ; envoi gated |
| Calendrier | Google Calendar | lit ; création gated |
| Code, commits, PR | Git / GitHub | lit, référence |
| Mémoire | Hindsight (banks `helios`, `mnema`…) | lit, affiche |
| Services, santé | Synapse / nœuds | lit, affiche |
| Jobs cron | Hermes cron | lit |
