# Conversations, lot 1 : lire les sessions locales des agents, chercher, créer une tâche depuis un message

- Phase 3 (ROADMAP, « Conversations »), premier lot. Issue #204. Tâche auxiliaire : l'implémentation commence après la clôture de la Phase 2.
- **Choix marqués (C1 à C16, §12) : choisis par l'agent sous la délégation totale de Loïc du 2026-11-25 (ADR-024), consignés dans ADR-025.** Quand un choix touche aux données de Loïc, on a pris l'option la plus restreinte et la plus réversible ; trois valeurs du premier jet ont été resserrées à ce titre le 2026-11-26 (C3, C5, C7). Ce cadrage et ses choix ont été rédigés par des subagents ; le fil principal les a relus et **confirmés le 2026-11-26**, avec les corrections du §16 (ADR-024 réserve la délégation au fil principal).
- Le lot n'a besoin d'aucun accès de Loïc : pas de jeton, pas de connexion, rien d'envoyé. Telegram, WhatsApp, Gmail, l'envoi de messages et le contact de tiers sont **hors du lot** (§2).
- Les formats ont été relevés le 2026-11-25 sous Windows 11, sur la machine de Loïc, par des scripts qui n'affichaient que des noms de clés, des types, des comptes et des tailles, jamais de valeur. Aucun fichier d'authentification n'a été ouvert ni listé. Les exemples de ce document sont inventés.

## 1. Ce que le lot livre

1. Une lecture **seule** des sessions locales de trois sources : Claude Code, Codex et Hermes. Nexus en garde un index daté et masqué dans `nexus.db` (ARCHITECTURE §« Index/cache externe »). La vérité reste à la source (ADR-016, DATA-MODEL §6).
2. Une vue **Conversations** : la liste des conversations, le fil des messages et une recherche plein texte sur l'ensemble.
3. **Créer une tâche depuis un message** : la tâche garde un lien de provenance stable vers le message.

Critère de fin du lot : Loïc retrouve en moins de 30 s ce qui a été dit dans une session Claude Code, Codex ou Hermes du mois écoulé, et en tire une tâche qui renvoie au message. Aucun octet n'est écrit chez une source, aucun fichier hors de la liste blanche n'est ouvert, et aucun secret synthétique semé dans les fixtures n'apparaît dans `nexus.db`.

## 2. Hors du lot

- Telegram (adaptateur direct), WhatsApp, Gmail, chat natif Nexus, tout envoi, tout contact de tiers.
- Les sessions Hermes d'une autre source que `cli` (`telegram`, `acp`…) et les conversations de groupe (`chat_type = group`). Le réglage C5 les ouvrira plus tard, sans migration.
- Les transcriptions de subagents Claude Code (`<projet>/<session>/subagents/*.jsonl`), les `tool-results/` et `memory/`.
- Les sorties d'outils, les appels d'outils, le raisonnement (`thinking`, `reasoning`, contenu chiffré) et les invites système.
- Le flux temps réel : aucun événement WebSocket pour les conversations (C10).
- Les sessions des runs de Nexus. Claude Code tourne avec `--no-session-persistence` et Codex sous le `CODEX_HOME` de Nexus : rien de tout cela n'est sous les racines lues. Les runs Hermes, eux, écrivent sans doute dans la même `state.db`, sous une `source` non relevée (§3.4) : seule `cli` est lue (C5), donc toute autre valeur reste exclue.
- Les sessions Codex en clair (`.jsonl` sans `.zst`) : aucune n'a été vue (§3.2), le motif ne les admet pas (C7).

## 3. Formats relevés (structure seulement)

### 3.1 Claude Code

