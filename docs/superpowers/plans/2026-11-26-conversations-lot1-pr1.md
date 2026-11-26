# Conversations, lot 1 — PR 1 : modèle, migration `0010`, sonde FTS5, réglages, `paths.py`, sauvegarde sans l'index — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** poser tout ce dont les lecteurs des PR 2 à 7 ont besoin, sans rien lire chez Loïc. La PR 1 apporte les trois tables et la FTS5 de `0010`, leurs modèles, le filtre `include_object` (tests de migration et `env.py`), la sonde FTS5 et les réglages (toutes sources `disabled`, durées bornées). Elle apporte aussi le confinement des chemins (`paths.py`, sans consommateur pour l'instant), une sauvegarde qui retire l'index de chaque copie, et l'effacement au démarrage des copies `*.partial` laissées par un arrêt brutal.

**Architecture :** nouveau paquet `server/src/nexus/conversations/` (`__init__.py` vide, `models.py`, `paths.py`). `nexus/models.py` importe `nexus.conversations.models` pour que `Base.metadata` voie les tables. La migration `0010` crée les tables par `op.create_table(…, sqlite_autoincrement=True)`, puis la FTS et ses déclencheurs par du SQL brut. Elle ne lit rien du code applicatif : c'est une copie figée, comme `0008`. `backup.py` vide l'index de la copie `.partial` avant de la publier, et efface au démarrage les `*.partial` orphelins.

**Tech Stack :** FastAPI, SQLAlchemy 2.1.1, Alembic 1.20.0, SQLite 3.53.1 (Python 3.13, FTS5 présent), pytest (`uv run --directory server pytest`).

**Spec :** `docs/superpowers/specs/2026-11-25-conversations-lot1-design.md` **fusionné sur `master` au commit `a32dd5b`** (§4.1, §5.1, §5.2, §6.1, §7.3, §11 ligne PR 1, §13, §14, §16), et ADR-025 dans `DECISIONS.md` (D1, D2, D6, D9, D10). Il n'y a pas de fichier `docs/adr/0025-…` : l'ADR vit dans `DECISIONS.md`. Il n'y a pas non plus de `CONTEXT.md` à la racine sur `master` (voir §10, décision M3). Écart avec la révision `7428a11` sur laquelle le premier jet était calé (`git diff 7428a11 a32dd5b`) :
- colonnes `covered_since` et `session_external_id` du curseur ;
- bornes des durées et du sondage ;
- effacement des `*.partial` au démarrage ;
- derniers `offset` devenus `byte_offset` ;
- D1, D6 et D10 de l'ADR alignés sur le cadrage.

Tout est repris ci-dessous.

