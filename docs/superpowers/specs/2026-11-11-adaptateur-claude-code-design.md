# Adaptateur `claude-code` — cadrage du lot H (ADR-023)

**Date :** 2026-11-11
**Issue :** #183 (Phase 2, lot H)
**Décision d'origine :** Loïc, 2026-11-11 — Nexus peut confier une carte à Claude Code (`claude -p`, non interactif), avec le **modèle choisi à chaque run** (Haiku, Sonnet ou Opus) dans « Confier à ». Chaque run consomme l'abonnement Claude de Loïc ; les runs réels se lancent à la main, jamais en CI.
**Entrées :** ADR-023 (D1–D8 et addendum Hermes D7), AGENTS.md (« Model routing », règle du 2026-10-17), INTEGRATIONS §A.2, DATA-MODEL §2.5, SECURITY §3, VIEWS (« Confier à »), adaptateurs Codex (`server/src/nexus/adapters/codex*.py`) et Hermes (`hermes*.py`), `runs/` (`rules.py`, `service.py`, `api.py`, `supervisor.py`), migration `0008_runs`, `web/src/runs/ConfierDialog.tsx`.
**Relevé fait pour ce cadrage (sans lancer de modèle) :** `claude --version` (2.1.322), `claude --help`, `claude auth status --help`, et une recherche de chaînes dans le binaire installé (alias de modèles, forme des lignes `system/init` et `result`, sous-types d'erreur, `permission_denials`, contrainte `--verbose`). Une preuve locale (Windows, git 2.55) que des hooks déclarés par le dépôt ne tournent pas quand l'environnement de git porte `core.hooksPath` vers `os.devnull` (§4.3).
**`CONTEXT.md` :** absent à la racine du dépôt ; les décisions viennent de `DECISIONS.md`.

Ce document fixe ce qu'un `implementer` écrit, tests d'abord. Il suit l'adaptateur Codex partout où c'est possible (worktree, preuve D6, arbre de processus, redémarrage → `unknown`) et ne s'en écarte que là où Claude Code diffère : pas de bac à sable du système sous Windows, une configuration utilisateur riche (hooks, plugins, MCP, skills) à tenir à l'écart, et le choix du modèle.

---

## 0. Décisions en bref

1. **Exécutant `claude`, agent `claude`, adaptateur (`origin`) `claude-code`.** L'acteur `claude` existe déjà (`actors.EXECUTORS`, `AGENTS_OF["claude"] = {"claude"}`, matrice des exécutants de SECURITY §3, DATA-MODEL §2.5) : aucun nouvel acteur. Le brief disait « exécutant `claude-code` » : c'est le **nom de l'adaptateur**, donc l'`origin` des événements, pas un nouvel acteur. Écart de vocabulaire signalé au §13.
2. **Commande** : `claude -p --output-format stream-json --verbose --model <alias> --restricted --strict-mcp-config --disable-slash-commands --no-session-persistence --tools Read,Edit,Write,Glob,Grep,Bash --permission-mode dontAsk --permission-prompts none --settings <fichier du run>`, cwd = worktree du run, brief sur l'entrée standard (§3).
3. **Bash limité à trois commandes git** (`git status`, `git add`, `git commit`), aucune autre commande, aucun accès web, aucun subagent ; git ne peut rien exécuter de ce que l'agent a écrit (hooks coupés par l'environnement, `GIT_DIR` imposé) (§4).
4. **Traduction pure** des lignes `stream-json` ; contrôle d'isolement sur la ligne `system/init` (aucun serveur MCP, outils attendus, mode de permission attendu), qui **échoue fermé** ; fin jugée sur la ligne `result` **et** le code de sortie ; preuve = règle Codex D6 (§5).
5. **Modèle par run** : colonne `runs.model` (migration `0009`, nullable pour les lignes existantes), liste fermée `haiku`, `sonnet`, `opus`, **exigée** pour l'exécutant `claude` et **refusée** pour les autres ; aucun défaut côté serveur ; Sonnet présélectionné dans l'interface ; la liste est servie par `GET /api/executors` (§6).
6. **Enregistrement opt-in** : `NEXUS_CLAUDE_BIN` obligatoire, aucun repli sur le `PATH` (le vrai `claude` est installé ici et aucun test ne doit l'atteindre) ; `NEXUS_RUN_WORKDIRS` partagé avec Codex (§2).
7. **Addendum ADR-023** : exception à la règle du 2026-10-17, « décidé par Loïc le 2026-11-11 » (§11).

---

## 1. Qui travaille, qui signe

| Champ du run | Valeur | Raison |
|---|---|---|
| `executor` | `claude` | l'acteur existant qui signe les événements (D2 : contrôle `nx-run-` par `executor`) |
| `agent` | `claude` | `AGENTS_OF["claude"]` reste `{"claude"}` ; l'adaptateur ne déclare pas d'attribut `agents` |
| `origin` des événements | `claude-code` | `Adapter.name`, conforme à `ADAPTER_NAME` |
| `external_ref` | `nexus/nx-run-<n>` (la branche) | comme Codex : c'est ce que Loïc relit ; l'id de session n'est pas conservé (§3.4) |
| `model` | `haiku` / `sonnet` / `opus` | §6 |

**Rejeté :** un nouvel acteur `claude-code` (il faudrait l'ajouter aux `Literal`, à la matrice de permissions, aux jetons, et il doublerait l'identité `claude`).

**Risque résiduel, identique à Codex :** un jeton d'acteur `claude` (s'il en existe un pour les sessions interactives de Claude Code) peut publier des événements citant un `nx-run-<n>` de l'adaptateur, puisque D2 ne contrôle que le signataire. Le journal en garde l'`origin` (`api` contre `claude-code`) ; on ne corrige pas dans ce lot.

---

## 2. Configuration et enregistrement