- Emplacement : `~/.claude/projects/<slug du dossier>/<uuid de session>.jsonl`, avec exactement deux niveaux sous `projects`. On a compté 127 fichiers de session à la racine d'un projet ; avec les sous-dossiers, 228 fichiers pour 207 Mo, le plus gros faisant 26 Mo. La plus longue ligne vue fait 190 Kio.
- Une ligne est un objet JSON. Seize valeurs de `type` ont été vues dans l'échantillon : `user`, `assistant`, `attachment`, `system`, `api-request`, `api-request-blob`, `api-request-shape`, `queue-operation`, `last-prompt`, `ai-title`, `custom-title`, `mode`, `session-owner`, `pr-link`, `cost-state` et `atis-latch`. Les jeux de clés varient d'une ligne à l'autre au sein d'un même type : le format bouge.
- Le motif de nom du §5.1 a été vérifié sur la machine : 131 fichiers sur 131 au niveau 2, et tous les dossiers de niveau 1 (comptes seulement).
- Champs utiles d'une ligne `user` ou `assistant` : `uuid`, `parentUuid`, `sessionId`, `timestamp` (ISO-8601 UTC), `isSidechain`, `isMeta`, `cwd`, `gitBranch`, `version`, et `message.role` / `message.content`. Pour `assistant` : `message.model`. Pour `user` : `origin.kind`, avec les valeurs vues `human` et `task-notification`, ou l'absence de `origin`.
- `message.content` est une chaîne, ou une liste de blocs `text`, `tool_use`, `tool_result`, `thinking`, `server_tool_use` ou `advisor_tool_result`. La plupart des lignes `user` ne portent que des `tool_result` (1 316 sur 1 455 dans l'échantillon).
- Titre : `custom-title.customTitle`, à défaut `ai-title.aiTitle`.
- **À ne jamais stocker** : `api-request-blob` (requête complète, invite système comprise), `toolUseResult` (peut contenir un fichier entier, `originalFile`), `attachment` (sorties de hooks, environnement), `session-owner` (identifiants de compte et d'organisation), `cost-state`, `mcpMeta`.

### 3.2 Codex

- Emplacement : `~/.codex/sessions/AAAA/MM/JJ/rollout-<horodatage>-<uuid>.jsonl.zst`. Les 87 fichiers relevés sont **tous compressés en zstd**, pour 61 Mo compressés ; le plus gros fait 32 Mo compressé, et le plus gros fichier décompressé de l'échantillon fait 7,3 Mo. Aucun `.jsonl` en clair n'a été vu. On ne sait donc pas encore si une session en cours s'écrit en clair et n'est compressée qu'à la fin (**non vérifié**). Le lecteur n'admet donc que `.jsonl.zst` (C7) : une session en cours, si elle s'écrit en clair, n'apparaît qu'une fois compressée.
- Une ligne : `{type, ordinal, timestamp, payload}`. Les `type` vus : `session_meta`, `turn_context`, `response_item`, `event_msg`, `token_usage_record`, `world_state`, `inter_agent_communication_metadata`, `compacted`. Une ligne de 3,1 Mo a été vue.
- Le motif de nom du §5.1 a été vérifié : 87 fichiers sur 87.
- Messages : `response_item` dont `payload.type = message`, avec `payload.role`. Les blocs `content` sont `input_text` ou `output_text` (`text`) ; on a vu aussi `input_image`. On ne garde que les rôles `user` et `assistant` ; les valeurs exactes de `role` n'ont pas été comptées (§3.4). `reasoning` (`encrypted_content`), `function_call*`, `custom_tool_call*` et `agent_message` (entre agents) sont ignorés.
- Session : `session_meta.payload.id` et `cwd`. **À ne jamais stocker** : `base_instructions`, `creator_account_id`, `creator_user_id`, `git` et tout `turn_context`.
- Le dossier `~/.codex` contient aussi les fichiers de connexion de Loïc. Le lecteur n'en voit aucun (§5.2).

### 3.3 Hermes

- Emplacement : `%LOCALAPPDATA%\hermes\state.db`, une base SQLite en WAL (`-wal`, `-shm`), de 508 Mo, `schema_version = 33`. Elle contient 946 sessions et 43 880 messages, dont 129 M caractères de `content` ; le plus long fait 140 k caractères. La table `messages_fts` de Hermes existe, mais Nexus ne s'en sert pas.
- Le même dossier contient des profils de navigateur, un `vault/`, des sauvegardes et des verrous de réparation (`state.db.quarantine.lock`, `.bak` d'urgence) : la base a déjà demandé des réparations. Rien d'autre que `state.db` n'est lu.
- Tables lues, et seulement celles-ci : `sessions` (`id`, `source`, `chat_type`, `title`, `profile_name`, `started_at`, `ended_at`, `cwd`, `archived`, `hidden`) et `messages` (`id`, `session_id`, `role`, `content`, `timestamp`, `display_kind`, `_compressed_summary`). Les instants sont des secondes epoch (`REAL`).
- Valeurs vues : `sessions.source` vaut `acp`, `cli`, `cron`, `kanban`, `oneshot` ou `telegram` ; `chat_type` vaut `dm`, `group` ou vide ; `messages.role` vaut `user`, `assistant`, `tool` ou `session_meta`. `display_kind` est vide (presque toujours) ou vaut `failed_turn`, `hidden`, `internal_notification`, `steer` ou `process_complete`.
- Surface native écartée : `hermes sessions export`. Elle réexporte des sessions entières à chaque passe, et la même commande porte `--upload`, `--public` et `--delete-after-verified` : une erreur d'argument publierait ou supprimerait (C6).

### 3.4 Non vérifié (à relever, comptes seulement, dans la PR de la source)

- Codex : les valeurs de `payload.role` (on suppose `developer` en plus de `user` et `assistant`) et la part des messages `user` injectés par l'outil (contexte d'environnement, instructions de dépôt), avec leurs préfixes exacts.
- Codex : la forme d'une session **en cours** (`.jsonl` en clair, puis compression à la fin ?).
- Hermes : qui écrit un message `user` dans une session `cli` ou `acp`. Aucun champ ne prouve que c'est Loïc, d'où `author = unknown` (C4).
- Hermes : ce qu'est une session `acp` (qui la mène, depuis quel client), et la `source` des sessions nées des runs de Nexus (board `nexus`, ADR-023 D7). Tant que ce n'est pas relevé, seule `cli` est lue (C5).
- Claude : la stabilité des champs `origin.kind` et `isMeta` d'une version à l'autre.

## 4. Modèle de données et migrations

### 4.1 Migration `0010_conversations` (PR 1)

Elle est réversible : `downgrade` supprime les déclencheurs, puis la table FTS, puis les tables. La sonde FTS5 passe **avant** toute création : sous SQLite, une table créée avant une instruction en échec reste en place. `author` n'a pas de CHECK, pour la même raison que `runs.model` dans `0009`.

**`conversations`** (référence `nx-conv-<n>`) :

La référence `nx-conv-<n>` est la poignée de la ligne d'index, pas l'identité de la session : celle-ci reste `claude-session:<id>`, `codex-session:<id>` ou `hermes-session:<id>` (DATA-MODEL §1), renvoyée par l'API dans `external_ref`. Après une purge puis une relecture, la même session reçoit une nouvelle poignée. DATA-MODEL §2.7 (qui ne prévoit `nx-conv-<n>` que pour une conversation native) est amendé en ce sens dans la PR 1.

| Colonne | Notes |
|---|---|
| `id` | entier, clé primaire `AUTOINCREMENT`, pour la même raison que les messages : une poignée purgée n'est jamais réattribuée à une autre conversation |
| `source` | `claude-code`, `codex` ou `hermes` (CHECK) |
| `external_id` | id de session à la source ; unique avec `source` |
| `channel` | Hermes : la `source` de la session (`cli` par défaut, C5) ; sinon `NULL` |
| `title` | masqué, 200 caractères au plus, `NULL` si absent |
| `workspace` | `cwd` masqué, 500 caractères au plus (filtre « projet ») |
| `git_branch` | masqué, 200 caractères au plus |
| `started_at`, `last_message_at` | `AwareDateTime` |
| `message_count` | entier, tenu à jour dans la transaction d'ingestion |
| `missing_since` | `AwareDateTime`, nul tant que la source existe (§6.6) |
| `measured_at` | dernière lecture réussie (provenance, DATA-MODEL §5) |

**`conversation_messages`** (référence `nx-msg-<n>`) :

| Colonne | Notes |
|---|---|
| `id` | entier, clé primaire `AUTOINCREMENT` : un id purgé n'est jamais réattribué, donc une clé étrangère périmée ne vise jamais un autre message |
| `conversation_id` | clé étrangère `ON DELETE CASCADE`, indexée avec `at` |
| `external_id` | Claude `uuid`, Codex `ordinal`, Hermes `messages.id` ; unique avec `conversation_id` |
| `role` | `user` ou `assistant` (CHECK) |
| `author` | `loic`, `claude`, `codex`, `helios`, `hermes` ou `unknown` (C4, ADR-005) |
| `at` | `AwareDateTime` |
| `body` | texte **masqué** (§7), de 1 à 16 000 caractères (CHECK) |
| `truncated` | booléen |
| `redacted` | booléen : le scanner a masqué au moins une valeur |
| `model` | Claude `message.model`, sinon `NULL` |

**`conversation_fts`** : table FTS5 à contenu externe (`content='conversation_messages'`, `content_rowid='id'`) sur `body`, `tokenize='unicode61 remove_diacritics 2'`. Trois déclencheurs (insertion, suppression, mise à jour) la tiennent à jour. La table FTS et ses tables d'ombre (`_data`, `_idx`, `_docsize`, `_config`) ne sont pas dans `Base.metadata` : `compare_metadata` les signalerait. Un filtre partagé `include_object` (exporté par `nexus/conversations/models.py`) les écarte, et il faut le passer aux **cinq tests de migration existants** (`test_actor_tokens_migration.py`, `test_approvals_migration.py`, `test_runs_migration.py`, `test_run_model_migration.py`, `test_task_follows_migration.py`), qui exigent un écart vide : sans lui, la PR 1 les casse. `test_run_model_migration.py` compare à `0009` et non à `head` : il doit aussi monter à `head` avant la comparaison. Le filtre retient un ensemble **exact** de cinq noms (la table FTS et ses quatre tables d'ombre), pas un préfixe, et il est aussi passé à `migrations/env.py`.

**`conversation_cursors`** (non exposée par l'API) :

| Colonne | Notes |
|---|---|
| `source`, `path_key` | clé primaire. `path_key` est le chemin **relatif** à la racine (`<slug>/<uuid>.jsonl`, `2026/11/03/rollout-….jsonl.zst`), ou `state.db` |
| `file_id` | identité du fichier, en **texte** `<st_dev>:<st_ino>` (sous Windows, `st_ino` est l'index de fichier NTFS, qui peut dépasser l'entier signé de 64 bits de SQLite) ; toujours lue par `os.lstat` (sous Windows, `DirEntry.stat()` rend 0 pour `st_ino`, `st_dev` et `st_nlink`) |
| `size`, `mtime_ns` | au dernier passage |
| `byte_offset` | (pas `offset`, mot réservé de SQL) octets consommés jusqu'à la dernière fin de ligne complète : octets du fichier (JSONL en clair) ou octets décompressés (`.zst`) |
| `head_sha256` | empreinte des 4 premiers Kio : détecte un fichier remplacé |
| `last_row_id` | Hermes : plus grand `messages.id` lu |
| `window_from_id` | Hermes : premier `messages.id` déjà couvert par la fenêtre (borne basse lue) ; nul pour les fichiers |
| `covered_since` | fichiers : seuil de rétention (`now - NEXUS_CONV_RETENTION_DAYS`, `AwareDateTime`) couvert par l'index pour ce fichier. Posé quand une lecture **commence** à 0 (le seuil sous lequel ses lignes sont jugées), gardé tel quel jusqu'à `ok` ou `too_large`, avancé par la purge (§6.6). Dans **tout** état (`partial`, `skipping`, `ok`, `too_large`), un seuil en vigueur plus ancien remet le curseur à 0 (§6.2) : un fichier ne passe jamais `ok` avec un seuil plus récent que celui de lignes déjà sautées |
| `session_external_id` | Codex : `session_meta.payload.id` lu au début du fichier, gardé pour rattacher les lignes lues après une reprise à `byte_offset` ; nul pour les autres sources |
| `state` | `partial` (lecture en cours), `skipping` (saut d'une ligne trop longue en cours, §6.2), `ok` (lu jusqu'au bout), `too_large`, `unreadable` ou `skipped_old` (CHECK) |
| `updated_at` | |

Le modèle SQLAlchemy vit dans `nexus/conversations/models.py`. `nexus/models.py` l'importe pour que `Base.metadata` le voie (migrations et `compare_metadata`).

**FTS5 est exigé.** Le Python du serveur (3.13, SQLite 3.53.1) l'a, vérifié. Au démarrage, une sonde (`CREATE VIRTUAL TABLE temp.x USING fts5(x)`) le contrôle. Sans FTS5, la migration échoue avec un message fixe « SQLite sans FTS5 » : c'est un échec fermé, à revoir pour le sidecar Tauri.

### 4.2 Migration `0011_task_origin_message` (PR 7)

Deux colonnes de `tasks`, ajoutées par `add_column(…, inline_references=True)`, sans mode batch, comme `0006` :

- `origin_message_id` : clé étrangère vers `conversation_messages.id`, `ON DELETE SET NULL`, indexée. Elle sert à la navigation et tombe à `NULL` si le message est purgé (§6.6).
- `origin_message_ref` : la référence **stable**, par exemple `claude-session:<session>/<uuid>`, `codex-session:<session>/<ordinal>` ou `hermes-session:<session>/<id>`. Préfixes de DATA-MODEL §2.7, et séparateur `/` de DATA-MODEL §1 (`telegram:<chat>/<msg>`), au lieu du `#` du premier jet. Elle est validée par une expression régulière et posée une fois, à la création. Elle **n'est pas** dans `UPDATABLE` : `tasks.origin`, lui, peut être réécrit par tout acteur (`PATCH`), donc la provenance n'y est pas confiée. Un test vérifie que le scanner laisse ces références intactes. Relevé du 2026-11-26 sur `master` : sur 3 000 références Claude et Codex tirées au hasard (UUID, ordinal), `redact` n'en a masqué aucune. La forme réelle d'un id de session Hermes n'est pas relevée : son test vient avec la PR 6.

## 5. Confinement des lecteurs (liste blanche)

### 5.1 Règles communes (`conversations/paths.py`)

1. **Aucune source n'est active par défaut** (C1). Chaque racine se règle explicitement : `NEXUS_CONV_CLAUDE_ROOT`, `NEXUS_CONV_CODEX_ROOT`, `NEXUS_CONV_HERMES_DB`. Sans valeur, la source est `disabled` et rien n'est ouvert. Il n'y a aucun repli sur `~`.
2. La racine doit être un chemin absolu ; pour Hermes, `state.db` doit en plus avoir `st_nlink == 1` (pas de lien physique). Elle est contrôlée **telle qu'elle est réglée, avant toute résolution** : dossier ordinaire (pour Hermes, un fichier ordinaire), sans lien ni point de jonction (attribut `FILE_ATTRIBUTE_REPARSE_POINT` sous Windows) ; le chemin résolu perd cet attribut, donc l'ordre inverse ne verrait jamais une jonction. Elle est ensuite résolue (`Path.resolve(strict=True)`). Contrôles de nom : la racine Claude doit s'appeler `projects`, la racine Codex `sessions`, la base Hermes `state.db`. Sinon Nexus refuse de démarrer la source, avec un message fixe qui ne recopie pas le chemin.
3. **L'énumération est à profondeur fixe, jamais récursive** (pas de `rglob`, pas de `os.walk`). On fait un `os.scandir` niveau par niveau, et seuls les noms qui correspondent **entièrement** à une expression du lecteur passent :
   - Claude : niveau 1 `^[A-Za-z0-9._-]{1,200}$` (dossier) ; niveau 2 `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$` (fichier) ;
   - Codex : `^\d{4}$` / `^\d{2}$` / `^\d{2}$` (dossiers) puis `^rollout-[0-9T:-]{10,40}-[0-9a-f-]{36}\.jsonl\.zst$` (fichier). Seule la forme compressée est admise (C7) ; `.jsonl` en clair s'ajoutera par une PR, après le relevé du §3.4.
   Avant chaque `os.scandir`, le dossier intermédiaire (Claude : `<slug>` ; Codex : `AAAA`, `MM`, `JJ`) passe par `os.lstat` : vrai dossier, ni `S_ISLNK` ni `FILE_ATTRIBUTE_REPARSE_POINT` (même contrôle que `is_link` de `adapters/run_commit_scan.py`), chemin résolu sous la racine résolue. Sous Windows, `DirEntry.is_dir(follow_symlinks=False)` rend vrai pour un point de jonction : il ne suffit donc pas. Un dossier qui échoue est sauté et compté, jamais parcouru.
   Un nom comme `auth.json`, `.credentials.json`, `config.toml` ou `*token*` ne peut donc pas passer, et un nom hors motif n'est jamais ouvert. Il n'y a **pas de liste de refus**.
4. Chaque candidat passe par `os.lstat` : fichier ordinaire, ni lien, ni point de réanalyse, `st_nlink == 1`, et chemin résolu sous la racine résolue (`is_relative_to`). L'ouverture se fait par `os.open(O_RDONLY | O_BINARY | O_NOINHERIT)` sous Windows, `os.open(O_RDONLY | O_NOFOLLOW | O_CLOEXEC)` ailleurs. Puis `os.fstat` doit redonner la même identité que le `lstat`, c'est-à-dire le même `(st_dev, st_ino)` : sous Windows, `st_ino` est l'index de fichier NTFS. C'est la parade contre une substitution entre les deux appels.
5. **Les descripteurs vivent peu** : une ouverture par fichier et par passe, fermée avant la transaction d'écriture. Sous Windows, un descripteur ouvert peut faire échouer le renommage ou la suppression que fait l'outil propriétaire ; le lecteur ne garde donc rien d'ouvert entre deux lectures.
6. Les journaux ne portent que la source, des comptes et un code d'erreur fixe : ni chemin, ni slug, ni id de session, ni contenu.

### 5.2 Codex : comment le lecteur reste hors des fichiers de connexion

La racine est `~/.codex/sessions`, jamais `~/.codex` (règle 2 : le nom doit être `sessions`). Le lecteur ne liste que quatre niveaux sous cette racine, avec les motifs de la règle 3. Il ne remonte jamais au parent : aucun `..`, et tout chemin résolu doit rester sous la racine résolue. `auth.json`, `config.toml` et `history.jsonl` sont dans le parent et ne sont jamais énumérés. Un test monte un faux `~/.codex` avec ces fichiers (contenu inventé et construit à l'exécution) et vérifie, en enregistrant chaque `os.open` et `os.scandir`, que **aucun** chemin du parent n'est touché.

### 5.3 Hermes : lecture SQLite en lecture seule

- Avant chaque passe, `state.db` et, s'ils existent, `state.db-wal` et `state.db-shm` repassent par `os.lstat` : fichier ordinaire, ni lien ni point de réanalyse, `st_nlink == 1`. Un échec rend la source `unavailable` pour cette passe. Connexion par URI construite avec `Path.as_uri()` puis `?mode=ro` (comme `backup.py` : un `?` ou un `#` du chemin ne peut pas ajouter de paramètre), puis `PRAGMA query_only=ON` et `busy_timeout=2000`. Une connexion par passe, fermée à la fin. Lectures en transactions courtes : 500 lignes au plus par requête, et aucune transaction ouverte pendant le masquage.
- SQLite ouvre lui-même `state.db-wal` et `state.db-shm`. En `mode=ro`, il n'écrit jamais `state.db` ; il peut mapper `-shm`. **À vérifier par un test** sur une base WAL construite à l'exécution, plutôt que posé en principe : le contenu et le `mtime` de `state.db` ne changent pas, aucun `-journal` n'apparaît et le `-wal` ne grossit pas. Si `-shm` manque et que le dossier est en lecture seule, l'ouverture échoue et la source passe `unavailable`, jamais `immutable=1` (lecture périmée).
- Requêtes à colonnes nommées (jamais `SELECT *`), sur `sessions` et `messages` seulement. Aucune autre table n'est citée par le code : `system_prompts`, `gateway_routing`, `delivery_obligations`, `telegram_*`, etc. restent hors de portée.
- Contrôle de schéma avant chaque passe : `PRAGMA table_info` doit contenir les colonnes du §3.3. Il manque une colonne → `incompatible`, plus rien n'est lu et rien n'est purgé. Une autre `schema_version` que 33 est seulement journalisée.
- Nexus ne tient aucune connexion entre deux passes. Les commandes de maintenance de Hermes (`set-journal-mode`, `optimize`, `repair`), qui exigent qu'aucun autre processus ne tienne la base, ne sont donc gênées que pendant une passe, quelques secondes au plus.

## 6. Ingestion

### 6.1 Boucle

- Une tâche `conversations_loop` dans le lifespan, à côté de `nodes_loop` et `backup_loop`. Chaque passe tourne dans `asyncio.to_thread`. Une seule passe à la fois (verrou du processus ; un seul processus serveur, ADR-021 D4). Pas de relance en parallèle.
- **Sondage, pas de surveillance de fichiers** (C2) : toutes les `NEXUS_CONV_POLL_SECONDS` (60 par défaut). Écartés : `watchdog` / `ReadDirectoryChangesW`, qui ajoutent une dépendance et des événements perdus ou doublés sous Windows ; il faudrait de toute façon un sondage de rattrapage.
- Budget par source et par passe : 8 Mio lus et 2 000 messages écrits. Le reste attend la passe suivante. Un premier remplissage de 200 Mo s'étale donc sur plusieurs passes sans bloquer la base.
- Fenêtre : un fichier dont le `mtime` est plus vieux que `NEXUS_CONV_SINCE_DAYS` (31 par défaut, C3) est noté `skipped_old` sans être ouvert. La fenêtre ne peut pas dépasser la rétention : `NEXUS_CONV_SINCE_DAYS > NEXUS_CONV_RETENTION_DAYS` fait refuser le démarrage, avec un message fixe. Les deux durées sont des entiers **de 1 à 3 650 jours**, et `NEXUS_CONV_POLL_SECONDS` un entier de **10 à 3 600** : une valeur nulle, négative, hors borne ou non entière fait refuser le démarrage, avec un message fixe qui nomme la variable sans recopier sa valeur (une rétention négative mettrait le seuil de purge dans le futur et viderait l'index ; un sondage nul ferait tourner la boucle sans pause). Pour Hermes, le curseur de départ est le premier `messages.id` dont le `timestamp` entre dans la fenêtre. Un message plus vieux que la rétention (§6.6) est sauté à l'ingestion, même dans un fichier récent : sinon il serait ingéré puis purgé à chaque relecture.

### 6.2 JSONL en clair (Claude ; plus tard Codex `.jsonl`, si le relevé l'admet)

- Le lecteur ouvre le fichier, se place à `byte_offset`, lit au plus le budget et découpe sur `\n`. **Seules les lignes complètes sont consommées.** Une dernière ligne sans `\n` (écriture en cours) n'avance pas `byte_offset` ; elle sera relue entière à la passe suivante.
- Une ligne de plus de 1 Mio est sautée en flux jusqu'au `\n` suivant, sans jamais la charger, et comptée `oversized`. Si le budget se termine au milieu d'une ligne trop longue, le curseur retient qu'un saut est en cours (`state = skipping`) et avance `byte_offset` jusqu'où il a lu : la passe suivante continue le saut jusqu'au `\n`, sans jamais relire le début. Une ligne plus grande que le budget d'une passe ne bloque donc jamais le fichier.
- Encodage : UTF-8 strict par ligne, BOM retiré en tête de fichier. Une ligne non décodable ou un JSON invalide est sauté et compté (`bad_lines`), sans arrêter le fichier.
- **Rotation et troncature** : `size < byte_offset`, un `file_id` changé ou un `head_sha256` différent remettent le curseur à 0. La relecture est idempotente (§6.4). Les messages qui n'existent plus dans le nouveau contenu restent jusqu'à la purge (§6.6).
- Fichier inchangé (`size`, `mtime_ns` et `file_id` égaux) dans l'état `ok` ou `too_large`, avec `covered_since` au plus égal au seuil de rétention en vigueur : non ouvert. Si `covered_since` est plus récent que ce seuil (rétention élargie, ou tranche purgée depuis), le fichier est relu depuis 0. Un curseur `skipped_old` est rejugé à chaque passe contre la fenêtre en vigueur : si le fichier y entre (fenêtre élargie), il est lu depuis 0. Pour Hermes, la passe calcule le premier `messages.id` de la fenêtre en vigueur : s'il est plus petit que `window_from_id` (fenêtre élargie), les messages de cet id jusqu'à `window_from_id` exclu sont lus en plus, sous le même budget, **par `messages.id` décroissant** (`id < window_from_id AND id >= <début> ORDER BY id DESC`). Chaque lot abaisse `window_from_id` au plus petit id lu, dans la même transaction que ses messages ; une fois la plage vide, il prend la valeur du début de la fenêtre. L'intervalle couvert `[window_from_id, last_row_id]` reste ainsi d'un seul tenant sur plusieurs passes et après un plantage, sans trou ni relecture sans fin ; sinon rien n'est relu. Les clés uniques rendent toute relecture idempotente.

### 6.3 Codex `.jsonl.zst`

- Nouvelle dépendance `zstandard` (C7) : le serveur exige Python ≥ 3.13, et `compression.zstd` n'existe qu'à partir de 3.14. Écartés : imposer Python 3.14 (toute la chaîne d'outils bouge pour un lecteur) et lancer `zstd.exe` (processus externe, absent sous Windows).
- Décompression **en flux** (`ZstdDecompressor().stream_reader`), lue ligne par ligne avec le même plafond de 1 Mio par ligne. Plafond de **256 Mio décompressés** par fichier : au-delà, la lecture s'arrête, ce qui a été lu est gardé et le curseur passe `too_large`. Un flux zstd invalide → `unreadable`. Rien n'est jamais décompressé sur le disque.
- Un `.zst` est traité comme immuable, mais il est lu **par morceaux** sous le même budget que le reste. Une ligne plus grande que le budget d'une passe suit la règle du §6.2 (`state = skipping`, `byte_offset` qui avance au milieu de la ligne) : les octets décompressés pour revenir à `byte_offset` ne comptent pas dans le budget de 8 Mio, mais tous les octets décompressés depuis 0 comptent dans le plafond de 256 Mio. `byte_offset` compte les octets décompressés consommés jusqu'à la dernière ligne complète, et l'état reste `partial` jusqu'à la fin du flux. À la passe suivante, un fichier inchangé est rouvert, décompressé en flux sans rien garder jusqu'à `byte_offset`, puis la lecture reprend. La fin du flux fait passer l'état à `ok`, et le fichier n'est plus ouvert. S'il change (`size`, `mtime_ns`, `file_id`), il repart de 0 ; les clés uniques rendent la relecture idempotente.
- La conversation a pour clé l'id de session (`session_meta.payload.id`), pas le chemin. Le curseur le garde (`session_external_id`) dès la première passe : une reprise à `byte_offset`, qui saute la ligne `session_meta`, rattache ses messages à la bonne conversation. Un fichier dont la première passe ne trouve pas `session_meta` avant le budget n'écrit aucun message et reste `partial` ; sans `session_meta` du tout, il passe `unreadable`. Le jour où la forme `.jsonl` sera admise, une session qui passe de `.jsonl` à `.jsonl.zst` gardera donc sa conversation.

### 6.4 Idempotence et transactions

- Écriture par lot de 500 messages au plus. Une seule transaction ajoute les messages (`INSERT … ON CONFLICT(conversation_id, external_id) DO NOTHING`), met la conversation à jour (`last_message_at`, `message_count`, `measured_at`) et avance le curseur. Après un plantage entre deux lots, la passe suivante repart de l'ancien curseur, sans doublon ni trou.
- `message_count` est recalculé par `COUNT(*)` dans la même transaction, jamais incrémenté à l'aveugle.
- Les écritures passent par la session SQLAlchemy de l'application (WAL, `busy_timeout`). Chaque lot est court, pour qu'une écriture de l'API n'attende que quelques millisecondes.

### 6.5 Extraction par source (fonctions pures, testées sur fixtures)

- **Claude** : on garde `type ∈ {user, assistant}`, `isSidechain` faux et `isMeta` différent de vrai. Pour `user` : le contenu est une chaîne, ou une liste sans `tool_result` dont on prend les blocs `text`. `author = loic` si `origin.kind == "human"`, `unknown` si `origin` est absent, et la ligne est **sautée** pour toute autre valeur (`task-notification`…) (C4). Pour `assistant` : les blocs `text` seulement, `author = claude`, `model` gardé. Une ligne sans texte après filtrage est sautée. Les titres viennent de `custom-title`, puis `ai-title`.
- **Codex** : `response_item` / `message`, rôles `user` et `assistant`, blocs `input_text` et `output_text`. `author` vaut `unknown` pour `user` (le format ne distingue pas Loïc d'un texte injecté) et `codex` pour `assistant`. On saute un message `user` qui commence par un préfixe injecté connu. La liste est fermée et testée ; ses valeurs sont relevées dans la PR 3 (§3.4), et elle s'étend par PR.
- **Hermes** : `sessions.source ∈ NEXUS_CONV_HERMES_SOURCES` (par défaut `cli`, C5), `chat_type` vide (`NULL` ou `''`) ou `dm`, `archived` et `hidden` nuls (`COALESCE(…, 0) = 0`). Messages : `role ∈ {user, assistant}`, `display_kind` vide (`COALESCE(display_kind, '') = ''`), `COALESCE(_compressed_summary, 0) = 0`, contenu non vide (`substr(content, 1, 65536)` en SQL : une borne de lecture, masquée entière puis coupée à 16 000 caractères avec `truncated`, §7.1). `author` vaut `unknown` pour `user` (§3.4). Pour `assistant`, il vaut `helios` si `profile_name` égale le profil réglé pour Helios (`NEXUS_HERMES_PROFILE`, `default` par défaut, comme l'adaptateur Hermes, addendum d'ADR-023 du 2026-11-11), et `hermes` sinon. Les messages compactés par Hermes sont gardés : c'est de l'historique réel. La colonne `active` qui les signale n'est pas lue.
- Un type ou un champ inconnu est ignoré. Un champ requis manquant fait sauter la ligne (`bad_lines`). Une source dont la moitié des lignes d'une passe sont `bad_lines` passe `degraded` dans son état (§8), signal d'un changement de format.

### 6.6 Disparition, rétention, purge

- Une session n'est comptée absente qu'après une énumération **complète et réussie** de sa source. Une racine illisible, une source `unavailable`, `incompatible` ou `degraded`, ou une passe interrompue ne marquent rien. Après deux telles passes sans la session, elle reçoit `missing_since`. Après **24 h** d'absence, elle est supprimée de l'index (C8), messages et FTS compris. Un fichier renommé ou compressé dans l'intervalle retrouve sa conversation par l'id de session. Pour Hermes, la liste des sessions est comparée une fois par heure.
- Une source désactivée (réglage retiré) voit son index purgé à la purge quotidienne suivante. C'est réversible : réactiver la source la fait relire.
- **Rétention** `NEXUS_CONV_RETENTION_DAYS` (31 par défaut, C3) : une purge quotidienne supprime les messages plus vieux, puis les conversations vides. C'est réversible : élargir la rétention fait relire la source. La purge avance `covered_since = max(covered_since, seuil de purge)` sur chaque curseur de fichier, et, pour Hermes, remonte `window_from_id` au plus petit id restant (`MIN(CAST(external_id AS INTEGER))` des messages Hermes conservés), ou à `last_row_id + 1` s'il n'en reste aucun. Un élargissement ultérieur relit donc la tranche purgée : un fichier inchangé depuis 0 dès que la rétention s'élargit ; Hermes par le rattrapage décroissant du §6.2, qui suit la fenêtre (`NEXUS_CONV_SINCE_DAYS`) : comme pour un fichier `skipped_old`, il faut élargir la fenêtre aussi, pas seulement la rétention. Les clés uniques rendent la relecture idempotente.
- La purge tourne avec `PRAGMA secure_delete=ON` sur sa connexion : le texte supprimé ne reste pas dans les pages libres. Deux compléments, ajoutés par l'agent et à vérifier par un test en PR 2 (la portée de `secure_delete` par connexion et les fusions de segments FTS faites par la connexion d'ingestion peuvent le contredire). D'abord, une suppression dans une FTS5 à contenu externe n'ajoute que des marques d'effacement : les termes restent dans les anciens segments jusqu'à leur fusion. La purge finit donc par `INSERT INTO conversation_fts(conversation_fts) VALUES('optimize')`. Ensuite, les anciennes pages restent dans `nexus.db-wal` jusqu'au point de contrôle : la purge le force par `PRAGMA wal_checkpoint(TRUNCATE)`. S'il ne peut pas aboutir (`busy`), on le note, et il est retenté à la purge suivante.
- Les tâches liées gardent `origin_message_ref`, et `origin_message_id` passe à `NULL`. La connexion de purge exige `PRAGMA foreign_keys=ON` ; un test vérifie la mise à `NULL`.

## 7. Secrets et vie privée

### 7.1 Masquage

- Chaque `body`, `title`, `workspace` et `git_branch` passe par `nexus.secrets.redact` **avant** de quitter la fonction d'extraction, et le masquage précède toute coupe : le texte est masqué entier (dans la borne de lecture de 1 Mio par ligne), puis coupé à sa longueur maximale sans entamer une marque de masquage, avec `truncated` (pour `body`). Une coupe avant le masquage pourrait couper un secret en deux et le laisser passer, ou faire dépasser au texte masqué le CHECK de longueur. Le type `ParsedMessage` ne se construit que par une fabrique qui masque : aucun chemin de code n'écrit un texte brut. Les caractères de contrôle de `snippet()` (`\x02`, `\x03`) sont retirés du texte avant le masquage.
- La FTS n'indexe que le texte masqué. Chercher `ghp_` ne retrouve donc jamais un secret, et un extrait de recherche ne peut pas en montrer.
- Les sorties d'outils, qui portent le plus de secrets (fichiers lus, `env`, journaux), ne sont jamais lues (§2).
- **Mesure d'abord (PR 2, condition d'arrêt)** : débit de `redact` et taux de sur-masquage sur 20 Mo de texte synthétique (prose française et anglaise, chemins, UUID, SHA, blocs de code). Relevé du 2026-11-25 : un SHA de 40 caractères est masqué en entier, et un UUID ou une référence de provenance ne le sont pas. Seuils : au moins 2 Mo/s sur la machine de Loïc, et au plus 1 message sur 20 masqué sans secret semé. Au-delà, on s'arrête et on tranche avant d'aller plus loin (bornes de longueur, ou masquage en différé hors de la boucle).
- Limites connues du scanner (SECURITY §1, environ 2,5 % de clés à barres obliques laissées entières) : elles s'appliquent ici telles quelles. SECURITY les recopie pour les conversations.

### 7.2 Ce qui est stocké, ce qui est référencé

- Stocké (masqué) : le texte des messages humains et des réponses des modèles, le titre, le dossier de travail et la branche.
- Référencé seulement : le fichier ou la base source (par `path_key` relatif, dans `conversation_cursors`, jamais renvoyé par l'API).
- Jamais lu ni stocké : tout ce que listent §3 et §2, les identifiants de compte et les invites système.
- **Classification « Sensible »** (SECURITY §2) : les messages privés de Loïc à ses modèles sont copiés dans `nexus.db`. Ils restent en local, ne sont jamais exportés, ne passent jamais sur le WebSocket et ne sont lisibles que par un humain (§8).

### 7.3 Sauvegardes

Les sauvegardes de `nexus.db` (14 par défaut, `NEXUS_BACKUP_KEEP`) garderaient des conversations au-delà de leur purge. L'index étant reconstructible, **la sauvegarde l'en retire** (C9) : après la copie par l'API `backup` de SQLite, `backup.py` ouvre la copie (`.partial`) avec `PRAGMA journal_mode=MEMORY` (un plantage pendant le retrait ne laisse ni `-wal` ni `-shm` à côté d'elle), `foreign_keys=ON` et `secure_delete=ON`. Il met `tasks.origin_message_id` à `NULL` (explicitement, à partir de la PR 7), vide `conversation_messages`, `conversations` et `conversation_cursors`, reconstruit la FTS vide, valide la transaction (sinon `VACUUM` échoue), fait un `VACUUM` et ferme la connexion (sous Windows, la copie ne peut pas être effacée tant qu'elle est ouverte), avant la publication et la rotation. Le retrait tolère un schéma plus ancien. Le lifespan sauvegarde la base **avant** de la migrer (`app.py`) : la copie faite avant `0010` n'a pas les tables, et celle faite avant `0011` n'a pas `tasks.origin_message_id`. Chaque étape vérifie donc d'abord que la table ou la colonne existe (`sqlite_master`, `PRAGMA table_info`), et une absence n'est pas une erreur. Un échec du retrait fait échouer la sauvegarde (la copie partielle est effacée), jamais publier une copie qui garderait l'index. Un arrêt brutal entre la copie et la fin du retrait laisserait un `*.partial` qui contient l'index : au démarrage, avant la première sauvegarde, `backup.py` efface tout `*.partial` (et ses `-wal`, `-shm`, `-journal`) du dossier des sauvegardes. Test : un `.partial` semé avant le démarrage a disparu après lui. Une restauration relit les sources. Les tâches gardent `origin_message_ref` ; `AUTOINCREMENT` garantit qu'aucun nouvel id ne reprend un ancien. Test : une sauvegarde faite après ingestion ne contient aucun octet d'un corps de message semé.

## 8. API (ADR-020, ADR-017)

Toutes les routes exigent un jeton. **Lecture et création de tâche réservées aux humains** (C10) : 403 `human_only` pour tout agent, contrôlé avant toute lecture (`permissions.check_conversations`, fonction pure). Cela amende la matrice de SECURITY §3, où « Lire » valait pour tous les acteurs authentifiés. Chaque réponse porte `source` et `measured_at`. Une erreur ne recopie aucune valeur reçue.

| Route | Rôle |
|---|---|
| `GET /api/conversations?source=&workspace=&before=&limit=` | liste triée par `last_message_at` décroissant, pagination par curseur opaque (`last_message_at`, `id`), `limit` ≤ 100 |
| `GET /api/conversations/{nx-conv-n}` | métadonnées, dont `external_ref` (§4.1) |
| `GET /api/conversations/{nx-conv-n}/messages?after=&limit=` | messages par `at`, `id` croissants, `limit` ≤ 200 |
| `GET /api/conversations/search?q=&source=&limit=` | résultats : `message`, `conversation`, `snippet`, `at`, `author`, rang bm25 ; `limit` ≤ 50. La route est déclarée **avant** `/{nx-conv-n}`, sinon FastAPI lit `search` comme une référence |
| `GET /api/conversation-sources` | par source : `enabled`, `state` (`disabled`, `ok`, `degraded`, `incompatible`, `unavailable`), `last_pass_at`, comptes, dernier code d'erreur ; **aucun chemin** |
| `POST /api/conversations/messages/{nx-msg-n}/tasks` | crée une tâche (PR 7, §9) |

Recherche :

- `q` fait 200 caractères au plus et 8 termes au plus. Chaque terme est mis entre guillemets comme une phrase FTS (guillemets internes doublés), les termes sont joints par `AND`, avec un `*` de préfixe sur le dernier terme d'au moins 3 caractères.
- La syntaxe FTS brute n'est jamais transmise, pour qu'une requête mal formée ne puisse pas lever une erreur 500. `q` vide → 422.
- Écarté : chercher à la demande dans les fichiers (C11). Une requête devrait relire 400 Mo, décompresser du zstd et masquer chaque passage, ce qui coûte des secondes. Elle verrait aussi les secrets bruts avant le masquage, et rouvrirait des fichiers de Loïc à chaque frappe.
- Écarté aussi : un tokenizer `trigram`, qui donne un index environ trois fois plus gros pour un besoin de sous-chaîne non exprimé.

## 9. Créer une tâche depuis un message (PR 7)

- `POST …/messages/{ref}/tasks` reçoit `title` et `objective` (obligatoires, comme `TaskCreate` : la création existante refuse un objectif vide, `objective_required`, et `tasks.objective` est `NOT NULL`) et `next_action`, `priority` (facultatifs), tous saisis par Loïc. **Rien du corps du message n'est recopié d'office** (C12). Les tâches sont lisibles par tous les agents et nourrissent les briefs envoyés aux fournisseurs de modèles (ADR-023 D4). L'interface montre le message à côté du formulaire, et Loïc recopie lui-même ce qu'il veut partager.
- Le serveur pose `origin_message_ref` et `origin_message_id` (§4.2), et `origin` à la même référence pour l'affichage existant, puis passe par la création de tâche existante (mêmes validations, masquage, `created_by` = l'acteur du jeton). Le code vit dans `conversations/to_task.py` : `tasks/service.py` fait déjà 397 lignes et ne grossit pas.
- Plusieurs tâches peuvent naître du même message. Le bouton est désactivé pendant la requête ; aucune contrainte d'unicité n'est posée.
- Le panneau de la tâche affiche « Née de » avec un lien vers le message, ou la référence seule si le message a été purgé.

## 10. Interface (ADR-017)

- Tout passe par l'API : aucun accès au disque ni API propre au navigateur. Fichiers dans `web/src/conversations/` : `ConversationsView.tsx` (liste + filtres source/projet), `ConversationThread.tsx`, `ConversationSearch.tsx`, `CreateTaskFromMessage.tsx`, `conversationsApi.ts`. Entrée « Conversations » dans la navigation.
- Le texte est affiché en clair, jamais par `dangerouslySetInnerHTML`. Les extraits sont découpés sur `\x02` et `\x03` et rendus en `<mark>` par React.
- Données qui changent (checklist §6) : la liste se recharge toutes les 60 s quand la vue est visible, en gardant la sélection et la position de défilement. Un fil ouvert n'ajoute qu'en fin de liste (`after`). Chaque conversation affiche « lu il y a … » (`measured_at`). Les états `disabled`, `degraded`, `incompatible` et `unavailable` d'une source s'affichent en clair.
- Libellés en français. L'auteur `unknown` s'affiche « auteur non vérifié ».

## 11. Découpage en PR

Chaque PR part de `master` à jour, sur une branche à elle, et ne dépend d'aucune PR ouverte. Elles se fusionnent dans l'ordre. Passent par `architect` avant `implementer` (AGENTS.md, « Model routing ») : les PR 1 et 7 (migrations), la PR 2 (secrets, concurrence de l'ingestion), la PR 4 (permissions) et la PR 6 (base vivante d'un autre outil).

| PR | Branche | Contenu | Docs mises à jour |
|---|---|---|---|
| 0 | `docs/<n>-conversations-lot1` | ce cadrage, issue, ADR-025 « Conversations, lot 1 » (C1 à C16) | DECISIONS |
| 1 | `feat/<n>-conversations-modele` | migration `0010`, modèles, sonde FTS5, réglages (toutes sources `disabled`), `paths.py`, sauvegarde qui retire l'index (§7.3) | DATA-MODEL §2.7, §2.8 et §6 |
| 2 | `feat/<n>-conversations-claude` | **mesure de `redact` d'abord** (§7.1), `jsonl_tail.py`, `parse_claude.py`, `ingest.py`, `retention.py`, boucle du lifespan | INTEGRATIONS §3 |
| 3 | `feat/<n>-conversations-codex` | dépendance `zstandard`, `parse_codex.py` | INTEGRATIONS §3 |
| 4 | `feat/<n>-conversations-api` | routes de lecture et de recherche, `permissions.check_conversations`, `conversation-sources` | SECURITY §2 et §3 |
| 5 | `feat/<n>-conversations-vue` | vue, fil, recherche, e2e Playwright sur serveur alimenté par de fausses sessions | VIEWS §3 |
| 6 | `feat/<n>-conversations-hermes` | `read_hermes.py`, réglage des sources Hermes | INTEGRATIONS §3, SECURITY |
| 7 | `feat/<n>-tache-depuis-message` | migration `0011`, `to_task.py`, dialogue, « Née de » dans la tâche | DATA-MODEL §2.4 |

Hermes vient en dernier parmi les sources (C13) : c'est la base vivante d'un autre outil, déjà réparée plusieurs fois. Les lots 1 à 5 livrent la vue sans elle.

## 12. Choix pris sous la délégation (confirmés le 2026-11-26)

Règle appliquée à chaque choix (ADR-024) : quand il touche aux données de Loïc, on prend l'option la plus restreinte et la plus réversible. Chaque choix est repris dans ADR-025. Le fil principal les a confirmés le 2026-11-26.

- **C1** : aucune source n'est active par défaut. Chaque racine se règle explicitement, sans repli sur `~` ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : rien n'est lu chez Loïc sans un réglage qu'il voit, et retirer le réglage suffit à tout arrêter.
- **C2** : sondage toutes les 60 s (`NEXUS_CONV_POLL_SECONDS`), pas de surveillance du système de fichiers ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : aucune dépendance ni descripteur tenu ouvert chez les outils de Loïc, et le sondage de rattrapage serait nécessaire de toute façon.
- **C3** (resserré le 2026-11-26 ; avant : fenêtre de 30 jours, rétention de 90) : la fenêtre d'ingestion et la rétention valent toutes deux **31 jours**. Elles sont réglables, et la fenêtre ne peut pas dépasser la rétention. Contrepartie : rien de plus vieux qu'un mois n'est cherchable, et « Née de » (§9) retombe sur la référence seule après 31 jours au lieu de 90 ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : 31 jours sont le minimum qui couvre « le mois écoulé » du critère de fin, et élargir le réglage fait relire la source.
- **C4** : `author = loic` seulement si la source le prouve (Claude `origin.kind = human`). Sinon `unknown` (ADR-005), Hermes et Codex compris. Les notifications de tâches Claude sont sautées ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : on n'attribue jamais à Loïc un texte qu'un outil a pu injecter.
- **C5** (resserré le 2026-11-26 ; avant : `cli` et `acp`) : Hermes est limité à la source `cli`, en `dm` ou sans type. `acp`, `telegram`, `group`, `cron`, `oneshot` et `kanban` sont exclus. La liste se règle sans migration (`NEXUS_CONV_HERMES_SOURCES`) ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : seule `cli` est, à coup sûr, une session que Loïc mène lui-même au terminal. Rien dans le dépôt ne dit ce qu'est une session `acp`, ni sous quelle source s'écrivent les runs de Nexus. `acp` s'ouvrira par le réglage, après un relevé fait sur des comptes seulement (PR 6, §3.4).
- **C6** : Hermes est lu en SQLite `mode=ro` + `query_only`, à colonnes nommées, et pas par `hermes sessions export` ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : aucune écriture chez Hermes, et aucune commande dont une erreur d'argument publierait ou supprimerait une session.
- **C7** (resserré le 2026-11-26 ; avant : le motif admettait aussi `.jsonl` en clair) : dépendance `zstandard`, décompression en flux, plafond de 256 Mio décompressés par fichier, et seuls les fichiers `.jsonl.zst` sont admis ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : la liste blanche n'admet que la forme vue sur la machine (87 fichiers sur 87). La forme en clair s'ajoutera par une PR, après un relevé.
- **C8** : une session disparue à la source est retirée de l'index après 24 h d'absence, et seulement après des énumérations complètes ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : ce que Loïc a supprimé chez l'outil ne survit pas dans Nexus, et une session qui revient est relue.
- **C9** : les sauvegardes de `nexus.db` ne contiennent pas l'index des conversations. Le retrait tolère les schémas antérieurs à `0010` et `0011` ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : l'index est reconstructible ; le garder dans 14 copies prolongerait la vie de messages privés au-delà de leur purge.
- **C10** : la lecture et la création de tâche sont réservées aux humains (cela amende la matrice de SECURITY §3), et aucun événement WebSocket n'est émis ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : les messages privés de Loïc ne vont à aucun agent. L'accès s'ouvrira par un amendement, s'il le faut.
- **C11** : recherche FTS5 `unicode61 remove_diacritics 2` dans `nexus.db`, sur le texte masqué. La purge optimise la FTS et force le point de contrôle du WAL ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : aucun fichier de Loïc n'est rouvert à chaque recherche, et l'index ne voit jamais un secret brut. `trigram` (index trois fois plus gros) et la recherche à la demande dans les fichiers ont été écartés.
- **C12** : une tâche née d'un message ne recopie rien du message d'office ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : les tâches sont lues par les agents et nourrissent leurs briefs. Seul ce que Loïc recopie lui-même en sort.
- **C13** : Hermes est la dernière source livrée (PR 6) ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : c'est la base vivante d'un autre outil, déjà réparée plusieurs fois. Elle vient une fois les lecteurs de fichiers éprouvés, et son report ne bloque pas la vue.
- **C14** : seuls le texte humain et les réponses des modèles sont gardés : aucun outil, raisonnement, invite système ni subagent ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : on garde le minimum qui répond au besoin, et on laisse de côté les sorties d'outils, qui portent le plus de secrets.
- **C15** : plafonds de 1 Mio par ligne lue, de 16 000 caractères stockés par message, et de 8 Mio et 2 000 messages par source et par passe ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : la mémoire reste bornée, la base n'est jamais bloquée longtemps, et un message coupé est signalé (`truncated`).
- **C16** : liste blanche de chemins à profondeur fixe, noms en motif complet, aucune liste de refus ; choisi par l'agent sous la délégation totale de Loïc du 2026-11-25. Raison : un fichier de connexion ne peut pas être ouvert par oubli d'une règle, puisque seul ce qui correspond au motif est ouvert.

## 13. Tests à écrire d'abord

Aucun vrai fichier de Loïc n'entre en CI. `tests/conversations_support.py` construit à l'exécution, sous `tmp_path`, de fausses racines `projects/`, `sessions/` et une fausse `state.db` en WAL, au contenu inventé. Les secrets synthétiques sont construits à l'exécution (`"ghp_" + "A" * 36`, `"nxt_" + …`). Les tests suivent la convention plate du dépôt : `tests/test_conversations_*.py`.

- **Confinement** (`test_conversations_paths.py`) : un faux `~/.codex` avec `auth.json`, `config.toml` et `history.jsonl` à côté de `sessions/`, et un faux `.claude` avec `.credentials.json`. On enregistre chaque `os.open` et `os.scandir` : aucun chemin hors motif n'est touché. On refuse aussi un lien symbolique ou un point de jonction vers l'extérieur, un lien physique, un nom au mauvais niveau, une racine mal nommée (`.codex` au lieu de `sessions`), une racine qui est un lien, la substitution d'un fichier entre `lstat` et `open`, et un dossier **intermédiaire** (`<slug>`, `AAAA`, `MM`, `JJ`) qui est un lien ou un point de jonction vers l'extérieur : jamais parcouru, aucun `os.scandir` hors de la racine.
- **Lecture JSONL** : dernière ligne partielle puis complétée ; ligne de 2 Mio sautée, y compris à cheval sur le budget ; ligne plus grande que le budget d'une passe (9 Mio pour un budget de 8 Mio) : état `skipping`, `byte_offset` qui avance à chaque passe, lignes suivantes lues, jamais de blocage ; curseur `skipped_old` relu depuis 0 quand la fenêtre est élargie, et fichier `ok` inchangé jamais rouvert ; UTF-8 invalide ; BOM ; JSON invalide ; troncature (`size < byte_offset`) ; remplacement de même taille (`head_sha256`) ; fichier inchangé jamais ouvert ; budget atteint et reprise à la passe suivante.
- **Codex zstd** : flux en plusieurs trames ; gros `.zst` lu en plusieurs passes sous le budget, reprise à `byte_offset` puis état `ok` ; flux corrompu → `unreadable` ; bombe (petit `.zst` qui dépasse 256 Mio décompressés) arrêtée sans tout charger en mémoire ; un `rollout-….jsonl` en clair jamais ouvert (C7) ; une session de plus de 2 000 messages lue en plusieurs passes garde une seule conversation (`session_external_id`) ; une ligne de 9 Mio dans un `.zst` (budget de 8 Mio) passée en `skipping` sans blocage, la reprise ne comptant pas dans le budget ; même id de session dans deux fichiers → une seule conversation ; préfixes injectés sautés.
- **Extraction** : lignes `tool_result`, `isMeta`, `task-notification`, `isSidechain`, `api-request-blob`, `session-owner` et `toolUseResult` jamais stockées. On vérifie par l'absence en base des marqueurs semés dans ces champs.
- **Hermes** : la base WAL de test est la même avant et après une passe (octets et `mtime`, pas de `-journal`) ; `state.db` en lien physique (`st_nlink == 2`), ou `-wal` remplacé par un lien entre deux passes → `unavailable` ; chemin contenant `?` et `#` ouvert sans paramètre ajouté (URI par `Path.as_uri()`) ; fenêtre élargie → les messages entre le début de la nouvelle fenêtre et `window_from_id` lus une fois, puis `window_from_id` abaissé ; rattrapage plus grand que le budget d'une passe (5 000 messages pour 2 000 par passe) fini en trois passes, sans trou ni doublon, y compris après une exception entre deux lots ; fenêtre inchangée → rien de relu à la passe suivante ; colonne manquante → `incompatible` sans purge ; sources et `chat_type` exclus (`acp` et `kanban` compris, par défaut) ; `display_kind`, `chat_type` et `_compressed_summary` à `NULL` comme à `''` ou `0` ; auteur `helios` pour le profil de `NEXUS_HERMES_PROFILE` et `hermes` pour un autre ; curseur `last_row_id` ; une écriture concurrente de la fausse « Hermes » pendant la passe ne casse rien ; `redact` laisse intacte une `origin_message_ref` Hermes de la forme réelle relevée (§4.2).
- **Idempotence et crash** : deux passes donnent le même état ; une exception entre deux lots → aucun doublon ni trou au redémarrage ; `message_count` exact.
- **Secrets** : un secret placé à cheval sur la 16 000ᵉ position est masqué entier (masquage avant la coupe), le corps stocké respecte le CHECK de longueur, avec `truncated` ; un `git_branch` qui contient un secret est masqué ; après ingestion de messages qui contiennent des secrets semés, ni `nexus.db` ni son `-wal` (octets bruts) ne les contiennent, et la recherche du préfixe ne rend aucun résultat. Une sauvegarde ne contient aucun corps de message. La sauvegarde d'une base à `0009` (avant `0010`) et d'une base à `0010` (avant `0011`) réussit, sans retrait à faire ou avec un retrait partiel. Un échec du retrait ne publie aucune copie.
- **Purge** : `missing_since`, puis suppression après 24 h ; racine illisible ou passe interrompue → rien n'est marqué absent ; source désactivée purgée ; message plus vieux que la rétention jamais ingéré ; rétention ; `NEXUS_CONV_SINCE_DAYS` plus grand que la rétention refusé au démarrage ; durées à 0, négatives ou non entières, sondage à 0 ou négatif, refusés sans recopier la valeur ; rétention élargie pendant la lecture d'un fichier `partial` → relu depuis 0 avant de passer `ok` ; rétention élargie après une purge → un fichier `ok` inchangé est relu et ses messages purgés reviennent, y compris quand seule la rétention change (fenêtre inchangée) ; un message Hermes purgé revient par le rattrapage quand la fenêtre et la rétention s'élargissent, pas quand seule la rétention change ; une purge qui vide Hermes met `window_from_id` à `last_row_id + 1` ; un `.zst` `too_large` inchangé n'est jamais redécompressé ; après purge, un terme propre au message purgé n'apparaît plus dans les octets bruts de `nexus.db` ni de son `-wal` (FTS `optimize`, point de contrôle) ; FTS cohérente (`INSERT INTO conversation_fts(conversation_fts) VALUES('integrity-check')`) ; une tâche liée garde `origin_message_ref` et voit `origin_message_id` passer à `NULL` (en base et dans une sauvegarde) ; `PATCH` ne peut pas changer `origin_message_ref`.
- **API** : 401 sans jeton ; 403 `human_only` pour `helios` et `codex` sur chaque route ; bornes de `limit` et de `q` ; requête FTS hostile (`"`, `NEAR(`, `*`, `-`, `:`) jamais en 500 ; `GET /api/conversations/search` qui n'est pas pris pour une référence ; une poignée `nx-conv-<n>` purgée qui donne 404, jamais une autre conversation ; aucun chemin dans `conversation-sources`.
- **Migration** : montée et descente ; `compare_metadata` sans écart, la FTS filtrée, dans le test de `0010` comme dans les cinq tests de migration existants.
- **Web** : rendu d'un message contenant du HTML (affiché comme texte) ; extraits marqués ; rechargement qui garde la sélection ; états de source ; dialogue de tâche sans pré-remplissage du corps, `objective` absent ou vide refusé par l'API comme par la création existante (`TaskCreate`, `objective_required`) ; e2e de bout en bout.

## 14. Fichiers et tailles (seuils de 400 et 600 lignes)

Prévus, avec une estimation de lignes (le détail de la PR 1 est dans son plan) : `nexus/conversations/models.py` (~90), `paths.py` (~170), `jsonl_tail.py` (~160), `parse_claude.py` (~130), `parse_codex.py` (~150), `read_hermes.py` (~190), `ingest.py` (~260), `retention.py` (~100), `search.py` (~110), `api.py` (~260), `to_task.py` (~110) ; migrations `0010` (~110) et `0011` (~40). Fichiers existants touchés à la marge : `config.py` (210 → ~240), `app.py` (253 → ~265), `backup.py` (66 → ~110), `permissions.py` (87 → ~100), `models.py` (274, +2), et les cinq tests de migration existants (le filtre `include_object`, §4.1). Aucun fichier listé dans `file-size-baseline.json` ne grossit. Un fichier de test par sujet, en dessous de 600 lignes.

## 15. Conditions d'arrêt

1. La mesure de `redact` (PR 2) dépasse un seuil du §7.1.
2. Le test du §5.3 montre que `mode=ro` modifie `state.db` ou fait grossir son `-wal` sur une base WAL réelle : Hermes est alors reporté. On n'invente pas de copie de la base.
3. Une session Codex en cours apparaît sous une forme non prévue : un `.zst` qui grossit en place, par exemple. Le lecteur Codex se limite alors aux fichiers vieux de plus de 10 minutes, jusqu'à un relevé. Une forme `.jsonl` en clair, elle, n'est pas un arrêt : le motif l'ignore (C7), et son admission passe par un relevé puis une PR.
4. Un format change au point que plus de la moitié des lignes d'une source sont rejetées sur une semaine : la source passe `degraded`, et un relevé suit avant toute correction.

## 16. Corrections du fil principal (2026-11-26)

Relecture du cadrage et du plan de la PR 1 contre le code et SQLite. Repris ci-dessus : le test `test_run_model_migration.py` qui compare à `0009` (§4.1) ; le contrôle de lien avant la résolution, et une racine relative refusée (§5.1) ; la sonde FTS5 en tête de migration ; la copie de sauvegarde en `journal_mode=MEMORY`, la validation avant `VACUUM` et la fermeture avant l'effacement (§7.3) ; `file_id` en texte, lu par `os.lstat` ; la colonne `byte_offset` ; un filtre à noms exacts, passé aussi à `migrations/env.py` ; des CHECK sur `state` et sur la longueur de `body`, aucun sur `author`. Le réglage `NEXUS_CONV_HERMES_SOURCES` arrive avec la PR 6 (§11), pas avant. Reportés : l'écho des valeurs numériques reçues par les réglages existants (issue à part) ; la nullité de `started_at` et `last_message_at`, et l'ordre des nuls, avec l'API (PR 4). Relecture Antigravity de la PR 0 (2026-11-26), reprise aussi : dossiers intermédiaires contrôlés avant leur parcours ; `git_branch` masqué ; masquage avant toute coupe ; `objective` obligatoire ; saut d'une ligne plus grande que le budget sans blocage (`skipping`) ; `skipped_old` rejugé contre la fenêtre ; `state.db` et ses fichiers WAL recontrôlés à chaque passe, URI par `Path.as_uri()`. Deuxième relecture : `skipping` aussi pour les `.zst` (§6.3) ; borne `window_from_id` du curseur Hermes, pour élargir la fenêtre sans tout relire à chaque passe. Troisième relecture : rattrapage d'une fenêtre élargie par id décroissant. Relecture de Codex : bornes des durées et du sondage ; `covered_since` pour relire un fichier inchangé quand la fenêtre s'élargit. Cinquième relecture : `covered_since` suit le seuil de rétention, posé aussi pour `too_large` et avancé par la purge ; `byte_offset` partout. Sixième relecture : purge Hermes et `window_from_id` (plus petit id restant, ou `last_row_id + 1`), élargissement de la fenêtre exigé pour Hermes ; derniers `offset`. Relecture CodeRabbit : `covered_since` fixé au début de la lecture et contrôlé dans tout état ; `session_external_id` pour les reprises Codex ; `*.partial` effacés au démarrage.