Légende des affirmations :
- **[vérifié ici]** : essayé par `architect` le 2026-11-26 sur cette machine. Les essais passent par des scripts jetables du scratchpad (`probe_ddl.py`, `probe_os.py`, `probe_ident.py` et `probe_strip.py`, jamais dans le dépôt), et par deux commandes en ligne : le CHECK sans NUL, et `alembic check` sur une base temporaire.
- **[à vérifier]** : à prouver par l'implémenteur, en général par le test qui le porte.
- **[ajout d'architect]** : une règle qui va au-delà du cadrage. Elle est listée au §10 pour le fil principal.

---

## 0. Préalables (bloquants)

- [x] La PR 0 (#205 : cadrage et ADR-025) est fusionnée sur `master` (`a32dd5b`). Ce plan est recalé sur la version fusionnée.
- [x] Le fil principal a confirmé C1 à C16 le 2026-11-26 (cadrage, en-tête et §12 ; corrections au §16).
- [x] La Phase 2 est close : ADR-026 (« Clôture de la Phase 2 », 2026-11-26) et `docs/ROADMAP.md` (« Phase 2 — Exécution (terminée le 2026-11-26) »), tous deux sur `HEAD` `a32dd5b`. La condition de la ligne 3 du cadrage est remplie.
- [x] Issue : #204. Branche : `feat/204-conversations-modele`, depuis `master` à jour. Le corps de la PR porte `Refs #204`.
- [x] `architect` a relu ce plan le 2026-11-26 (AGENTS.md, « Model routing » : migration, secrets et invariants). Les ajouts marqués **[ajout d'architect]** attendent l'accord du fil principal (§10).

## 1. Périmètre exact de la PR 1

Dans la PR (cadrage §11, ligne PR 1) :

1. Migration `0010_conversations` : trois tables, une FTS5 à contenu externe, trois déclencheurs et un `downgrade` complet.
2. Modèles SQLAlchemy et filtre `include_object` (`nexus/conversations/models.py`). Le filtre est branché dans les cinq tests de migration existants et dans `migrations/env.py`.
3. Sonde FTS5 au démarrage (lifespan, en premier) et dans la migration (avant toute création).
4. Réglages :
   - `NEXUS_CONV_CLAUDE_ROOT`, `NEXUS_CONV_CODEX_ROOT` et `NEXUS_CONV_HERMES_DB`, sans valeur par défaut : la source est alors `disabled` (C1) ;
   - `NEXUS_CONV_POLL_SECONDS` (entier, 60, de 10 à 3 600) ;
   - `NEXUS_CONV_SINCE_DAYS` et `NEXUS_CONV_RETENTION_DAYS` (entiers, 31, de 1 à 3 650) ;
   - refus d'une fenêtre plus longue que la rétention. Aucun message ne recopie la valeur reçue (§6.1).
5. `nexus/conversations/paths.py` : contrôle des racines, énumération à profondeur fixe et ouverture sûre (§5.1, §5.2). Aucun appelant en production avant la PR 2.
6. `backup.py` :
   - la copie publiée ne contient plus l'index (§7.3, C9), et un schéma antérieur à `0010` est toléré ;
   - un échec efface la copie partielle **et** ses fichiers voisins ;
   - au démarrage, avant la première sauvegarde, les `*.partial` orphelins et leurs `-wal`, `-shm` et `-journal` sont effacés (§7.3, D10).
7. Docs : DATA-MODEL §2.7, §2.8 et §6. Dans `README.md`, une ligne à côté des réglages de sauvegarde : la sauvegarde exclut l'index, et les sources sont inactives par défaut.

**Hors PR 1** (renvoyé, à ne pas commencer ici) :

- `NEXUS_CONV_HERMES_SOURCES` : la PR 6 (§11, §16).
- La mise à `NULL` de `tasks.origin_message_id` dans la copie : la PR 7, car la colonne n'existe pas encore.
- Tout comportement de `covered_since` et de `session_external_id`. La PR 1 ne pose que les colonnes. Leur pose, leur contrôle dans tout état et leur avance par la purge reviennent à la PR 2 ; le rattachement des reprises Codex à la PR 3.
- La purge elle-même (`secure_delete`, `optimize`, point de contrôle), l'ingestion, la boucle du lifespan, l'API et la vue.
- Le contrôle Hermes **à chaque passe** (`state.db`, `-wal` et `-shm`, §5.3), l'URI `Path.as_uri()` + `?mode=ro`, et le test « `-wal` remplacé par un lien entre deux passes » : la PR 6. `paths.check_root` ne fait ici que contrôler la racine Hermes au démarrage de la source.
- Le masquage de `title`, `workspace`, `git_branch` et `body` (§7.1), et la fabrique qui masque : la PR 2. La PR 1 ne pose que les colonnes. Le modèle et DATA-MODEL disent que ces colonnes portent un texte **déjà masqué**, puis coupé.

### Répartition des tests du §13 (version fusionnée), clause par clause

| Puce du §13 : clause | PR | Où dans ce plan |
|---|---|---|
| Confinement : faux `~/.codex` (`auth.json`, `config.toml`, `history.jsonl`) et faux `.claude` (`.credentials.json`), aucun chemin hors motif touché (`os.open` et `os.scandir` enregistrés) | 1 | §5.5, test 3 |
| Confinement : lien symbolique ou jonction vers l'extérieur | 1 | §5.5, tests 4, 4 bis et 5 |
| Confinement : lien physique | 1 | §5.5, test 6 ; racine Hermes : §5.4, test 8 |
| Confinement : nom au mauvais niveau | 1 | §5.5, test 12 |
| Confinement : racine mal nommée, racine qui est un lien | 1 | §5.4, tests 5, 6, 7 et 9 |
| Confinement : substitution entre `lstat` et `open` | 1 | §5.5, test 7 |
| Confinement : dossier intermédiaire lien ou jonction, jamais parcouru | 1 | §5.5, tests 4, 4 bis et 5 |
| Lecture JSONL (toutes les clauses) | 2 | — |
| Codex zstd (toutes les clauses, `session_external_id` compris) | 3 | — ; la colonne est posée et nommée ici (§5.1, tests 7 et 7 bis) |
| Extraction (Claude) | 2 | — |
| Hermes (toutes les clauses, `state.db` en lien physique **à chaque passe** → `unavailable` compris) | 6 | — ; PR 1 : racine au démarrage seulement (§5.4, test 8) |
| Idempotence et crash | 2 | — |
| Secrets : masquage à la 16 000ᵉ position, `git_branch` masqué, octets de `nexus.db` et de son `-wal` après ingestion, recherche du préfixe | 2 | — |
| Secrets : une sauvegarde ne contient aucun corps de message | 1 | §5.6, test 1 (base remplie par SQL direct ; la PR 2 peut le rejouer après une vraie ingestion) |
| Secrets : sauvegarde d'une base `0009` | 1 | §5.6, tests 3 et 5 |
| Secrets : sauvegarde d'une base `0010` avant `0011` | 1, puis 7 | §5.6, test 1 (la tête de la PR 1 **est** ce cas) ; la PR 7 ajoute l'étape `origin_message_id` |
| Secrets : un échec du retrait ne publie aucune copie | 1 | §5.6, tests 6 et 8 |
| Purge : `NEXUS_CONV_SINCE_DAYS` plus grand que la rétention refusé au démarrage | 1 | §5.3, test 4 |
| Purge : durées à 0, négatives, hors borne ou non entières, sondage à 0 ou négatif, refusés sans recopier la valeur | 1 | §5.3, tests 5 et 6 |
| Purge : `missing_since`, racine illisible, source désactivée, message plus vieux que la rétention, rétention, `covered_since` (rétention élargie pendant `partial`, après une purge, fenêtre inchangée), octets après purge, `integrity-check` | 2 | — |
| Purge : un `.zst` `too_large` inchangé n'est jamais redécompressé | 3 (il faut `zstandard`) | — |
| Purge : clauses Hermes (rattrapage d'un message purgé, `window_from_id = last_row_id + 1`) | 6 | — |
| Purge : tâche liée (`origin_message_id` à `NULL` en base et dans une sauvegarde), `PATCH` refusé sur `origin_message_ref` | 7 | — |
| API | 4 | — |
| Migration : montée, descente, `compare_metadata` sans écart (test de `0010` et cinq tests existants) | 1 | §5.1, §5.7 |
| Web | 5 | — |
| **Hors §13**, §7.3 : « un `.partial` semé avant le démarrage a disparu après lui » | 1 | §5.6, tests 9 et 10 |
| **Hors §13**, §5.3 : `mode=ro` ne modifie pas `state.db` | 6 | — |
| **Hors §13**, §7.1 : mesure de `redact` (condition d'arrêt) | 2 | — |

## 2. Sections de la checklist qui s'appliquent (`docs/agents/review-checklist.md`)

| § | S'applique ? | Cas à couvrir dans cette PR |
|---|---|---|
| 1 Secrets | oui | Les messages d'erreur des racines (`paths.py`) et des réglages sont fixes : ni chemin, ni slug, ni valeur reçue. Les journaux de `paths.py` ne portent que la source, des comptes et un code. Une copie de sauvegarde ne garde aucun octet d'un corps de message, ni dans le fichier ni dans un `-wal`, un `-shm` ou un `-journal` voisin. Un `*.partial` orphelin, qui contient l'index, est effacé au démarrage. |
| 2 Validation | oui (réglages) | Seul un vrai `int` passe (`bool`, `float` et `str` refusés). Côté environnement, la lecture est stricte : chiffres ASCII seulement (ni `1_000`, ni `+31`, ni `1.5`, ni chiffres non ASCII). Les bornes sont tenues. Une racine relative est refusée par `check_root`. |
| 3 Concurrence | marginal | Aucun chemin d'écriture concurrent n'est ajouté. Les clés uniques de `0010` servent l'idempotence de la PR 2 : elles sont testées en base dès maintenant. L'effacement des `*.partial` tourne avant toute sauvegarde, donc aucune copie n'est en cours. |
| 4 Invariants | oui | Les listes fermées (`source`, `role`, `state`), les clés uniques et la longueur de `body` (sans NUL) sont tenues par la base. Un id purgé n'est jamais réattribué (`AUTOINCREMENT`). |
| 5 Provenance | non | Aucune route n'est ajoutée : `test_provenance_contract.py` n'a rien à apprendre. |
| 6 UI | non | |
| 7 Dates | oui (modèle) | `AwareDateTime` sur les nouvelles colonnes, `covered_since` compris : l'heure repliée Europe/Paris, et une date lointaine avec microsecondes. |
| 8 Outillage | oui | Secrets de test construits à l'exécution (`"ghp_" + "A" * 36`) ; aucun vrai fichier de Loïc ; fixture autouse qui retire les `NEXUS_CONV_*` du shell. |
| 9 Avant PR | oui | Migration testée sur une base `0009` **peuplée**. Chaque test de régression est montré rouge d'abord (§6). |

## 3. Fichiers

Tailles relevées sur `master` `a32dd5b` par `wc -l`. Seuils : **400** lignes pour le code, **600** pour un fichier sous `tests/` (`scripts/check-file-size.mjs`). Seul `server/src/nexus/demo_agent.py` figure dans `file-size-baseline.json`, et la PR ne le touche pas.

| Fichier | Action | Lignes avant → estimation après |
|---|---|---|
| `server/src/nexus/conversations/__init__.py` | créer (docstring seule) | → 1 |
| `server/src/nexus/conversations/models.py` | créer | → ~120 |
| `server/src/nexus/conversations/paths.py` | créer | → ~200 (seuil 400) |
| `server/src/nexus/migrations/versions/0010_conversations.py` | créer | → ~130 |
| `server/src/nexus/models.py` | une ligne d'import | 274 → 276 |
| `server/src/nexus/config.py` | six champs, bornes, `_env_root`, `_env_int` | 210 → ~265 |
| `server/src/nexus/app.py` | sonde FTS5 en tête du lifespan, `backup.remove_partials` avant la première sauvegarde | 253 → ~258 |
| `server/src/nexus/backup.py` | retrait de l'index, `_discard`, `remove_partials`, `_open_copy` | 66 → ~130 |
| `server/src/nexus/migrations/env.py` | `include_object` passé à `context.configure` (hors ligne et en ligne) | 31 → ~35 |
| `server/tests/migration_support.py` | créer : `schema_diff(db_url)` | → ~20 |
| `server/tests/conversations_support.py` | créer : fausses racines, enregistreur d'audit, aide `junction` | → ~170 |
| `server/tests/conftest.py` | fixture autouse qui retire les `NEXUS_CONV_*` | 285 → ~297 |
| `server/tests/test_conversations_migration.py` | créer | → ~300 |
| `server/tests/test_conversations_models.py` | créer (dont la sonde du lifespan) | → ~120 |
| `server/tests/test_conversations_settings.py` | créer | → ~150 |
| `server/tests/test_conversations_roots.py` | créer | → ~230 |
| `server/tests/test_conversations_paths.py` | créer | → ~380 |
| `server/tests/test_conversations_backup.py` | créer | → ~320 |
| `server/tests/test_actor_tokens_migration.py` | `schema_diff`, imports inutiles retirés | 150 → ~144 |
| `server/tests/test_approvals_migration.py` | idem | 135 → ~129 |
| `server/tests/test_runs_migration.py` | idem | 79 → ~73 |
| `server/tests/test_run_model_migration.py` | idem, **plus** une montée à `head` avant la comparaison | 57 → ~53 |
| `server/tests/test_task_follows_migration.py` | idem | 137 → ~131 |
| `docs/DATA-MODEL.md` | §2.7, §2.8, §6 | |
| `README.md` | une ligne, sous « Sauvegardes » | |

Les tests de confinement sont répartis sur deux fichiers dès le départ : les racines d'une part, l'énumération et l'ouverture d'autre part. Aucun ne s'approche ainsi des 600 lignes.

## 4. Contenu de la migration `0010_conversations`

En-tête : `revision = "0010"`, `down_revision = "0009"`, `Create Date` du jour. Copie figée des listes (jamais importées de `nexus`) :

```python
SOURCES = ("claude-code", "codex", "hermes")
ROLES = ("user", "assistant")
CURSOR_STATES = ("partial", "skipping", "ok", "too_large", "unreadable", "skipped_old")
TS = sa.String(length=40)  # AwareDateTime: ISO-8601 UTC
FTS_PROBE = "CREATE VIRTUAL TABLE temp.nexus_fts5_probe USING fts5(x)"
NO_FTS5 = "SQLite sans FTS5"
```

### 4.1 `upgrade()`, dans cet ordre

1. **Sonde FTS5 d'abord**, avant toute création : `bind.exec_driver_sql(FTS_PROBE)`, puis `DROP TABLE temp.nexus_fts5_probe`. Sur `sqlalchemy.exc.OperationalError`, `raise RuntimeError(NO_FTS5) from None`. Sous SQLite, le DDL d'Alembic n'est pas transactionnel (`SQLiteImpl.transactional_ddl` vaut `False`) **[vérifié ici]** : une table créée avant l'échec resterait en place.
2. `conversations` :
   - `id` `Integer`, clé primaire ; `sqlite_autoincrement=True` sur la table.
   - `source` `String(16)` NOT NULL ; `external_id` `String(128)` NOT NULL ; `channel` `String(32)` ; `title` `String(200)` ; `workspace` `String(500)` ; `git_branch` `String(200)`.
   - `title`, `workspace` et `git_branch` portent le texte **masqué** (§7.1), coupé ensuite à sa longueur. Aucun code de la PR 1 ne les écrit ; le modèle le dit en commentaire. `String(n)` n'est pas tenu par SQLite, et il n'y a pas de CHECK de longueur sur ces colonnes : le cadrage n'en demande que pour `body`.
   - `started_at` `TS` et `last_message_at` `TS`, nullables (P10, reporté à la PR 4).
   - `message_count` `Integer` NOT NULL ; `missing_since` `TS` ; `measured_at` `TS` NOT NULL.
   - `UniqueConstraint("source", "external_id", name="uq_conversations_source_external_id")`.
   - `CheckConstraint` `ck_conversations_source` (`source IN (…)`) et `ck_conversations_external_id` (`length(external_id) BETWEEN 1 AND 128`).
   - Index `ix_conversations_last_message_at` sur `(last_message_at, id)`.
3. `conversation_messages` :
   - `id` `Integer`, clé primaire ; `sqlite_autoincrement=True`.
   - `conversation_id` `Integer` NOT NULL. La clé étrangère `ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE")` est posée au niveau de la table, comme `runs.task_id` dans `0008`. Le modèle déclare le même `ondelete`.
   - `external_id` `String(128)` NOT NULL. Claude fournit un UUID, Codex un `ordinal` et Hermes un `messages.id`, tous stockés en texte.
   - `role` `String(16)` NOT NULL ; `author` `String(32)` NOT NULL, **sans CHECK** (même raison que `runs.model` dans `0009`).
   - `at` `TS` NOT NULL ; `body` `Text` NOT NULL ; `truncated` `Boolean` NOT NULL ; `redacted` `Boolean` NOT NULL ; `model` `String(64)`.
   - `UniqueConstraint("conversation_id", "external_id", name="uq_conversation_messages_conversation_id_external_id")`.
   - `CheckConstraint` `ck_conversation_messages_role` (`role IN ('user', 'assistant')`).
   - `CheckConstraint` `ck_conversation_messages_body` : `length(body) BETWEEN 1 AND 16000 AND instr(body, char(0)) = 0`. **[ajout d'architect]** La seconde moitié vient d'un relevé : sous SQLite, `length()` s'arrête au premier NUL. Un corps `"a\x00" + "b" * 20000` passe le CHECK nu avec `length() = 1`. Avec `instr`, il est refusé, et 16 000 « é » restent admis **[vérifié ici]**. C15 est ainsi vraiment tenu par la base. La fabrique de la PR 2 devra donc retirer `\x00` avec `\x02` et `\x03` (§7.1).
   - Index `ix_conversation_messages_conversation_id_at` sur `(conversation_id, at)`.
4. `conversation_cursors`, colonnes dans cet ordre :
   - `source` `String(16)` et `path_key` `String(512)` : clé primaire composée.
   - `file_id` `String(64)`, en texte `"<st_dev>:<st_ino>"`, lu par `os.lstat`.
   - `size` `Integer` ; `mtime_ns` `Integer`.
   - `byte_offset` `Integer` NOT NULL, `server_default="0"`, déclaré pareil dans le modèle.
   - `head_sha256` `String(64)` ; `last_row_id` `Integer`.
   - `window_from_id` `Integer`, nullable (Hermes).
   - **`covered_since` `TS`, nullable** : seuil de rétention couvert par l'index pour un fichier, `NULL` pour Hermes et tant qu'aucune lecture n'a commencé à 0. Il est posé, contrôlé et avancé par la PR 2 (§4.1, §6.2 et §6.6 du cadrage).
   - **`session_external_id` `String(128)`, nullable** : Codex, `session_meta.payload.id`, et `NULL` pour les autres sources. Il est posé par la PR 3 (§6.3). Sa longueur est celle de `conversations.external_id`, qui reçoit la même valeur.
   - `state` `String(16)` NOT NULL ; `updated_at` `TS` NOT NULL.
   - `CheckConstraint` `ck_conversation_cursors_source` (`source IN (…)`), `ck_conversation_cursors_state` (six valeurs, `skipping` compris) et `ck_conversation_cursors_path_key` (`length(path_key) BETWEEN 1 AND 512`).
   - Aucun CHECK ne lie `window_from_id`, `covered_since` ou `session_external_id` à `source`. La règle « `NULL` hors de sa source » est tenue par le code des PR 2, 3 et 6 : un CHECK de plus sous SQLite demanderait de reconstruire la table à chaque changement.
5. FTS, par `op.execute` :

   ```sql
   CREATE VIRTUAL TABLE conversation_fts USING fts5(
       body, content='conversation_messages', content_rowid='id',
       tokenize='unicode61 remove_diacritics 2'
   )
   ```

6. Les trois déclencheurs :

   ```sql
   CREATE TRIGGER conversation_messages_ai AFTER INSERT ON conversation_messages BEGIN
       INSERT INTO conversation_fts(rowid, body) VALUES (new.id, new.body);
   END
   CREATE TRIGGER conversation_messages_ad AFTER DELETE ON conversation_messages BEGIN
       INSERT INTO conversation_fts(conversation_fts, rowid, body)
       VALUES ('delete', old.id, old.body);
   END
   CREATE TRIGGER conversation_messages_au AFTER UPDATE ON conversation_messages BEGIN
       INSERT INTO conversation_fts(conversation_fts, rowid, body)
       VALUES ('delete', old.id, old.body);
       INSERT INTO conversation_fts(rowid, body) VALUES (new.id, new.body);
   END
   ```

   `AFTER UPDATE` porte sur toutes les colonnes. Une suppression en cascade depuis `conversations` (avec `foreign_keys=ON`) déclenche bien `_ad`, et `integrity-check` reste propre ensuite **[vérifié ici]**.

**[vérifié ici]** (`probe_ddl.py`), sur ce schéma exact, `covered_since` et `session_external_id` compris, créé par `op.create_table` et `op.create_index`, puis la FTS et les déclencheurs :
- avec le filtre, `compare_metadata` ne rend aucun écart ;
- sans le filtre, il rend exactement cinq `remove_table` (`conversation_fts`, `_config`, `_data`, `_docsize` et `_idx`) ;
- le `sql` des deux tables contient `NOT NULL PRIMARY KEY AUTOINCREMENT` ;
- `PRAGMA table_info(conversation_cursors)` rend les treize colonnes dans l'ordre ci-dessus ;
- `MATCH 'echeance'` retrouve « Échéance réunion ».

### 4.2 `downgrade()`

Dans cet ordre :
1. `DROP TRIGGER` des trois déclencheurs ;
2. `DROP TABLE conversation_fts`, qui supprime aussi ses tables d'ombre ;
3. les deux index ;
4. `conversation_cursors`, `conversation_messages`, puis `conversations`.

L'environnement de migration passe par `make_engine`, qui pose `foreign_keys=ON`. L'ordre enfant avant parent est donc requis, et il marche **[vérifié ici]** : il ne reste aucun objet `conversation%`. `sqlite_sequence` reste, mais la réflexion l'ignore. Les autres tables ne sont pas touchées.

### 4.3 Pièges relevés

- Une colonne `id INTEGER PRIMARY KEY AUTOINCREMENT` écrite à la main sans `NOT NULL` fait remonter un `modify_nullable` à `compare_metadata`. On garde donc `op.create_table` pour les tables, et le SQL brut seulement pour la FTS et les déclencheurs.
- `compare_metadata` ne voit ni les CHECK, ni `AUTOINCREMENT`, ni les déclencheurs, ni le tokenizer, ni un nom de colonne absent des deux côtés : chacun a son test direct (§5.1).

## 5. Tests à écrire d'abord (rouges avant le code)

Plateformes :
- **W** : tourne sur cette machine (Windows 11) ;
- **L** : tourne sur la CI Linux ;
- **skip** : sauté, avec la raison.

Faits relevés sur cette machine **[vérifié ici]** (`probe_os.py`) :
- La création d'un lien symbolique est refusée (`winerror 1314`).
- `_winapi.CreateJunction` marche sans droit d'administrateur.
- `os.link` marche, et `os.lstat` donne `st_nlink == 2`. `DirEntry.stat()`, lui, donne `0` pour `st_ino`, `st_dev` et `st_nlink`.
- `os.O_NOFOLLOW` n'existe pas sous Windows.
- Une jonction : `DirEntry.is_dir(follow_symlinks=False)` vrai, `is_symlink()` faux, `S_ISLNK` faux et `S_ISDIR` vrai, mais `FILE_ATTRIBUTE_REPARSE_POINT` vrai. Son chemin résolu n'a plus cet attribut.
- Les hooks d'audit voient `open` pour `os.open`, et `os.scandir` pour `os.scandir` comme pour `Path.iterdir`.
- Sur un fichier non remplacé, `fstat` et `lstat` donnent le même `(st_dev, st_ino)`.

### 5.1 `test_conversations_migration.py` (W, L)

Base de départ commune : une fixture `at_0009` monte à `0009` et insère une tâche, un run et un événement (même SQL que `test_run_model_migration.py`).

1. `test_upgrading_a_populated_0009_database_keeps_every_row` : les comptes de `tasks`, `runs` et `events` sont inchangés ; les trois nouvelles tables sont vides ; `alembic_version` vaut la tête (`ScriptDirectory…get_current_head()`).
2. `test_the_migrated_schema_matches_the_models_once_fts_is_filtered` : `schema_diff(url) == []`. Sans le filtre, l'écart vaut exactement cinq `remove_table` (`conversation_fts`, `_data`, `_idx`, `_docsize` et `_config`) : le test l'affirme aussi, pour prouver que le filtre est nécessaire et qu'il ne cache rien d'autre.
3. `test_the_fts_tables_are_exactly_the_filtered_names` : l'ensemble des tables `conversation_fts%` de `sqlite_master` vaut `models.FTS_TABLES`.
4. `test_the_fts_is_external_content_with_the_unicode61_tokenizer` : le `sql` de `sqlite_master` contient `content='conversation_messages'`, `content_rowid='id'` et `tokenize='unicode61 remove_diacritics 2'`. Côté comportement, « Échéance réunion » se retrouve par `MATCH 'echeance'`.
5. `test_the_triggers_keep_the_index_in_step`, étape par étape :
   - après une insertion, le terme est trouvé ;
   - après une mise à jour du corps, l'ancien terme n'est plus trouvé et le nouveau l'est ;
   - après la suppression du message, plus rien n'est trouvé ;
   - après la suppression d'une conversation (cascade, `PRAGMA foreign_keys=ON`), ses termes ne sont plus trouvés.

   Après chaque étape, `INSERT INTO conversation_fts(conversation_fts) VALUES('integrity-check')` ne lève rien.
6. `test_ids_are_never_reused_after_a_purge` : `AUTOINCREMENT` figure dans le `sql` des deux tables. On insère deux lignes et on supprime la plus haute : la suivante reçoit 3, pas 2, pour `conversations` comme pour `conversation_messages`.
7. `test_the_database_enforces_the_closed_lists_and_keys` : chaque cas refusé lève `sqlite3.IntegrityError`.
   - Refusés :
     - `source = 'telegram'` ; `role = 'tool'` ; `state = 'reading'` ;
     - `byte_offset` à `NULL` ;
     - un `body` vide, un `body` de 16 001 caractères, et un `body` `"a\x00" + "b" * 20000` (NUL) ;
     - un doublon `(source, external_id)`, un doublon `(conversation_id, external_id)` et un doublon `(source, path_key)` ;
     - un `conversation_id` inconnu (avec `foreign_keys=ON`) ;
     - un `external_id` vide.
   - Admis :
     - un `body` de 1 caractère, un de 16 000, et un de 16 000 « é » ;
     - deux conversations au même `external_id`, de sources différentes ;
     - chacun des six états, `skipping` compris ;
     - un curseur de fichier avec `window_from_id`, `session_external_id` à `NULL` et `covered_since` posé ;
     - un curseur Codex avec `session_external_id` (UUID) ;
     - un curseur Hermes (`path_key = 'state.db'`) avec `window_from_id = 1`, `last_row_id = 9` et `covered_since` à `NULL` ;
     - un `file_id` texte `"<dev>:<ino>"` avec `st_ino = 2**64 - 1`, relu égal.
   - **7 bis.** `test_the_cursor_columns_have_the_spec_names` : `PRAGMA table_info(conversation_cursors)` donne exactement, dans cet ordre, `source`, `path_key`, `file_id` (`VARCHAR`), `size`, `mtime_ns`, `byte_offset` (NOT NULL, défaut `0`), `head_sha256`, `last_row_id`, `window_from_id`, `covered_since` (nullable), `session_external_id` (nullable), `state` et `updated_at`, et **aucune** colonne `offset`.
8. `test_downgrade_removes_tables_fts_and_triggers_and_keeps_the_rest` : on descend de la tête à `0009`. Il ne reste dans `sqlite_master` aucune table `conversation%` ni aucun déclencheur `conversation_messages_%`, et les lignes de `tasks`, `runs` et `events` sont intactes. Une nouvelle montée à `head` réussit.
9. `test_the_migration_fails_closed_without_fts5` : `monkeypatch.setattr("nexus.db.make_engine", …)` enveloppe le vrai moteur d'un écouteur `before_cursor_execute` (`retval=True`). L'écouteur réécrit `USING fts5(` en `USING nexus_absent_module(`, ce qui touche la sonde comme la création. On obtient ainsi la vraie erreur de SQLite, « no such module ». Assertions :
   - la montée de `0009` à `head` lève `RuntimeError` au message exact « SQLite sans FTS5 » ;
   - `alembic_version` reste `0009` ;
   - aucune table `conversation%` n'existe.

   `env.py` fait `from nexus.db import Base, make_engine` à chaque exécution : il est rechargé par chaque commande Alembic, et lit donc l'attribut remplacé **[à vérifier]**.
10. `test_an_empty_database_migrates_to_head` : une base neuve passe par `migrate.upgrade`, et les tables existent.
11. `test_alembic_check_sees_no_drift_at_head` : `migrate.upgrade(url)`, puis `command.check(migrate.alembic_config(url))` ne lève rien. C'est le test du filtre d'`env.py`. Sur `master`, `command.check` passe déjà à la tête `0009` **[vérifié ici]**. Preuve rouge : sans `include_object` dans `env.py`, `AutogenerateDiffsDetected` (les cinq tables FTS) **[à vérifier]**.

### 5.2 `test_conversations_models.py` (W, L)

1. `test_the_conversation_tables_are_registered_on_the_metadata` : `import nexus.models` suffit pour que les trois tables figurent dans `Base.metadata.tables`, et la FTS n'y est pas.
2. `test_include_object_hides_only_the_fts_tables` :
   - faux pour les cinq noms de `FTS_TABLES` avec `type_ == "table"` ;
   - vrai pour `conversations`, `conversation_messages`, `conversation_cursors` et `conversation_fts_extra` ;
   - vrai pour un index nommé `conversation_fts`.

   Le filtre compare à un ensemble exact, jamais à un préfixe.
3. `test_refs_are_handles` : `nx-conv-<id>` et `nx-msg-<id>`, sur le modèle de `Task.ref`.
4. `test_instants_round_trip_across_the_fall_back_hour` :
   - un message à `2026-10-25T02:15:00+01:00` et un autre à `02:30:00+02:00` sont écrits par l'ORM puis relus. Ils se trient dans l'ordre des instants : le premier vient après le second ;
   - `2999-12-31T23:59:59.999999+00:00` revient égal ;
   - `ConversationCursor.covered_since` fait le même aller-retour.
5. `test_require_fts5_passes_here_and_fails_closed` :
   - `require_fts5()` ne lève rien sur ce Python ;
   - avec un `connect` injecté dont `execute` lève `sqlite3.OperationalError("no such module: fts5")`, il lève `RuntimeError("SQLite sans FTS5")`, et le message ne recopie pas l'erreur d'origine ;
   - la connexion de sonde est fermée dans les deux cas.
6. `test_startup_refuses_without_fts5_before_touching_disk` : `monkeypatch.setattr(conv_models, "require_fts5", …)` lève `RuntimeError`. Le démarrage de l'app (`with ActorClient(create_app(settings))`) lève, `settings.data_dir` n'existe pas, et aucune copie n'est faite. `app.py` appelle `conv_models.require_fts5()` par l'attribut du module, jamais par un `from … import`.

### 5.3 `test_conversations_settings.py` (W, L)

Champs ajoutés à `Settings` :

```python
conv_claude_root: Path | None = None   # NEXUS_CONV_CLAUDE_ROOT
conv_codex_root: Path | None = None    # NEXUS_CONV_CODEX_ROOT
conv_hermes_db: Path | None = None     # NEXUS_CONV_HERMES_DB
conv_poll_seconds: int = 60            # NEXUS_CONV_POLL_SECONDS, 10..3600
conv_since_days: int = 31              # NEXUS_CONV_SINCE_DAYS, 1..3650
conv_retention_days: int = 31          # NEXUS_CONV_RETENTION_DAYS, 1..3650
```

Règles (§6.1 du cadrage ; les points marqués sont des **[ajout d'architect]**, faute de règle dans le cadrage) :

- `__post_init__` exige `type(value) is int`, ce qui refuse `bool`, `float` et `str`, puis la borne. Le message est **une constante par variable**, qui nomme la variable et ses bornes, jamais la valeur. Exemple : `"NEXUS_CONV_SINCE_DAYS : un entier de 1 à 3650 est attendu"`. Une table `_CONV_BOUNDS` (champ → variable, min, max) porte ces données.
- Ensuite seulement vient `conv_since_days > conv_retention_days`, avec un message constant qui nomme `NEXUS_CONV_SINCE_DAYS` et `NEXUS_CONV_RETENTION_DAYS`.
- `from_env` lit chaque nombre par `_env_int(name, default)`. La valeur est d'abord débarrassée de ses espaces. **[ajout d'architect]** Une valeur vide après `strip()` donne le défaut, comme une variable absente. Sinon, la valeur doit correspondre à `[0-9]{1,9}` : `int()` seul admettrait `1_000`, `+31` et `٣١`. Un échec donne le même message constant que le contrôle de borne.
- `from_env` lit chaque racine par `_env_root(name)` : absente, vide ou faite d'espaces, elle vaut `None`, sans aucun repli sur `Path.home()`. Sinon, c'est `Path(raw)`, sans contrôle. Le contrôle des chemins appartient à `paths.check_root`, appelé au démarrage d'une source (PR 2), pour que le message ne recopie jamais le chemin.

La règle « jamais la valeur reçue » est celle d'ADR-006, déjà appliquée par `config.py` (`NEXUS_HOST`, `NEXUS_HERMES_PROFILE`, `NEXUS_ALLOWED_ORIGINS`). Aucune entrée de `DECISIONS.md` ne règle le cas d'une variable vide ; « vide = défaut » ne contredit donc rien.

Comment prouver qu'une valeur n'est pas recopiée : par **égalité des messages** pour deux valeurs fautives différentes, et par égalité avec la constante du module. Un test de sous-chaîne entrerait en collision avec les bornes : `0` est dans `3650`, par exemple.

1. `test_every_source_is_disabled_by_default` : `Settings(data_dir=…)` a les trois racines à `None`, un sondage de 60, une fenêtre de 31 et une rétention de 31, tous de type `int`.
2. `test_from_env_never_falls_back_on_home` : sans aucun `NEXUS_CONV_*`, ou avec `""` ou `"   "`, `from_env()` donne `None` pour les trois racines. Aucun chemin sous `Path.home()` n'apparaît dans `Settings`.
3. `test_from_env_reads_each_root` : chaque variable donne le `Path` attendu.
4. `test_a_window_longer_than_the_retention_refuses_to_start` :
   - `(40, 31)` lève `ValueError`, et `(3650, 1)` aussi, avec un message identique au premier. Ce message égale la constante et nomme les deux variables ;
   - une fenêtre égale à la rétention est admise, une plus courte aussi.
5. `test_bounds_are_enforced_without_echo`, paramétré :
   - fenêtre ou rétention à `0`, `-1` ou `3651` : refusée ; à `1` ou `3650` : admise, avec une fenêtre au plus égale à la rétention ;
   - sondage à `9`, `0`, `-1` ou `3601` : refusé ; à `10` ou `3600` : admis ;
   - `True`, `31.0` et `"31"` refusés pour chaque champ.

   Pour un même champ, deux valeurs refusées donnent le même message, égal à la constante.
6. `test_a_non_integer_env_value_is_refused_without_echo` : `abc`, `1.5`, `1e3`, `1_000`, `+31`, `٣١` et `-4` dans `NEXUS_CONV_SINCE_DAYS` lèvent `ValueError`, et tous avec le même message. Même chose pour `NEXUS_CONV_POLL_SECONDS`.
7. `test_an_empty_numeric_env_value_means_the_default` : `NEXUS_CONV_SINCE_DAYS=""` donne 31, et `" 45 "` donne 45 (avec une rétention de 45).

Plus, dans `conftest.py`, une fixture autouse `no_conversation_sources_from_the_shell`, sur le modèle de `no_claude_from_the_shell`. Elle retire les six variables `NEXUS_CONV_*`.

Les réglages existants recopient encore la valeur reçue (P9) : c'est l'issue #208, pas cette PR.

### 5.4 `test_conversations_roots.py` : racines (§5.1, règle 2)

`paths.check_root(configured, kind) -> Root` rend la racine résolue et son identité, ou lève `SourceRefused(code)` avec un message fixe. Ordre imposé par le cadrage, plus un contrôle d'identité **[ajout d'architect]** :

1. `configured.is_absolute()`, sinon `root_not_absolute`, avant tout appel système.
2. `info = os.lstat(configured)` **sur le chemin réglé**. Une absence donne `root_missing`. On vérifie :
   - le type attendu (dossier ; fichier ordinaire pour Hermes), sinon `root_wrong_kind` ;
   - ni `S_ISLNK` ni `FILE_ATTRIBUTE_REPARSE_POINT`, sinon `root_is_link`. On réutilise `is_link` de `adapters/run_commit_scan.py` en l'important, sans le recopier ;
   - pour Hermes, `st_nlink == 1`, sinon `root_hard_linked`.
3. Contrôle du nom sur le chemin réglé (`projects`, `sessions` ou `state.db`, casse exacte), sinon `root_badly_named`.
4. Seulement alors `resolved = configured.resolve(strict=True)`. Le nom est revérifié sur `resolved.name`.
5. **[ajout d'architect]** L'identité `(st_dev, st_ino)` de `os.lstat(resolved)` doit égaler celle de `info`, sinon `root_substituted`. Cela ferme la fenêtre entre le contrôle de lien (2) et `resolve` (4) : une racine remplacée par une jonction dans l'intervalle donne une identité différente **[vérifié ici]** (`probe_ident.py`). Une jonction **parente** (`~/.claude` qui pointe ailleurs) garde, elle, la même identité, et elle est admise.

Verdicts d'`architect` sur les points ouverts du premier jet :

- **R1, parents de la racine : fermé, sans contrôle des parents.** Tout ce qui est lu reste sous la racine résolue. Un parent jonction ne fait que déplacer la racine que Loïc a lui-même réglée, et son identité reste celle du dossier final (`probe_ident.py` : « parent-junction same True »). Contrôler chaque parent refuserait des installations légitimes (OneDrive, profil déplacé) sans protéger la liste blanche.
- **R2, nom contrôlé sur le chemin réglé puis sur le chemin résolu, casse exacte : fermé, retenu.** Sous Windows, `resolve` rend la casse réelle du disque. `Projects` ou un nom court `PROJEC~1` sont refusés : c'est un échec fermé, et le message dit le nom attendu, jamais celui reçu.

Chaque test de refus vérifie aussi que ni `str(tmp_path)` ni le nom du dossier ne figurent dans `str(exc)`. Tous ces tests relèvent de la puce **Confinement** et de la **PR 1**.

1. `test_a_well_named_directory_is_accepted` (W, L) : `…/projects`, `…/sessions` et `…/state.db` (fichier) sont admis. `Root.path` est résolu.
2. `test_a_missing_root_is_refused` (W, L) : `root_missing`.
3. `test_a_relative_root_is_refused` (W, L) : `root_not_absolute`.
4. `test_a_root_of_the_wrong_kind_is_refused` (W, L) : `projects` qui est un fichier, `state.db` qui est un dossier.
5. `test_a_badly_named_root_is_refused` (W, L) : `.codex` au lieu de `sessions`, `.claude` au lieu de `projects`, `hermes.db` au lieu de `state.db`, et `Projects` (casse).
6. `test_a_root_that_is_a_junction_is_refused` (W ; skip ailleurs, « jonctions : Windows seulement ») : une jonction `…/projects` vers `…/ailleurs/projects` donne `root_is_link`.
7. `test_a_root_that_is_a_symlink_is_refused` (L ; skip sous Windows sans le droit de lien, `winerror 1314`) : les trois sortes de racine.
8. `test_a_hard_linked_hermes_db_is_refused` (W, L) : un second nom posé par `os.link` donne `root_hard_linked`. Une fois le second nom effacé, la racine est admise.
9. `test_the_link_check_runs_before_resolve` (W ; skip ailleurs) : `Path.resolve` et `os.path.realpath` sont enveloppés. Sur une racine jonction, `root_is_link` est levée **sans** appel de résolution.
10. `test_a_relative_root_touches_nothing` (W, L) : sous `recording()`, `check_root(Path("projects"), "claude")` lève `root_not_absolute` sans aucun événement `open`, `os.scandir` ou `os.listdir`, même avec un dossier `projects` dans le dossier courant (`monkeypatch.chdir(tmp_path)`).
11. `test_a_root_swapped_before_resolve_is_refused` (W ; skip ailleurs) : `Path.resolve` est enveloppé. Au premier appel, il remplace le vrai dossier `…/projects` par une jonction vers `…/ailleurs/projects`, puis appelle la vraie résolution. Le résultat attendu est `root_substituted`. Preuve rouge : sans le contrôle 5, la racine est admise, résolue hors de l'emplacement réglé.

Note pour la PR 2 : le cadrage contrôle la racine « au démarrage de la source ». `architect` recommande d'appeler `check_root` **à chaque passe**, ce qui ne coûte que quelques `lstat`, pour qu'une racine remplacée entre deux passes soit refusée. C'est à trancher avec la PR 2 (§10, M4).

### 5.5 `test_conversations_paths.py` : énumération et ouverture (§5.1, règles 3 à 6, et §5.2)

`conversations_support.py` fournit :

- `fake_claude_home(tmp_path)` : un faux `.claude/` qui contient `.credentials.json`, `settings.json` (contenu inventé, construit à l'exécution) et `projects/`. Sous `projects/` :
  - un slug valide avec deux sessions valides ;
  - un `<uuid>/subagents/x.jsonl`, `tool-results/`, `memory/MEMORY.md` et `notes.txt` ;
  - un `<UUID EN MAJUSCULES>.jsonl`, un `<uuid>.jsonl.bak` et un dossier nommé `<uuid>.jsonl` ;
  - un slug avec une espace, et un `<uuid>.jsonl` posé au niveau 1.
- `fake_codex_home(tmp_path)` : un faux `.codex/` avec `auth.json`, `config.toml` et `history.jsonl` (inventés), et `sessions/2026/11/03/rollout-2026-11-03T10-22-33-<uuid>.jsonl.zst`. En plus :
  - le même nom en `.jsonl` clair ;
  - un `.zst` au niveau du mois ;
  - `sessions/26/…`, `sessions/archive/…` et `sessions/2026/11/03/sub/…` ;
  - un dossier `2026` sous `sessions/2026/11/`.

  Une aide `junction(link, target)` (`_winapi.CreateJunction`, Windows seulement) sert aux tests 4, 4 bis, 10 et au §5.4.
- `recording()` : un enregistreur `sys.addaudithook`, installé une seule fois par session (un hook d'audit ne se retire pas) et actif seulement dans un bloc `with`. Il note `open`, `os.scandir` et `os.listdir`. `os.lstat` n'émet pas d'événement.

Contrôle des dossiers intermédiaires (§5.1, règle 3 ; ADR-025 D2) : `paths._check_level_dir(path, root)` passe **avant chaque `os.scandir`** sous la racine. Il porte sur le `<slug>` Claude, et sur `AAAA`, `MM` et `JJ` chez Codex. Il fait :
- `os.lstat(path)` : `S_ISDIR` vrai, `is_link(info)` faux ;
- puis `path.resolve(strict=True).is_relative_to(root.path)`.

Un dossier refusé est sauté et compté (`skipped_dirs`, code `level_dir_is_link` ou `level_dir_outside`), jamais parcouru.

Chaque candidat passe par `os.lstat` :
- fichier ordinaire, sans lien, `st_nlink == 1` ;
- chemin résolu sous `root.path`.

`Candidate` porte `path_key` (relatif, avec `/`), le chemin, `file_id` (`f"{st_dev}:{st_ino}"` du `lstat`), `size` et `mtime_ns`. `open_candidate` ouvre, puis compare le `fstat` à l'identité du `lstat`. En cas d'écart, il ferme le descripteur **avant** de lever `SourceRefused("substituted")`. `opened(candidate)` est le gestionnaire de contexte qui ferme toujours.

1. `test_only_whitelisted_claude_files_are_listed` (W, L) : seules les deux sessions valides sortent. Leur `path_key` vaut `<slug>/<uuid>.jsonl`, avec `/` même sous Windows.
2. `test_only_compressed_codex_rollouts_are_listed` (W, L) : seul le `.jsonl.zst` sort. Le `.jsonl` clair n'est ni listé ni ouvert (C7).
3. `test_nothing_outside_the_whitelist_is_opened_or_scanned` (W, L) : l'énumération, puis l'ouverture de chaque candidat, tournent sous `recording()`. On ne regarde que les chemins sous `tmp_path`, car un import paresseux ouvre aussi des fichiers de Python. Sous `tmp_path` :
   - les seuls `os.scandir` portent sur la racine et les dossiers admis de niveau 1 (Claude), ou sur la racine, `AAAA`, `MM` et `JJ` (Codex) ;
   - les seuls `open` portent sur les fichiers admis ;
   - **aucun** chemin du parent (`.claude`, `.codex`) n'est touché.
4. `test_a_junctioned_intermediate_directory_is_never_scanned` (W ; skip ailleurs), paramétré sur `<slug>`, `AAAA`, `MM` et `JJ` : le dossier au nom admis est une jonction vers un dossier extérieur, qui contient un fichier au nom admis. Assertions :
   - aucun `os.scandir` ni `open` sous `tmp_path/ailleurs`, ni sur la jonction elle-même ;
   - le fichier extérieur ne sort pas ;
   - `skipped_dirs == 1` ;
   - les autres dossiers du même niveau sont parcourus.
   - **4 bis.** `test_a_junction_back_into_the_root_is_not_followed` (W ; skip ailleurs) : un `<slug>` jonction vers un autre slug de la racine, et un `JJ` jonction vers un autre jour de la racine. La jonction n'est pas parcourue, et chaque fichier ne sort qu'une fois, sous son vrai `path_key`. Preuve rouge : remplacer le contrôle par `DirEntry.is_dir(follow_symlinks=False)` fait échouer ce test, qui est le seul à tenir le contrôle du point de réanalyse.
5. `test_a_symlinked_level_directory_or_file_is_refused` (L ; skip sans droit sous Windows) : les quatre niveaux, plus un fichier candidat, en lien symbolique vers l'extérieur. Mêmes assertions que le test 4.
6. `test_a_hard_linked_file_is_refused` (W, L) : un `os.link` vers un fichier admis écarte les deux noms (`st_nlink == 2`). Sous Windows, ce test prouve que le code appelle `os.lstat` et non `DirEntry.stat()`, qui rendrait 0.
7. `test_a_file_swapped_between_lstat_and_open_is_refused` (W, L) : après l'énumération, un autre fichier est posé sur le candidat par `os.replace`. `open_candidate` lève `SourceRefused("substituted")`. Le descripteur est fermé : on capture son numéro par un `os.open` enveloppé, et `os.fstat` dessus lève `OSError`.
8. `test_the_open_flags_match_the_platform` (W, L) : `O_RDONLY | O_BINARY | O_NOINHERIT` sous Windows, `O_RDONLY | O_NOFOLLOW | O_CLOEXEC` ailleurs, vérifiés par un `os.open` enveloppé.
9. `test_a_candidate_is_closed_after_use` (W, L) : `with paths.opened(candidate) as fd:`, puis, après le bloc, `os.fstat(fd)` lève `OSError`. Même chose quand le bloc lève.
10. `test_the_resolved_candidate_stays_under_the_root` (W ; L avec un lien de dossier) : un dossier de niveau déjà validé est remplacé, **entre son contrôle et son listage**, par une jonction (W) ou un lien de dossier (L) vers un dossier extérieur. Le remplacement passe par un `os.scandir` enveloppé, au premier appel sur ce dossier. Le fichier extérieur est refusé, parce que son chemin résolu sort de la racine. Preuve rouge : retirer `is_relative_to` sur les candidats fait échouer ce test.
11. `test_logs_carry_counts_and_codes_only` (W, L) : sur l'arbre factice (avec, sous Windows, la jonction du test 4), `caplog` ne contient ni slug, ni UUID, ni morceau de chemin, ni nom refusé. Il ne porte que `source`, des comptes (`listed`, `skipped`, `skipped_dirs`) et des codes.
12. `test_a_name_at_the_wrong_level_is_not_listed` (W, L) : un `<uuid>.jsonl` au niveau 1 de Claude, un `rollout-….jsonl.zst` au niveau du mois chez Codex et un dossier `AAAA` sous `MM` ne sortent pas et ne sont pas ouverts.

### 5.6 `test_conversations_backup.py` (W, L)

Puce **Secrets**, partie sauvegarde, et §7.3 du cadrage. Le retrait se fait dans cet ordre :
1. ouvrir la copie `.partial` par `_open_copy(path)`, une fonction de module, seule couture de test ;
2. `PRAGMA journal_mode=MEMORY`, en **vérifiant** que le pragma rend `memory`, sinon `RuntimeError` **[ajout d'architect]** ;
3. `temp_store=MEMORY`, `foreign_keys=ON` et `secure_delete=ON` ;
4. lire les tables présentes, et retourner si aucune n'est une table de conversation ;
5. vider les tables présentes, puis reconstruire la FTS vide ;
6. `commit` ;
7. `VACUUM` ;
8. fermer, dans un `finally`.

Ensuite seulement viennent `os.replace` (publication), ou, en cas d'échec, `_discard(partial)`, puis la rotation. `_discard` **[ajout d'architect]** efface `partial` et ses `-wal`, `-shm` et `-journal`. `backup()` l'appelle dans son `except BaseException` à la place de `partial.unlink(missing_ok=True)`.

Une base à la tête est remplie par du SQL direct : deux conversations, trois messages et deux curseurs. Le corps de chaque message porte un marqueur unique et un secret synthétique, tous deux construits à l'exécution (`"zq" + uuid4().hex`, `"ghp_" + "A" * 36`).

1. `test_a_backup_holds_no_conversation_index` : `backup.backup(...)` réussit. Dans la copie :
   - les trois tables sont vides ;
   - `MATCH` sur le marqueur ne rend rien, et `integrity-check` passe ;
   - les **octets bruts** ne contiennent ni le marqueur ni le secret.

   La base source garde ses lignes. C'est aussi le cas « base à `0010` avant `0011` » du §13.
2. `test_no_sidecar_file_is_left_next_to_a_backup` : `backup_dir` ne contient aucun `*-wal`, `*-shm`, `*-journal` ni `*.partial*`. La copie se rouvre en `journal_mode` `delete`.
3. `test_a_backup_of_a_0009_database_needs_no_strip` : base à `0009`, sauvegarde réussie. La copie a les mêmes tables et les mêmes lignes, sans fichier voisin. Une copie `0009` sort aussi du mode WAL sans voisin **[vérifié ici]** (`probe_ident.py`).
4. `test_backup.py` (table `t`) et `test_health.py` (table `notes`) restent verts **sans changement**. Le chemin d'échec de `test_failed_copy_is_not_published` (`FailingSource`) ne passe pas par le retrait : la copie échoue avant. `_open_copy` appelle `sqlite3.connect(path)` sans `uri=True`, donc le faux `connect` de ce test rendrait de toute façon une vraie connexion.
5. `test_the_pre_migration_copy_of_a_0009_database_succeeds` : le lifespan démarre sur une base `0009`. La copie d'avant migration existe, n'a aucune table `conversation%` ni fichier voisin, et la base est migrée.
6. `test_a_failed_strip_publishes_nothing` : `monkeypatch` ajoute en fin de `backup._STRIP_STATEMENTS` la paire `("conversations", "DELETE FROM nexus_absent_table")`. L'erreur remonte, aucune copie n'est publiée, et il ne reste aucun `*.partial*` (voisins compris). Sous Windows, `unlink` échoue (`winerror 32`) tant qu'une connexion tient le fichier : le `finally` du retrait ferme donc la connexion avant `_discard`.
7. `test_a_restored_backup_starts_with_an_empty_index` : la copie, remise comme `nexus.db`, démarre l'app sans migration en attente. Les trois tables sont vides et la FTS est cohérente.
8. `test_the_strip_commits_before_vacuum_and_closes_before_unlink` : `backup._open_copy` est remplacé par `lambda p: sqlite3.connect(p, factory=Recording)`. `Recording` est une sous-classe de `sqlite3.Connection` qui journalise `execute`, `commit` et `close`. On passe par `factory=` parce que les méthodes d'une instance de `sqlite3.Connection` ne se remplacent pas. Ordre attendu :
   - `journal_mode=MEMORY` avant le premier `DELETE` ;
   - `commit` avant `VACUUM` ;
   - `close` en dernier.

   Sur le chemin d'échec du test 6, `close` précède le `unlink` de la copie partielle (`pathlib.Path.unlink` enveloppé). Preuve rouge : retirer le `commit` fait lever « cannot VACUUM from within a transaction ».
9. `test_startup_removes_leftover_partials`. Dans `backup_dir`, on sème :
   - `nexus-20261101T000000000000Z.db.partial`, qui contient le marqueur, avec ses `-wal`, `-shm` et `-journal` ;
   - une vraie sauvegarde `nexus-…db` ;
   - `notes.partial` et `nexus-x.db.partial`, au nom hors motif.

   Après le démarrage de l'app : les quatre fichiers semés au bon nom ont disparu, la vraie sauvegarde et les deux noms hors motif restent. `backup.backup`, enveloppé, vérifie à son premier appel qu'aucun `*.partial` au bon nom n'existe : l'effacement précède bien la première sauvegarde.
10. `test_remove_partials_is_a_no_op_without_a_backup_dir` : `backup.remove_partials(absent)` ne lève rien et ne crée rien.

`remove_partials(backup_dir)` **[ajout d'architect pour la forme]** :
- il fait un `os.scandir` du seul dossier des sauvegardes ;
- il n'efface que les fichiers ordinaires (`lstat`, `S_ISREG`, ni lien ni point de réanalyse) dont le nom correspond **entièrement** à `re.escape(PREFIX) + r"\d{8}T\d{12}Z" + re.escape(SUFFIX + PARTIAL) + r"(-wal|-shm|-journal)?"` ;
- il ne parcourt aucun sous-dossier et n'efface rien d'autre ;
- une erreur d'effacement remonte et fait échouer le démarrage. Les erreurs de fichiers au démarrage remontent déjà (docstring de `create_app`), et une copie qui garde l'index ne doit pas rester en silence (§10, M2).

Ordre dans le lifespan :
1. `conv_models.require_fts5()` ;
2. `data_dir.mkdir` ;
3. `backup.remove_partials(settings.backup_dir)` ;
4. la sauvegarde d'avant migration ;
5. `migrate.upgrade`.

### 5.7 Les cinq tests de migration existants

`server/tests/migration_support.py` :

```python
def schema_diff(db_url: str) -> list:
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={"include_object": include_object})
            return compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
```

Par test, désigné par son nom (les numéros de ligne bougent) :

- `test_actor_tokens_migration.py::test_the_migrated_schema_matches_the_models`, `test_approvals_migration.py::test_the_migrated_schema_matches_the_models`, `test_runs_migration.py::test_0008_creates_runs_matching_the_models_and_drops_it_again` et `test_task_follows_migration.py::test_the_migrated_schema_matches_the_models` : le bloc `create_engine` / `compare_metadata` devient `assert schema_diff(url) == []`. Ces tests montent déjà à `head`.
- `test_run_model_migration.py::test_0009_adds_a_nullable_model_and_drops_it_again` : la comparaison se fait à `0009`. On ajoute `command.upgrade(cfg, "head")` juste avant elle, avec le commentaire de `test_runs_migration.py` (« the models describe the head schema »). Les assertions sur `model` à `0009` restent avant cette montée. La descente vers `0008` qui suit passe alors aussi par le `downgrade` de `0010`.
- Dans chacun de ces cinq fichiers, on retire les imports devenus inutiles : `compare_metadata`, `MigrationContext`, `create_engine` et `Base`, sauf s'ils servent ailleurs dans le fichier. Sinon `ruff` (F401) bloque le commit.

## 6. Étapes (TDD : test d'abord, chaque commit vert)

Le hook pre-commit lance la suite rapide : on ne commite jamais un test rouge. La preuve « rouge d'abord » (checklist §9) se fait en local et se recopie dans le corps de la PR (nom du test et ligne d'échec).

- [ ] **Étape 1 — Réglages.** Écrire `test_conversations_settings.py` et la fixture autouse, et les voir rouges (`TypeError` sur les champs absents). Compléter `config.py` (`_CONV_BOUNDS`, `_env_int`, `_env_root`). Vert. Commit.
- [ ] **Étape 2 — Modèles, migration et filtre : un seul commit.** Tant que les modèles et `0010` ne sont pas là ensemble, les cinq tests existants sont rouges. Importer `nexus.conversations.models` suffit en effet à enregistrer les tables sur le `Base.metadata` partagé, quel que soit le fichier de test. Ordre de travail :
  1. Écrire `test_conversations_models.py` (tests 1 à 5), `test_conversations_migration.py` et `migration_support.py`. Ils sont rouges (`ModuleNotFoundError`).
  2. Créer `conversations/__init__.py` et `conversations/models.py` (`Conversation`, `ConversationMessage`, `ConversationCursor`, `FTS_TABLE`, `FTS_TABLES`, `include_object`, `require_fts5`), puis ajouter l'import dans `nexus/models.py`. **Preuve rouge 1**, à recopier : les cinq tests existants échouent sur des `add_table` des conversations.
  3. Écrire `0010_conversations.py`. **Preuve rouge 2**, à recopier : les cinq tests échouent sur exactement cinq `remove_table` FTS, et `test_alembic_check_sees_no_drift_at_head` lève `AutogenerateDiffsDetected`.
  4. Brancher `schema_diff` dans les cinq tests (avec la montée à `head` dans `test_run_model_migration.py`), retirer les imports inutiles, et passer `include_object` à `env.py` (hors ligne et en ligne).
  5. Vert : les nouveaux tests, les cinq tests, et `ruff check .`. Commit.
- [ ] **Étape 3 — Sonde au démarrage.** Écrire `test_startup_refuses_without_fts5_before_touching_disk` : il est rouge. Appeler `conv_models.require_fts5()` en première ligne du `lifespan` d'`app.py`, avant `mkdir`. Vert. Commit.
- [ ] **Étape 4 — Racines.** `test_conversations_roots.py` rouge, puis `paths.check_root`, `Root` et `SourceRefused`. Vert. Commit.
- [ ] **Étape 5 — Énumération et ouverture.** Écrire `conversations_support.py`, puis `test_conversations_paths.py`, rouge. Écrire ensuite `paths._check_level_dir`, `paths.iter_claude`, `paths.iter_codex`, `Candidate`, `open_candidate` et `opened`. Vert sous Windows ; les tests L sautés sont nommés dans la PR. Commit.
- [ ] **Étape 6 — Sauvegarde.** `test_conversations_backup.py` rouge : le test 1 trouve le marqueur dans la copie, et le test 9 trouve encore les `*.partial`. Écrire ensuite le retrait (`_open_copy`, `_STRIP_STATEMENTS`, `_strip_conversations`), `_discard` et `remove_partials`, puis l'appel dans le lifespan. Vert, avec `test_backup.py` et `test_health.py` inchangés et verts. Commit.
- [ ] **Étape 7 — Docs.** Commit.
  - DATA-MODEL §2.7 : `nx-conv-<n>` est une poignée d'index, pas l'identité de la session. `external_ref` vaut `claude-session:<id>`, `codex-session:<id>` ou `hermes-session:<id>`. Une purge suivie d'une relecture donne une nouvelle poignée. Reprendre les champs de §4.1.
  - DATA-MODEL §2.8 : `nx-msg-<n>`. Pour un message externe : `role`, `author` (dont `unknown`), `truncated`, `redacted` et `model`. `from`, `to[]` et `kind` restent ceux des messages natifs.
  - DATA-MODEL §6 : les sessions Claude, Codex et Hermes sont indexées dans `nexus.db`, masquées, pour 31 jours au plus, et absentes des sauvegardes.
  - `README.md`, sous « Sauvegardes » : « les sauvegardes n'emportent pas l'index des conversations ». Et : « aucune source de conversations n'est lue sans `NEXUS_CONV_CLAUDE_ROOT`, `NEXUS_CONV_CODEX_ROOT` ou `NEXUS_CONV_HERMES_DB` ».

### Esquisse du retrait (`backup.py`)

Le retrait est appelé après `source.close()` et avant `os.replace(partial, target)`, dans le `try` existant de `backup()`. Son échec passe ainsi par `except BaseException: _discard(partial); raise`.

```python
# Messages first: their delete trigger keeps the FTS in step. A table absent from an older
# copy (the lifespan backs up before migrating) is skipped.
_STRIP_STATEMENTS = (
    ("conversation_messages", "DELETE FROM conversation_messages"),
    ("conversations", "DELETE FROM conversations"),
    ("conversation_cursors", "DELETE FROM conversation_cursors"),
    ("conversation_fts", "INSERT INTO conversation_fts(conversation_fts) VALUES('rebuild')"),
)


def _open_copy(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)  # no uri=True: a plain local file


def _strip_conversations(path: Path) -> None:
    conn = _open_copy(path)
    try:
        # The copy inherits WAL from the source header; MEMORY leaves no -wal/-shm beside it.
        (mode,) = conn.execute("PRAGMA journal_mode=MEMORY").fetchone()
        if mode != "memory":
            raise RuntimeError("copie de sauvegarde : journal non basculé")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA secure_delete=ON")
        present = {name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not present & {table for table, _ in _STRIP_STATEMENTS}:
            return  # older than 0010: nothing to strip
        for table, statement in _STRIP_STATEMENTS:
            if table in present:
                conn.execute(statement)
        conn.commit()  # VACUUM refuses an open transaction
        conn.execute("VACUUM")
    finally:
        conn.close()  # before any unlink: Windows will not delete an open file
```

**[vérifié ici]** (`probe_strip.py`), sur le schéma exact du §4.1 :
- source en WAL avec 200 messages, qui portent un marqueur et un secret synthétique, copiée en `.partial` par l'API `backup` ;
- `journal_mode=MEMORY` rend `memory` ;
- après les instructions ci-dessus, ni le marqueur ni le secret ne restent dans les octets bruts, et aucun fichier voisin n'existe ;
- la copie se rouvre en mode `delete` ; ses trois tables sont vides, `MATCH` ne rend rien et `integrity-check` passe ;
- la source garde ses 200 messages.

Ne pas lancer `delete-all` sur la FTS **avant** le `DELETE` : le déclencheur `_ad` enverrait alors des `delete` pour des lignes que l'index n'a plus, ce qui peut corrompre une FTS5 à contenu externe. **[à vérifier en PR 2]** : la durée du `DELETE` ligne à ligne (un déclencheur FTS par ligne) sur 50 000 messages. La sauvegarde tourne toutes les 24 h et au démarrage.

## 7. Commandes de vérification

Ne pas lancer les suites complètes pendant qu'un serveur réel tourne sur ce checkout. Dans la branche de travail :

```bash
uv run --directory server pytest -q tests/test_conversations_settings.py tests/test_conversations_models.py tests/test_conversations_migration.py tests/test_conversations_roots.py tests/test_conversations_paths.py tests/test_conversations_backup.py
uv run --directory server pytest -q tests/test_actor_tokens_migration.py tests/test_approvals_migration.py tests/test_runs_migration.py tests/test_run_model_migration.py tests/test_task_follows_migration.py tests/test_backup.py tests/test_health.py tests/test_provenance_contract.py
uv run --directory server ruff check .
pnpm check:size
pnpm test     # size-check node tests, pytest -q, then web tests
pnpm lint     # ruff + web lint
```

`pnpm --dir web build` et Playwright ne sont pas concernés : la PR ne touche pas `web/`, et le corps de la PR le dit (checklist §9). Sous Linux et macOS, `TMPDIR` doit pointer hors de `/tmp` (AGENTS.md). La CI Linux exécute les tests de liens symboliques que cette machine saute : il faut les y voir passer, et non sautés, avant de fusionner.

## 8. Avant la PR

- [ ] La checklist est parcourue. Le corps de la PR note §1, §2, §3, §4, §7, §8 et §9 comme vérifiés, et §5 et §6 comme sans objet (raison au §2 de ce plan).
- [ ] Le corps porte `Refs #204`, pas `Closes` : la PR 1 ne traite qu'une partie de l'issue du lot.
- [ ] Le corps liste les tests sautés sur chaque plateforme, avec la raison, et les ajouts d'`architect` du §10 avec la décision du fil principal.
- [ ] `git status` est propre : aucun `nexus.db`, aucune capture.
- [ ] Le circuit de relecture d'AGENTS.md (`reviewer`, Antigravity, CodeRabbit) porte sur le même commit de tête.

## 9. Problèmes relevés contre le code : état au commit `a32dd5b`

| Problème | Sujet | État |
|---|---|---|
| P1 | `test_run_model_migration.py` compare à `0009`, pas à `head` | repris (§4.1 du cadrage) ; §5.7 |
| P2 | contrôle de lien avant `resolve` | repris (§5.1, règle 2) ; §5.4, tests 6 et 9 ; complété par le contrôle d'identité (§5.4, contrôle 5, test 11) |
| P3 | DDL non transactionnel : sonde FTS5 en tête de migration | repris ; §5.1, test 9 |
| P4 | copie en WAL, `VACUUM` dans une transaction, `unlink` sous Windows | repris (§7.3) ; §5.6, tests 2, 6 et 8 |
| P5 | `file_id` en texte, lu par `os.lstat` | repris ; §5.1, test 7 |
| P6 | `byte_offset` au lieu de `offset` | repris ; §5.1, test 7 bis. Il ne reste aucun `offset` nu dans le cadrage fusionné (grep) |
| P7 | filtre à noms exacts, passé aussi à `env.py` | repris ; §5.1, tests 2, 3 et 11, et §5.2, test 2 |
| P8 | `NEXUS_CONV_HERMES_SOURCES` en PR 6 | repris (§16) ; hors PR 1 |
| P9 | écho des valeurs numériques des réglages existants | issue #208 ; les nouveaux réglages n'en font pas (§5.3) |
| P10 | nullité de `started_at`, `last_message_at` et ordre des nuls | reporté à la PR 4 ; nullables ici |
| P11 | CHECK sur `state` et sur la longueur de `body`, aucun sur `author` | repris ; NUL ajouté (§4.1) |
| P12 | `DirEntry.stat()` à zéro sous Windows | repris ; §5.4, test 8, et §5.5, test 6 |
| P13 | racine relative refusée | repris ; §5.4, tests 3 et 10 |
| R1 | parents de la racine | **fermé par `architect`** : pas de contrôle des parents (§5.4) |
| R2 | nom contrôlé sur le chemin réglé et sur le chemin résolu | **fermé par `architect`** : les deux, casse exacte (§5.4) |
| R3 | nom du compte des dossiers refusés | `skipped_dirs` ; l'état de source de la PR 4 le reprendra |
| R4 | `offset` résiduel dans le cadrage | **fermé** par `a32dd5b` |
| R5 | estimations du §14 plus basses que celles du plan | sans effet : rien n'approche 400 lignes (§3) |
| R6 | clôture de la Phase 2 | **fermé** : ADR-026 et ROADMAP sur `a32dd5b` (§0) |
| R7 | ADR-025 D1 moins strict que le cadrage | **fermé** par `a32dd5b` (D1 cite la racine relative et `st_nlink`) |

## 10. Décisions pour le fil principal

- **M1 : fermé.** La Phase 2 est close (ADR-026, ROADMAP ; §0).
- **M2 (ajouts d'`architect`, à confirmer ensemble avant l'étape 2) :** aucun ne contredit le cadrage ni ADR-025. Chacun resserre une règle sans élargir ce qui est lu. Si le fil principal les accepte, la PR 1 les mentionne dans son corps. Les reprendre au §16 du cadrage est facultatif (une PR de docs à part, pas dans la PR 1).
  1. CHECK `instr(body, char(0)) = 0` sur `conversation_messages.body` (§4.1). Sans lui, un NUL rend `length()` faux et contourne C15. La fabrique de la PR 2 retire `\x00`.
  2. Contrôle d'identité de la racine, `lstat(réglé) == lstat(résolu)`, code `root_substituted` (§5.4).
  3. Lecture stricte des nombres de l'environnement (chiffres ASCII) ; une valeur vide vaut le défaut (§5.3).
  4. `_discard` : un échec de sauvegarde efface aussi les `-wal`, `-shm` et `-journal` de la copie partielle (§5.6).
  5. `remove_partials` : motif exact du nom, fichiers ordinaires seulement, et une erreur fait échouer le démarrage (§5.6).
  6. `journal_mode=MEMORY` vérifié sur la copie (§5.6).
- **M3 : `CONTEXT.md` est absent à la racine.** `docs/agents/domain.md` en annonce un. Sans effet sur la PR 1, mais l'instruction « vérifier `CONTEXT.md` » ne peut pas s'appliquer. À créer ou à corriger dans une PR de docs à part.
- **M4 (pour la PR 2, pas la PR 1) : `check_root` à chaque passe**, et non seulement au démarrage de la source (§5.4, note).

## Décision du fil principal sur M2 (2026-11-26)

Les six ajouts M2 sont **acceptés**, choisis par l'agent sous la délégation totale de Loïc du 2026-11-25 (ADR-024). Chacun resserre une règle sans élargir ce qui est lu :
- CHECK `instr(body, char(0)) = 0` (et la fabrique de la PR 2 retire `\x00`) ;
- contrôle d'identité de la racine (`root_substituted`) ;
- nombres de l'environnement en chiffres ASCII, variable vide égale au défaut ;
- `_discard` sur l'échec de la sauvegarde ;
- `remove_partials` dont l'échec fait échouer le démarrage ;
- résultat de `journal_mode=MEMORY` vérifié.

À reporter dans le cadrage (§16) avec la PR 1. M3 (`CONTEXT.md` annoncé par `docs/agents/domain.md`) : PR de docs à part. M4 (`check_root` à chaque passe) : à décider en PR 2.