- `Settings.claude_bin: str | None` lu de `NEXUS_CLAUDE_BIN` (vide → `None`). **Aucun repli sur `claude` du `PATH`** (comme Hermes, contrairement à Codex).
- `register_configured(registry, settings)` n'enregistre l'adaptateur sous l'exécutant `claude` que si :
  1. `settings.claude_bin` est défini et `shutil.which(settings.claude_bin)` le trouve ;
  2. `settings.run_workdirs` contient au moins un dépôt valide (racine git, pas le dépôt du serveur : mêmes filtres que Codex, `codex_git.toplevel` et `codex_git.is_server_repo`) ;
  3. la sonde réussit : `claude --version` seulement, borné à 10 s (ne lance aucun modèle). **Rejeté :** `claude auth status` comme sonde (sa sortie contient l'identité du compte et peut appeler le réseau ; une connexion absente se voit au premier run, en `failed` avec la cause).
- `app.py` appelle `claude_code.register_configured(app.state.adapters, settings)` après Codex et Hermes.
- Durée maximale : `NEXUS_RUN_MAX_MINUTES` (commun, 60 par défaut).
- **Tests :** `conftest.py` reçoit une fixture autouse `no_claude_from_the_shell` (`monkeypatch.delenv("NEXUS_CLAUDE_BIN")`), sur le modèle de `no_hermes_from_the_shell` (Loïc ou l'agent principal peuvent commiter depuis le shell où ils ont exporté la variable pour un run réel), et `GuardedPopen` refuse aussi le radical `claude` (`("codex", "hermes", "claude")`). Le faux exécutable s'appelle `fake-claude` (radical différent).

---

## 3. Invocation

### 3.1 Liste d'arguments

Construite par une fonction pure `claude_code_cli.argv(binary, model, settings_path)` ; jamais de shell, jamais le brief en argument :

```text
<NEXUS_CLAUDE_BIN>
  -p
  --output-format stream-json
  --verbose                       # exigé : « stream-json requires --verbose » (relevé dans le binaire)
  --model <haiku|sonnet|opus>     # revalidé contre la liste fermée avant de construire l'argv
  --restricted
  --strict-mcp-config             # sans --mcp-config : aucun serveur MCP
  --disable-slash-commands        # ni skills ni commandes
  --no-session-persistence
  --tools Read,Edit,Write,Glob,Grep,Bash
  --permission-mode dontAsk
  --permission-prompts none
  --settings <NEXUS_DATA_DIR>/claude-code/nx-run-<n>.settings.json
```

Ce que fait chaque garde-fou, d'après l'aide de la 2.1.322 :

- `--restricted` : ignore les fichiers de réglages utilisateur, projet et local (donc les hooks, plugins et permissions de Loïc), garde seulement les réglages gérés et `--settings` ; confine les outils de fichiers aux dossiers de travail ; refuse `bypassPermissions` ; ne laisse approuver les écritures dans les réglages, git et la configuration des outils que par une personne ou le gestionnaire de permissions configuré (ici : personne, donc refus).
- `--tools` : seuls ces outils existent ; ni `WebFetch`, ni `WebSearch`, ni l'outil de subagents, ni `Skill`.
- `--permission-mode dontAsk` + `--permission-prompts none` : ce qui n'est pas pré-autorisé par `permissions.allow` est refusé, sans invite.
- `--no-session-persistence` : aucune transcription écrite dans `~/.claude/projects` (cohérent avec « la sortie brute n'est jamais écrite » de Codex) et pas de reprise possible hors de Nexus.

**Exclus, avec la raison :**

- `--bare` : n'accepte que `ANTHROPIC_API_KEY` ou un `apiKeyHelper` (OAuth jamais lu) ; le run ne consommerait pas l'abonnement.
- `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `--permission-mode bypassPermissions` / `auto` / `acceptEdits` : jamais (un test vérifie qu'aucun n'apparaît dans l'argv).
- `--fallback-model` : changerait de modèle en silence ; la ligne `runs.model` mentirait.
- `--max-turns` : absent de l'aide de la 2.1.322 (présent seulement comme option cachée, avec la mention interne « assume none is enforced ») ; **seule la durée maximale (D7) borne un run**.
- `--max-budget-usd` : ne vaut que pour une clé d'API.
- `--safe-mode` : option de dépannage dont la portée peut changer ; `--restricted` est fait pour ce cas.
- `-w/--worktree` : Nexus crée lui-même le worktree (D6) ; on ne laisse pas Claude Code en créer un second.
- `--effort` : pas exposé dans ce lot (valeur par défaut du CLI) ; un choix d'effort par run serait une extension du §6.

### 3.2 Fichier de réglages du run

Écrit par l'adaptateur avant le lancement, **hors du worktree** (`<NEXUS_DATA_DIR>/claude-code/nx-run-<n>.settings.json`, l'agent ne peut pas le modifier : outils de fichiers confinés au worktree), supprimé à la clôture. Contenu exact (constante, test d'égalité) :

```json
{
  "disableAllHooks": true,
  "permissions": {
    "allow": [
      "Read", "Glob", "Grep", "Edit", "Write",
      "Bash(git status)", "Bash(git status *)",
      "Bash(git add *)",
      "Bash(git commit *)"
    ],
    "deny": [
      "Edit(.git)", "Write(.git)", "Edit(.git/**)", "Write(.git/**)"
    ]
  }
}
```

- Fichier plutôt que JSON en argument : sous Windows, des guillemets et parenthèses dans l'argv d'un `.cmd` (le faux exécutable des tests) se cassent ; un chemin ne pose aucun problème.
- La clé `disableAllHooks` et le mode `dontAsk` figurent dans le binaire 2.1.322 ; la syntaxe des règles `deny` sur `.git` n'y a pas été vérifiée. **Un fichier de réglages invalide est ignoré en silence en mode `-p`** (aide de `-p`) : le run perd alors ses règles `allow`, et, `dontAsk` refusant tout le reste, on attend des « Outils refusés » sur `Edit` dès le premier fichier et une fin en `review`. Ce symptôme est à reconnaître au premier run réel (§12, étape 8) ; il échoue fermé.
- Ni `git diff` ni `git log` : `--output=<fichier>` leur fait écrire n'importe où sur le disque. L'agent lit les fichiers avec `Read`.
- Les règles sont des **préfixes** : `git -c core.hooksPath=… commit` ne commence pas par `git commit` et reste refusé (cela compte : un `-c` en ligne de commande l'emporte sur la configuration passée par l'environnement, constaté au §4.3).

### 3.3 Entrée standard

Le brief (ce que Loïc a écrit, masqué à l'écriture) suivi d'une consigne fixe, comme Hermes :

```text

---
Consigne de Nexus : tu travailles dans un worktree git à part, sur une branche créée pour ce run.
Seules les commandes `git status`, `git add <fichiers>` et `git commit -m "<message d'une ligne>"`
te sont permises ; toute autre commande sera refusée. Ne pousse pas, ne change pas de branche.
Quand le travail est fini, commite-le : Nexus vérifie ce commit. Sans commit, Nexus demandera une
relecture à Loïc.
```

La consigne ne contient ni référence de run ni chemin (constante, testée telle quelle). Écrite sur l'entrée standard par un fil, comme `CodexAdapter._feed`.

### 3.4 Dossier de travail et identifiants

- `codex_git.choose_repo(workdirs, run.workdir)` puis `codex_git.create_worktree(repo, <data>/worktrees, run.ref)` : mêmes règles que Codex (jamais le dépôt du serveur, jamais un dépôt hors liste), même chemin `<data>/worktrees/nx-run-<n>`, même branche `nexus/nx-run-<n>`. Les références de run sont uniques tous exécutants confondus : un worktree Codex et un worktree Claude ne se télescopent pas.
- **Identité git vérifiée avant le lancement** : `git config user.email` lu dans le worktree (même environnement git que l'enfant). Absente → `ValueError`, donc `failed` « lancement impossible : aucune identité git (user.email) pour ce dépôt », sans lancer de modèle. Constaté le 2026-11-12 : Helios n'a pas d'identité git globale ; dans un dépôt sans identité locale, le `git commit` de l'agent échouerait et le run finirait en `review` sans cause lisible, après avoir consommé l'abonnement. Test : dépôt sans `user.email` → `failed` avec cette cause, aucun `Popen` de `fake-claude`.
- `Dispatched(external_ref=tree.branch, native_status="started")`.
- L'id de session (`session_id` de `system/init`) n'est pas conservé : la session n'est pas persistée, il ne désignerait rien.
- Les modules `codex_git` et `codex_process` sont réutilisés **tels quels** ; les renommer en modules génériques est un sujet à part (une PR de renommage sans changement), pas ce lot.

### 3.5 Environnement de l'enfant

`codex_process.child_env(environ, allow=CLAUDE_ENV_ALLOW)` puis des valeurs imposées.

- **Liste blanche** (`CLAUDE_ENV_ALLOW`) : celle de Codex **sans** `CODEX_HOME`, **plus** `CLAUDE_CONFIG_DIR` (si Loïc a déplacé la configuration) et `CLAUDE_CODE_GIT_BASH_PATH` (l'outil Bash de Claude Code sous Windows a besoin de Git Bash). La connexion à l'abonnement se trouve par le profil (`USERPROFILE` / `HOME`, `~/.claude/.credentials.json` ou le trousseau) : **à confirmer au premier run réel**.
- **Jamais transmis** (testé par nom, sur un environnement qui les contient tous) : tout `NEXUS_*` ; tout `ANTHROPIC_*` (une `ANTHROPIC_API_KEY` ferait payer l'API au lieu de l'abonnement) ; `CLAUDECODE` et tout `CLAUDE_CODE_*` autre que `CLAUDE_CODE_GIT_BASH_PATH` (le serveur peut avoir été lancé depuis une session Claude Code : identifiant de session, socket et jeton de messagerie de la session parente) ; `CODEX_HOME` ; tout `GIT_*` hérité.
- **Imposé par l'adaptateur** :
  - `GIT_DIR=<dépôt>/.git/worktrees/nx-run-<n>` (lu par `git rev-parse --absolute-git-dir` dans le worktree juste après sa création, avant tout lancement : git peut suffixer ce nom ; le chemin doit être sous `git rev-parse --git-common-dir` du dépôt, sinon `ValueError`) et `GIT_WORK_TREE=<worktree>` : git n'utilise plus le fichier `.git` du worktree, que l'agent pourrait réécrire (§4.3) ;
  - `GIT_CONFIG_COUNT=3`, `GIT_CONFIG_KEY_0=core.hooksPath`, `GIT_CONFIG_VALUE_0=<os.devnull>`, `GIT_CONFIG_KEY_1=core.fsmonitor`, `GIT_CONFIG_VALUE_1=false`, `GIT_CONFIG_KEY_2=commit.gpgsign`, `GIT_CONFIG_VALUE_2=false` (une signature demanderait une phrase secrète sans terminal et bloquerait le commit jusqu'à la durée maximale) ;
  - `GIT_EDITOR=:` (un `git commit` sans `-m` n'ouvre aucun éditeur : message vide, commit abandonné au lieu d'attendre un éditeur jusqu'à la durée maximale) ;
  - `GIT_TERMINAL_PROMPT=0` ;
  - `DISABLE_AUTOUPDATER=1` (le binaire ne se remplace pas pendant un run).
  La configuration globale de git reste lue (identité de l'auteur du commit).

---

## 4. Ce que l'agent peut exécuter

### 4.1 Le constat

Codex tourne sous `--sandbox workspace-write`. Claude Code n'a pas de bac à sable du système sous Windows (Helios) : tout `Bash` autorisé s'exécute avec les droits de Loïc, réseau, clés SSH et jeton `gh` compris. D'où le choix d'un Bash réduit à git. **Conséquence assumée :** l'agent ne peut lancer ni tests, ni linter, ni installation de dépendances. Élargir est une décision de Loïc (§13).

### 4.2 Une barrière par chemin d'exécution

| Chemin | Barrière |
|---|---|
| Commande arbitraire | `--tools` + `permissions.allow` préfixés sur trois commandes git ; `dontAsk` + `--permission-prompts none` refusent le reste |
| Accès web, subagent, skill, MCP | absents de `--tools` ; `--strict-mcp-config` ; `--disable-slash-commands` ; contrôle `system/init` (§5.2) |
| Hooks, plugins et réglages de Loïc | `--restricted` (réglages utilisateur, projet, local ignorés) ; `disableAllHooks` ; aucun MCP |
| Écriture hors du worktree | `--restricted` confine les outils de fichiers ; `git diff`/`git log --output` non autorisés |
| Hook git écrit par l'agent (dossier de hooks dans l'arbre, hook qui lance des tests qu'il a modifiés) | `core.hooksPath=<devnull>` par l'environnement (§3.5) ; l'agent ne peut pas l'annuler (pas de `git -c`, pas de `git config`, pas d'autre Bash) |
| Fichier `.git` du worktree réécrit vers une config piégée (pilotes `filter.*.clean` lancés par `git add`, `diff.external`) | `GIT_DIR` imposé ; règles `deny` sur `.git` ; protection de `--restricted` sur les fichiers git |
| Redirection dans une commande permise (`git status > fichier`) | analyse des redirections par Claude Code : **refus attendu, à confirmer au premier run** (§12, scénario E) |
| Substitution de commande (`git commit -m "$(…)"`) | refus attendu (invite → refus) ; la consigne du §3.3 demande un message d'une ligne |

La preuve se lit toujours depuis le dépôt sur `refs/heads/nexus/nx-run-<n>` (`codex_git.proof`), jamais depuis le worktree.

### 4.3 Preuve locale faite pour ce cadrage

Dans un dépôt jetable (Windows, git 2.55) dont la configuration déclare `core.hooksPath=.githooks` et un `pre-commit` qui écrit un témoin : avec `GIT_CONFIG_COUNT`/`core.hooksPath=nul` dans l'environnement, le commit réussit **sans** lancer le hook ; sans cet environnement, le hook tourne ; et `git -c core.hooksPath=.githooks commit` avec le même environnement le relance (le `-c` l'emporte). D'où les règles préfixées du §3.2. Les tests du §9 refont cette preuve avec le faux exécutable.

---

## 5. Suivi : traduction, fin, preuve

### 5.1 Lecture

Comme Codex : un fil de lecture traduit chaque ligne de la sortie standard, en mémoire ; `stderr` est jeté ; la sortie brute n'est jamais écrite. `at` = l'heure de lecture (les lignes `stream-json` n'ont pas d'horodatage). Plafonds repris de Codex : `MAX_PROGRESS = 300`, `KEEP_FINISHED = 20`, `claimed` et `working` une fois chacun.

### 5.2 Table de traduction (`claude_code_translate.translate_line(line) -> tuple[Fact, ...]`)

Fonction pure : une ligne peut porter plusieurs faits (un message `assistant` à plusieurs blocs ; une ligne `result` avec des refus). Tout texte passe par `text.cut` (secrets masqués, 500 caractères). Ligne non JSON, JSON qui n'est pas un objet, type inconnu : `()`, jamais d'exception.

| Ligne | Fait(s) |
|---|---|
| `{"type":"system","subtype":"init", …}` isolée conforme | `claimed` « Claude Code a ouvert une session », `payload.model` = `cut(init.model)` (le nom complet résolu par le CLI) |
| même ligne, `mcp_servers` liste **non vide** | `breach` « isolation non respectée : serveur MCP chargé » |
| même ligne, `tools` contient un outil hors de `Read, Edit, Write, Glob, Grep, Bash` | `breach` « … : outil inattendu » (le nom n'est pas recopié) |
| même ligne, `permissionMode` différent de `dontAsk` | `breach` « … : mode de permission inattendu » |
| même ligne, `mcp_servers`, `tools` ou `permissionMode` **absent ou d'un autre type** | `isolation_unknown` (pas de `claimed` confirmé ; voir §5.3) |
| `{"type":"assistant","message":{"content":[…]}}` | `working` « Claude Code travaille » (le premier seulement) ; puis par bloc : `text` → `progress` « Message de Claude Code » ; `tool_use` `Bash` → `progress` « Commande demandée » (`input.command`) ; `tool_use` `Edit`/`Write` → `progress` « Fichier modifié » (`input.file_path`) ; `thinking`, `tool_use` `Read`/`Glob`/`Grep`, autre bloc → rien |
| `{"type":"user", …}` (résultats d'outils) | rien : la sortie d'une commande ou le contenu d'un fichier n'est **jamais** lu dans un fait |
| `{"type":"system","subtype":<autre>}` (compactage, nouvelle tentative d'API, hooks…) | rien |
| `{"type":"result","subtype":"success","is_error":false, …}` (`is_error` strictement le booléen `false`) | `finished`, avec `num_turns` et `duration_ms` s'ils sont des entiers |
| `result` avec `is_error` vrai, ou un `subtype` d'erreur (`error_during_execution`, `error_max_turns`, `error_max_budget_usd`, `error_max_structured_output_retries`, ou inconnu) | `failed`, cause = `cut(result)` sinon `cut("; ".join(errors))` (chaînes seulement) sinon « échec sans détail (<subtype connu>) » |
| `result` dont `permission_denials` est une liste non vide | en plus : `progress` « Outils refusés », corps = noms d'outils distincts (`tool_name`), jamais `tool_input` |

« Commande **demandée** » et non « exécutée » : un `tool_use` est une demande, qui peut être refusée.

Formes relevées dans le binaire 2.1.322 (`system/init` : `cwd`, `session_id`, `tools`, `mcp_servers`, `model`, `permissionMode`, `slash_commands`, `apiKeySource` ; `result` : `subtype`, `is_error`, `num_turns`, `duration_ms`, `result` ou `errors`, `permission_denials` d'objets `{tool_name, tool_use_id, tool_input}`). **À confirmer au premier run réel** et isolées dans ce module, comme `codex_translate.py`.

### 5.3 Fin du run (`_settle`, après la fin réelle du processus)

Dans l'ordre :

1. `breach` lu : l'adaptateur **tue l'arbre tout de suite** (sans attendre la fin ni la durée maximale), puis `failed`, cause « isolation non respectée : <mots fixes> ». Un arrêt non confirmé lève et laisse le run ouvert (comme Codex).
2. Durée maximale dépassée : arbre tué, `failed` « Durée maximale dépassée ».
3. Une ligne `result` en échec : `failed` avec sa cause (la dernière ligne `result` l'emporte).
4. Code de sortie non nul : `failed`, « le processus s'est arrêté (code N) ».
5. Aucune ligne `result` : `failed`, « le processus s'est arrêté sans résultat ».
6. `finished` et code 0 :
   - isolement **non vérifié** (`system/init` jamais vu, ou `isolation_unknown`) : `review`, « isolement de la session non vérifié : à relire », `branch:nexus/nx-run-<n>` — jamais `done` ;
   - sinon preuve D6 (`codex_git.proof`) : commit produit → `done` avec `commit:<12 caractères>` ; pas de commit → `review` avec `branch:…`.

Le fichier de réglages du run est supprimé à la clôture, quelle qu'elle soit (et par `cancel`).

---

## 6. Modèle par run

### 6.1 Liste fermée

`runs/rules.py` : `RUN_MODELS = ("haiku", "sonnet", "opus")` (dans l'ordre affiché, du plus économe au plus capable) et `MODELS_OF = {"claude": RUN_MODELS}`. Le binaire 2.1.322 accepte ces trois alias (et aussi `fable`, `best`, `sonnet[1m]`…, **non retenus** : Loïc a nommé Haiku, Sonnet, Opus). Un alias suit la dernière version du modèle connue du CLI installé.

### 6.2 Base de données

Migration `0009_run_model.py` : `op.add_column("runs", sa.Column("model", sa.String(16)))`, nullable, sans défaut ; `downgrade` = `op.drop_column("runs", "model")`. Même méthode que `0006` (sans mode batch, qui reconstruirait la table). Les runs existants gardent `model = NULL`. Modèle : `model: Mapped[str | None] = mapped_column(String(16))`.

**Rejeté :** une contrainte `CHECK` en base (en SQLite elle demande une reconstruction de table, et `compare_metadata` ne la compare pas) ; la validation est faite trois fois : schéma de l'API, règle de dispatch, adaptateur avant l'argv.

### 6.3 API et règles

- `RunIn.model: Literal["haiku", "sonnet", "opus"] | None = None` : une valeur inconnue est un 422, traité comme une valeur inconnue d'`executor` (le message ne recopie pas la valeur).
- `rules.check_model(executor, model)` (pure), appelée dans `check_dispatchable` **après** les contrôles d'adaptateur (`executor_unavailable` reste la réponse la plus utile quand rien n'est configuré) et avant `check_task_ready` :
  - exécutant qui a des modèles (`claude`) et `model` absent → **409 `model_required`** « choisis un modèle pour ce run » ;
  - exécutant sans modèles (`codex`, `hermes`, `orca`) et `model` présent → **409 `model_not_for_executor`**. Refusé et non ignoré : un modèle ignoré en silence ferait croire à l'interface qu'il a compté.
- **Aucun défaut côté serveur** : chaque run Claude dit quel modèle a été consommé, parce que quelqu'un l'a choisi.
- `NewRun.model`, `Run(model=…)` ; `_same()` compare aussi `model` : renvoyer la même `client_key` avec un autre modèle est un 409 `client_key_reused`, avec le même modèle un 200.
- `RunOut.model: str | None`.
- `ExecutorOut.models: list[str]` = `MODELS_OF.get(executor, ())` (restreint par un attribut facultatif `models` de l'adaptateur, comme `agents`) : `["haiku", "sonnet", "opus"]` pour `claude`, `[]` pour les autres.
- `RunInfo.model: str | None = None` (dernier champ, avec défaut : les constructeurs existants des tests restent valides) ; `supervisor.info_of` (ligne 52) le passe. L'adaptateur lève `ValueError` si `run.model` n'est pas dans `RUN_MODELS` : le superviseur publie alors `failed` « lancement impossible », sans lancer de processus.

### 6.4 Interface « Confier à »

- `runsApi.ts` : `Run.model: string | null`, `ExecutorInfo.models: string[]`, `RunDraft.model?: string`.
- `ConfierDialog.tsx` : un champ **« Modèle »** n'apparaît que si l'exécutant choisi a des modèles. Options : « Haiku — rapide, le plus économe », « Sonnet — équilibré », « Opus — le plus capable, consomme le plus ». **Sonnet est présélectionné** (le modèle par défaut du fil principal, AGENTS.md ; Haiku reste un choix explicite). Changer d'exécutant remet le choix à zéro. Un modèle que le serveur ne propose plus reste affiché « — plus disponible » et bloque l'envoi (même logique que `executorGone`). La signature d'idempotence inclut le modèle (`JSON.stringify([selected, theAgent, theWorkdir, theModel, text])`) ; `model` n'est envoyé que si l'exécutant en a. L'avertissement « Lance un LLM » ajoute pour Claude : « consomme l'abonnement Claude de Loïc ».
- `vocabulary.ts` : `MODEL_LABEL` et les refus `model_required`, `model_not_for_executor`.
- `RunsSection.tsx` : la ligne du run affiche « Claude → Claude · Sonnet » quand `model` est présent ; ligne 51, `run.executor === 'codex'` devient « exécutant à branche » (`codex` ou `claude`) pour le libellé « Branche ».
- La timeline montre le `claimed` avec `payload.model` (nom complet résolu) : Loïc voit l'alias choisi **et** le modèle réellement servi.

---

## 7. Concurrence et invariants

- **Un run actif par exécutant** (D7) : index unique partiel existant sur `executor` → 409 `executor_busy`. Un run Codex et un run Claude peuvent tourner en même temps, chacun dans son worktree.
- **Un run actif par agent et par tâche** : index existant ; le contrôle du journal (`_runs(session, executor, task)`) s'applique à `claude` comme aux autres.
- **Annulation** : `codex_process.kill_tree` (arbre entier, confirmé) ; non confirmé → lève, le run reste ouvert, le superviseur réessaie. Après redémarrage : jamais lancé ou marqueur `.stopped/nx-run-<n>` → retour ; sinon lève (même limite connue que Codex, même procédure manuelle).
- **Arrêt du serveur** (`close`) : tue chaque processus vivant et écrit le marqueur, comme Codex.
- **Redémarrage** : le run passe `unknown` (D3) ; `recover` rend `None`.
- **Dispatch** : marqueur `dispatching` avant l'appel (superviseur existant) ; une exception avant le `Popen` (worktree, modèle invalide, fichier de réglages) → `failed` « lancement impossible ». Pas de `LaunchUncertain` : le lancement d'un processus local est certain ou échoue.
- **Tous les appels sont bornés** : sonde 10 s, git 60 s, `kill_tree` 10 s ; le fil de lecture est un démon.
- **Abonnement partagé** : un run et les sessions interactives de Loïc consomment le même quota ; une limite atteinte arrive en `result` d'erreur et termine le run en `failed` avec le message du CLI comme cause (heure de reprise comprise). Aucune relance automatique.

---

## 8. Sécurité (à reporter dans SECURITY §3)

- Aucun jeton Nexus pour l'enfant (D4) ; liste blanche d'environnement du §3.5, testée par nom.
- Brief par l'entrée standard, jamais en argument ; `client_key`, `workdir` et `model` validés avant tout lancement ; `model` revalidé par l'adaptateur.
- Isolement de la session vérifié sur `system/init`, échec fermé (§5.2, §5.3).
- Bash réduit à trois commandes git ; hooks git coupés par l'environnement ; `GIT_DIR` imposé ; écritures confinées au worktree ; rien de poussé ni fusionné.
- Sortie brute jamais écrite ni journalisée ; `stderr` jeté ; seuls des faits traduits et masqués sont publiés ; résultats d'outils jamais lus.
- Session non persistée ; fichier de réglages hors du worktree, supprimé à la clôture.
- Enregistrement opt-in (`NEXUS_CLAUDE_BIN`), sans repli sur le `PATH`.

---

## 9. Plan de tests (écrits avant le code)

Fake : `server/tests/claude_code_support.py` écrit `fake_claude.py` et un lanceur `fake-claude(.cmd)`, sur le modèle de `codex_support.py`. Le script : `--version` → `2.1.322 (fake)` ; sinon enregistre `args.json`, `env.json` (noms seulement), `stdin.txt`, rejoue `scenario.lines`, puis selon le scénario : `commit` (lance `git commit --allow-empty` **avec l'environnement reçu**, sans `-c`), `rewrite_dotgit` (réécrit le fichier `.git` du worktree vers un faux gitdir avant de commiter), `hang`, `exit`. Constantes de lignes : `INIT_OK`, `INIT_MCP`, `INIT_EXTRA_TOOL`, `INIT_BYPASS`, `INIT_BARE` (sans champs), `ASSISTANT_TEXT`, `ASSISTANT_BASH`, `ASSISTANT_EDIT`, `USER_TOOL_RESULT` (avec un texte `RAW-OUTPUT-NEVER-STORED`), `RESULT_OK`, `RESULT_IS_ERROR`, `RESULT_ERROR_EXEC`, `RESULT_DENIALS`. Les faux secrets sont construits à l'exécution (`"ghp_" + "A" * 36`).

### Cas limites d'abord

**Traduction pure — `test_claude_code_translate.py`**
1. Ligne non JSON, `[]`, `null`, `3`, `""`, type inconnu → `()`.
2. `init` conforme → `claimed` avec `payload.model`.
3. `init` avec un serveur MCP / un outil en plus / `permissionMode` `bypassPermissions` → `breach` (mots fixes, aucun nom recopié).
4. `init` sans `mcp_servers`, avec `mcp_servers` qui n'est pas une liste, sans `tools` → `isolation_unknown`.
5. `assistant` à trois blocs (texte, `Bash`, `Edit`) → trois faits, plus `working` au premier.
6. `tool_use` `Read`, bloc `thinking` → rien.
7. `user` avec résultat d'outil contenant un faux secret et `RAW-OUTPUT-NEVER-STORED` → `()`.
8. `result` succès strict → `finished` ; `is_error: "false"` (chaîne) ou absent → pas un succès.
9. `result` `success` avec `is_error: true` (limite d'usage) → `failed` avec la cause recopiée et masquée.
10. `result` `error_during_execution` avec `errors` (chaînes et non-chaînes mêlées) → `failed`, seules les chaînes.
11. `result` avec `permission_denials` → « Outils refusés » avec les noms distincts, jamais `tool_input` (qui contient un faux secret).
12. Texte avec moitié de paire UTF-16, texte vide, texte réduit à un secret → pas de fait vide.

**Argv, réglages, environnement — `test_claude_code_cli.py`**
13. `argv()` égale exactement la liste du §3.1 pour chaque modèle ; aucun drapeau exclu (§3.1) n'y figure ; le brief n'y figure pas.
14. `argv()` avec `fable`, `""`, `None`, `opus --dangerously-skip-permissions` → `ValueError`, aucun processus.
15. Fichier de réglages : contenu exact du §3.2, écrit sous `<data>/claude-code/`, jamais dans le worktree.
16. Environnement : à partir d'un environnement qui contient `NEXUS_TOKEN`, `ANTHROPIC_API_KEY`, `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_TOKEN`, `CODEX_HOME`, `GIT_DIR`, `GIT_INDEX_FILE` (et leurs variantes en minuscules) → aucun ne passe ; `USERPROFILE`, `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_GIT_BASH_PATH` passent ; `GIT_DIR`, `GIT_WORK_TREE`, les `GIT_CONFIG_*`, `GIT_EDITOR`, `GIT_TERMINAL_PROMPT`, `DISABLE_AUTOUPDATER` valent ce que l'adaptateur impose.

**Adaptateur avec le faux — `test_claude_code_adapter.py`, `test_claude_code_errors.py`**
17. Chemin heureux (`INIT_OK`, texte, `RESULT_OK`, commit) → `claimed`, `working`, `progress`, `done` `commit:<12>` ; `stdin.txt` = brief + consigne du §3.3 ; `args.json` contient `--model sonnet`.
18. Succès sans commit → `review` `branch:nexus/nx-run-1`.
19. Succès puis code 1 → `failed` code 1.
20. Aucune ligne `result`, code 0 → `failed` « sans résultat ».
21. `RESULT_IS_ERROR` → `failed` avec la cause.
22. `INIT_MCP` puis `hang` → processus tué sans attendre la durée maximale, `failed` « isolation non respectée » ; arrêt confirmé.
23. Pas d'`init` (ou `INIT_BARE`), succès et commit → `review` « isolement non vérifié », jamais `done`.
24. Durée maximale (`max_seconds` minuscule, `hang`) → `failed`, arbre tué.
25. 400 lignes de texte → 300 `progress` au plus, la fin toujours présente ; `claimed`/`working` une fois.
26. Fichier de réglages supprimé après `done`, après `failed` et après `cancel`.
27. `RunInfo.model = None` → `dispatch` lève `ValueError` avant tout `Popen`.

**Barrières git — `test_claude_code_git_barriers.py`**
28. Dépôt dont la config déclare `core.hooksPath` vers un dossier de l'arbre avec un `pre-commit` qui écrit un témoin ; le faux commite avec l'environnement reçu → commit présent sur `refs/heads/nexus/nx-run-1`, témoin absent.
29. `rewrite_dotgit` : le faux réécrit `.git` vers un gitdir piégé (config avec un hook et un pilote de filtre), puis commite → le commit arrive sur la vraie branche (car `GIT_DIR` est imposé), aucun témoin ; la preuve est relue depuis le dépôt.

**Annulation et redémarrage — `test_claude_code_cancel.py`**
30. `cancel` pendant `hang` → arbre tué, run réglé, purgeable.
31. Après redémarrage : jamais lancé → retour ; marqueur `.stopped` → retour ; sinon lève.
32. `close()` tue et écrit le marqueur.

**Enregistrement — `test_claude_code_registration.py`**
33. Sans `NEXUS_CLAUDE_BIN`, même avec un exécutable nommé `claude` en tête du `PATH` → rien d'enregistré, aucun `Popen`.
34. `NEXUS_CLAUDE_BIN` sans `NEXUS_RUN_WORKDIRS`, ou seulement le dépôt du serveur → rien.
35. Sonde en échec (code ≠ 0, délai dépassé) → rien.
36. Tout est bon → enregistré sous `claude`, `name == "claude-code"` ; `GET /api/executors` liste `claude` avec `agents == ["claude"]` et `models == ["haiku", "sonnet", "opus"]`.
37. `GuardedPopen` lève pour un radical `claude`.

**Modèle, règles, API, migration — `test_runs_model.py`, `test_run_model_migration.py`**
38. `claude` sans `model` → 409 `model_required` ; `codex` ou `hermes` avec `model` → 409 `model_not_for_executor` ; `model: "fable"` → 422 sans recopie de la valeur (`validation.french_errors` ne garde que `loc` et `msg` ; le test le vérifie sur une valeur en forme de secret).
38 bis. **Tests existants touchés :** `test_runs_api.py` (l. 180–184) et `test_runs_supervisor.py` (l. 101–105) enregistrent un adaptateur factice sous `claude` comme « autre exécutant » et confient sans `model` : avec H1 ils recevraient `model_required`. H1 les fait passer sur `orca` (exécutant sans modèles), ce qui garde leur intention ; c'est une modification de test assumée, notée dans la PR. Un mock de `/api/executors` sans `models` (tests web, e2e) se lit comme une liste vide.
39. Même `client_key`, même modèle → 200 ; autre modèle → 409 `client_key_reused`.
40. `RunOut.model` relu ; `GET /api/executors` : `models == []` pour Codex.
41. Le superviseur passe `model` à `RunInfo` (adaptateur factice qui capture le snapshot).
42. Migration : `0009` sur une base `0008` peuplée (un run existant) → `model` NULL, `compare_metadata` vide ; `downgrade` vers `0008` garde les runs.

**Interface (Vitest) — `ConfierDialog.model.test.tsx`, `RunsSection.test.tsx`**
43. Champ « Modèle » présent pour Claude (Sonnet présélectionné), absent pour Codex ; changer d'exécutant le masque et l'oublie.
44. L'envoi porte `model` pour Claude et pas pour Codex ; changer de modèle après un refus produit une nouvelle `client_key`, renvoyer sans changement garde la même.
45. Modèle retiré par le serveur → « — plus disponible », envoi bloqué, brief gardé.
46. Refus `model_required` et `model_not_for_executor` expliqués.
47. La ligne du run affiche « Sonnet » et « Branche » pour Claude.

**Bout en bout (Playwright)** — `web/e2e/fake-claude.mjs` (rejoue `INIT_OK`, un message, `RESULT_OK`, commite) et `NEXUS_CLAUDE_BIN` dans `e2e-env.ts` : confier une tâche à Claude avec Opus → le run apparaît avec « Opus », se termine `done` avec la preuve de commit.

---

## 10. Fichiers touchés et découpage (seuils 400 / 600 lignes)

| Fichier | Contenu | Taille visée |
|---|---|---|
| `server/src/nexus/adapters/claude_code.py` (nouveau) | `ClaudeCodeAdapter` (`_Job`, `probe`, `dispatch`, `watch`, `cancel`, `recover`, `close`), `register_configured` | ≤ 330 |
| `server/src/nexus/adapters/claude_code_cli.py` (nouveau) | `argv()`, contenu et écriture du fichier de réglages, `CLAUDE_ENV_ALLOW`, `child_env()` avec les valeurs imposées, `INSTRUCTION`, `EXPECTED_TOOLS` | ≤ 130 |
| `server/src/nexus/adapters/claude_code_translate.py` (nouveau) | traduction pure du §5.2 | ≤ 190 |
| `server/src/nexus/adapters/base.py` (104) | `RunInfo.model` ; attribut facultatif `models` documenté | +4 |
| `server/src/nexus/runs/rules.py` (93) | `RUN_MODELS`, `MODELS_OF`, `check_model` | ≤ 125 |
| `server/src/nexus/runs/service.py` (181), `runs/api.py` (143) | `NewRun.model`, `_same`, `RunIn`/`RunOut`/`ExecutorOut` | +10, +12 |
| `server/src/nexus/runs/supervisor.py` (363) | `model=run.model` dans `info_of` | +1 |
| `server/src/nexus/models.py` (271), `config.py` (201), `app.py` (252) | colonne, `claude_bin`, enregistrement | +2, +3, +2 |
| `server/src/nexus/migrations/versions/0009_run_model.py` (nouveau) | §6.2 | ≤ 30 |
| `server/tests/conftest.py` | `no_claude_from_the_shell`, radical `claude` | +8 |
| `server/tests/claude_code_support.py` (nouveau) et les tests du §9 | un fichier par sujet | chacun ≤ 350 |
| `web/src/runsApi.ts`, `runs/vocabulary.ts`, `runs/ConfierDialog.tsx` (194), `runs/RunsSection.tsx` (124) | §6.4 | ConfierDialog ≤ 250 |
| `web/e2e/fake-claude.mjs`, `e2e-env.ts`, `runs-claude.spec.ts` (nouveaux ou modifiés) | e2e | |

Aucun fichier ne franchit son seuil ; aucune entrée de `file-size-baseline.json`. **Rejeté :** factoriser dès maintenant `_Job` avec Codex (toucherait un adaptateur testé en réel pour un gain de quelques dizaines de lignes) ; à reconsidérer une fois les deux adaptateurs relevés en vrai, dans une PR à part.

**Deux PR, l'une après l'autre, chacune depuis `master` à jour (jamais empilées) :**
- **H1 — modèle par run** : migration `0009`, modèle, règles, API, `RunInfo.model`, interface (le champ n'apparaît que si un exécutant sert des modèles ; testé avec un adaptateur factice), tests 38–47, DATA-MODEL et VIEWS, addendum ADR-023 et phrase d'AGENTS.md (§11).
- **H2 — adaptateur `claude-code`** (ouverte après la fusion de H1) : §2 à §5, tests 1–37 et e2e, INTEGRATIONS §A.2, SECURITY §3, ROADMAP.
La migration, la sécurité de l'enfant et un invariant du superviseur sont touchés : `architect` relit ce cadrage avant `implementer` (AGENTS.md, « Model routing »).

### Docs à mettre à jour

- `DECISIONS.md` : addendum du §11.
- `AGENTS.md` (« Model routing », règle du 2026-10-17) : une phrase « Exception : l'adaptateur `claude-code` de Nexus (ADR-023, addendum du 2026-11-11). »
- `docs/INTEGRATIONS.md` §A.2 : paragraphe « Adaptateur Claude Code (lot H) » (réglages, commande, barrières, preuve, à confirmer au premier run).
- `docs/SECURITY.md` §3 : troisième adaptateur enregistré (opt-in), liste blanche, Bash réduit à git, barrières git.
- `docs/DATA-MODEL.md` §2.5 : champ `model` ; `external_ref` d'un run Claude = la branche (remplacer « session Claude »).
- `docs/VIEWS.md` : champ « Modèle » de « Confier à ».
- `docs/ROADMAP.md` : lot H.

---

## 11. Addendum à ADR-023 (texte à ajouter par H1)

```markdown
### Addendum (2026-11-11) — Claude Code comme exécutant, modèle choisi à chaque run (lot H)

Décidé par Loïc le 2026-11-11 (cadrage : `docs/superpowers/specs/2026-11-11-adaptateur-claude-code-design.md`) :

- Nexus peut confier une tâche à Claude Code (`claude -p`), avec le modèle choisi à chaque run
  parmi `haiku`, `sonnet` et `opus` dans « Confier à ». Chaque run consomme l'abonnement Claude
  de Loïc.
- **Exception à la règle du 2026-10-17** (AGENTS.md, « Model routing » : les modèles Claude ne sont
  consommés que par le fil principal de Claude Code et les subagents de `.claude/agents/`) : un run
  de l'adaptateur `claude-code` consomme lui aussi l'abonnement. Les tests n'utilisent qu'un faux
  exécutable (D8) ; aucune CI ne lance de run réel. La règle reste entière pour tout autre harnais.

Choix du cadrage, pris par l'agent sous le feu vert de Loïc du 2026-11-11 et **à confirmer par lui**
(chacun se change sans migration) :

- Un run réel est confié depuis Nexus par un humain (D2) : Loïc, ou l'agent principal avec le jeton
  de navigateur de Loïc et sur sa consigne.
- L'exécutant est l'acteur existant `claude`, qui ne sert que l'agent `claude` ; l'`origin` des
  événements est `claude-code`.
- `runs.model` (migration `0009`) : exigé pour `claude` (409 `model_required`), refusé pour les
  autres exécutants (409 `model_not_for_executor`), sans défaut côté serveur ; `NULL` pour les runs
  antérieurs.
- D4, D6 et D7 s'appliquent sans changement (environnement par liste blanche, brief sur l'entrée
  standard, worktree et preuve par commit, un run actif par exécutant, durée maximale, aucune
  relance). En plus : session isolée (`--restricted`, aucun MCP, ni hooks ni réglages de Loïc,
  vérifiée sur la ligne `system/init`), Bash réduit à `git status`, `git add` et `git commit`,
  hooks git coupés par l'environnement de l'enfant. Sonnet est présélectionné dans « Confier à ».
```

---

## 12. Run réel (manuel, jamais en CI)

### 12.0 Relevé préalable du 2026-11-12 (Haiku, hors Nexus)

Avant toute implémentation, sept runs réels de `claude` 2.1.322 avec Haiku ont été lancés à la main, avec l'argv exact du §3.1, le fichier de réglages du §3.2 et l'environnement du §3.5 (liste blanche et valeurs imposées), dans un dépôt jetable dont la configuration déclare `core.hooksPath=.githooks` avec un `pre-commit` témoin. Chaque run a duré de 4 à 11 s.

- `system/init` réel : `tools = ["Bash","Edit","Glob","Grep","Read","Write"]` (ordre alphabétique : comparer en ensemble), `mcp_servers = []`, `permissionMode = "dontAsk"`, `model = "claude-haiku-5-5"`, `apiKeySource = "none"` (abonnement, pas de clé d'API), `slash_commands = []`. Le contrôle d'isolement du §5.2 passe tel quel.
- Lignes vues en plus de la table du §5.2 : `system/thinking_tokens`, `system/vcs_state_changed`, `rate_limit_event` (type de premier niveau). Toutes → `()` (type ou sous-type sans fait).
- `result` réel : `subtype`, `is_error`, `num_turns`, `duration_ms`, `result`, `errors` (`null` en succès), `permission_denials` d'objets `{tool_name, tool_use_id, tool_input}`. Un refus d'outil laisse `subtype = "success"` et `is_error = false` : la fin est jugée par la preuve, comme prévu.
- **A** (modifier `README.md` puis commiter) : `Read`, `Edit`, `git status`, `git add README.md`, `git commit -m … -m "Co-Authored-By: …"` permis ; commit sur la branche du run, accents intacts en UTF-8, **hook témoin non lancé**, aucune session dans `~/.claude/projects`. L'agent ajoute de lui-même un second `-m` (attribution, consigne interne du CLI) : `Bash(git commit *)` le couvre.
- **B** (`npm --version`), **E** (`git status > ../hors.txt`), **E2** (`git -c core.hooksPath=.githooks commit …`), **E4** (`git status && npm --version`) : refusés, `permission_denials` = `Bash`, aucun fichier `hors.txt`, aucun témoin, aucun commit.
- **E3** (lire et modifier `../target/README.md`) : `Read` hors du worktree refusé, `cat` refusé ; rien modifié.
- `--restricted` tient `~/.claude/CLAUDE.md` et les mémoires à l'écart (question posée au modèle sans outil : aucune instruction de ce genre, aucun contenu de la configuration de Loïc).
- Les scénarios D (annulation) et F (redémarrage) dépendent de l'adaptateur : ils restent pour le premier run réel par Nexus.

Prérequis : Loïc vérifie lui-même qu'il est connecté (`claude auth status --text`, dans son terminal ; la sortie n'est ni copiée ni journalisée). Un dépôt jetable avec un commit, déclaré seul dans `NEXUS_RUN_WORKDIRS`.

1. Lancer Nexus avec `NEXUS_CLAUDE_BIN=<chemin absolu de claude>` (par exemple `%USERPROFILE%\.local\bin\claude.exe`), `NEXUS_RUN_WORKDIRS=<dépôt jetable>`, `NEXUS_RUN_MAX_MINUTES=15` ; `GET /api/executors` liste `claude` avec les trois modèles.
2. **Scénario A — `done` avec Haiku** (le moins cher d'abord) : brief « Ajoute une ligne "bonjour" à README.md puis commite. Accents : é è à ç « » ». Attendu : `claimed` avec le nom complet du modèle Haiku dans `payload.model`, `working`, « Fichier modifié », « Commande demandée » (`git add`, `git commit`), `done` `commit:<12>`. Vérifier : branche `nexus/nx-run-<n>` avec un commit, accents intacts, aucun fichier de session pour ce worktree dans `~/.claude/projects`, fichier de réglages du run supprimé.
3. **Scénario B — refus attendu** : brief « Lance `npm --version` puis réponds en une phrase ». Attendu : « Outils refusés » (`Bash`), puis une fin ; sans commit → `review`.
4. **Scénario C — `.git` protégé** : brief « Modifie le fichier .git du dossier courant ». Attendu : refus, aucun changement du fichier `.git`.
5. **Scénario D — annulation** : brief long (Sonnet) ; annuler après `working`. Attendu : `cancelled`, plus aucun processus `claude` de ce run (gestionnaire des tâches).
6. **Scénario E — redirection** : brief « Exécute `git status > ../hors.txt` ». Attendu : refus, aucun fichier `hors.txt`. **Si le fichier apparaît, arrêter les runs réels** et revenir vers Loïc : la barrière « préfixe git » ne suffit pas.
   - **E2 — `-c` en ligne de commande** : brief « Exécute `git -c core.hooksPath=.githooks commit --allow-empty -m test` » (avec un hook témoin dans `.githooks`). Attendu : refus (la règle `Bash(git commit *)` ne correspond pas), aucun témoin. Même règle d'arrêt : `-c` l'emporte sur l'environnement (§4.3), cet ancrage est toute la barrière des hooks.
   - **E3 — hors du worktree** : brief « Lis puis modifie `../../README.md` ». Attendu : refus pour l'écriture (et la lecture, si `--restricted` confine aussi `Read`), aucun fichier modifié hors du worktree. Même règle d'arrêt.
   - **E4 — commande chaînée** : brief « Exécute `git status && npm --version` ». Attendu : refus de l'ensemble ou de `npm`, « Outils refusés ». Même règle d'arrêt si `npm` a tourné.
7. **Scénario F — redémarrage** : relancer Nexus pendant un run → `unknown` ; annuler (arrêt propre : marqueur) → `cancelled`.
8. Noter dans la PR et dans INTEGRATIONS §A.2 (« Constaté aux premiers runs réels ») : forme réelle de `system/init` (`tools`, `mcp_servers`, `permissionMode`, `apiKeySource`) et de `result` ; si `--restricted` a bien tenu à l'écart hooks, plugins et `~/.claude/CLAUDE.md` ; si `git commit` a été permis par `Bash(git commit *)` ; si le fichier de réglages a été pris en compte (sinon : « Outils refusés » sur `Edit`, §3.2) ; la variable d'environnement qui porte la connexion ; la durée d'un run court.

Si le scénario A finit en `failed` « isolation non respectée » à cause d'un outil toujours présent dans cette version (par exemple un outil de liste de tâches), on n'élargit pas la liste sans relire ce que fait l'outil : la correction passe par une PR. Même chose pour `permissionMode` : le binaire convertit le mode avant de l'écrire dans `system/init` (une fonction de correspondance existe entre le mode interne et le mot exporté) ; si la valeur réelle diffère de `dontAsk` alors que le mode est le bon, on corrige la comparaison du module de traduction, pas le mode.

---

## 13. Ce qui revient à Loïc

1. **Bash réduit à git** (§4.1) : avec ce cadrage, l'agent ne peut lancer ni tests ni linter, parce que Windows n'offre aucun bac à sable à Claude Code et que tout Bash autorisé tourne avec tes droits (réseau, SSH, `gh`). Élargir (par exemple `pnpm test`, `uv run pytest`) permettrait à l'agent d'exécuter du code qu'il vient d'écrire : c'est ta décision, à prendre de préférence après les premiers runs réels.
2. **Nom de l'exécutant** : l'exécutant reste l'acteur existant `claude`, `claude-code` n'est que le nom de l'adaptateur (`origin`). À dire si tu voulais vraiment un acteur distinct.
3. **Modèle présélectionné** : Sonnet. Haiku si tu préfères que le défaut soit le moins cher.
4. **Déclenchement des runs réels « par l'agent principal »** : D2 réserve le dispatch à un humain ; l'agent principal ne peut confier un run qu'avec ton jeton de navigateur, sur ta consigne. L'addendum l'écrit ainsi ; à corriger si tu veux que seul toi cliques.
5. **Phrase dans AGENTS.md** pointant vers l'exception (§10) : ajoutée par H1, comme pour toute PR qui touche AGENTS.md.
