# Run Codex réel — commit fait par Nexus, bac à sable `unelevated`, configuration de Loïc tenue à l'écart

**Date :** 2026-11-13
**Issue :** #186 (refs #183, Phase 2) ; précédent : `docs/superpowers/specs/2026-11-11-adaptateur-claude-code-design.md` (lot H2, §4, §5.4 et §14), module commun `run_commit` livré par #188.
**Décisions d'origine :**
- **Décidé par Loïc le 2026-11-12** (commentaire de #186) : Nexus passe `windows.sandbox=unelevated` à **ses** runs Codex seulement ; la configuration de Loïc (`~/.codex/config.toml`, `[windows] sandbox = "elevated"`) ne change pas.
- **Choisi par l'agent sous la délégation de Loïc du 2026-11-13** (« je te laisse gérer ce que tu préfères niveau option ») : Nexus commite pour Codex à la fin du run par `run_commit`, comme pour `claude-code` ; **pas** de clone par run. Ce n'est pas un choix de Loïc entre deux options : il a délégué le choix, l'agent l'a fait et l'écrit comme tel (`DECISIONS.md`, addendum du 2026-11-13).
**Entrées :** ADR-023 (D1–D8 et addenda), INTEGRATIONS §A.2 (adaptateurs Codex et Claude Code), SECURITY §3, `server/src/nexus/adapters/codex.py`, `codex_git.py`, `codex_process.py`, `codex_translate.py`, `run_commit.py`, `run_commit_scan.py`, `claude_code*.py`, `runs/supervisor.py`, `tasks/timeline_api.py`, `web/src/runs/Timeline.tsx`, les tests `server/tests/test_codex_*.py` et `web/e2e/fake-codex.mjs`.
**`CONTEXT.md` :** absent à la racine du dépôt ; les décisions viennent de `DECISIONS.md`.

**Relevé fait pour ce cadrage, sans lancer de modèle** (codex-cli 0.167.1, Windows 11, 2026-11-13) : `codex --version`, `codex --help`, `codex exec --help`, `codex features --help`, `codex mcp list --help`, `codex debug --help`, `codex debug prompt-input --help`, `codex doctor --help`, `codex sandbox --help` ; avec un `CODEX_HOME` **vide** pris dans un dossier jetable (jamais celui de Loïc) : `codex features list` (avec et sans `--disable`, avec `-c windows.sandbox=…`), `codex mcp list --json`, `codex debug prompt-input` (rendu local de l'entrée du modèle, sans connexion : le dossier n'avait aucun `auth.json`), dont la sortie n'a été lue que par recherche de marqueurs. Dans `~/.codex` de Loïc : **noms** des entrées seulement, et des lignes d'en-tête de `config.toml` (`[windows]`, `sandbox = …`, noms de tables `[mcp_servers.*]`), jamais une valeur, jamais `auth.json`. La documentation officielle lue : référence de configuration (learn.chatgpt.com, `config-reference`) et page des skills (via Context7, `learn.chatgpt.com/docs/build-skills`). Le §11 sépare ce qui est vérifié de ce qui ne l'est pas.

Ce document fixe ce qu'un `implementer` écrit, tests d'abord. Il ne touche ni `run_commit.py` (380 lignes, neutre, testé) ni le comportement de `claude-code`, sauf l'enveloppe de processus du §4 (même module partagé, voir §4.5).

---

## 0. Décisions en bref

1. **Nexus commite pour Codex** (§1). L'agent ne commite plus : la consigne le dit, le bac à sable l'empêche de toute façon (relevé du 2026-11-12). À la fin d'un tour réussi (`turn.completed`, code 0), Nexus arrête tout l'arbre de processus du run, vérifie que l'agent n'a touché ni à la branche ni au fichier `.git` du worktree, puis appelle `run_commit.commit_run(CommitRequest(…, adapter="codex", label="Codex", model=None))`. D6 inchangé : la preuve est un commit qui descend du commit de départ, relu depuis le dépôt.
2. **Précondition 1 de `run_commit`** (l'agent n'a pas pu écrire dans le dossier git) : tenue par le bac à sable `workspace-write` ; Nexus refuse au lancement tout montage où un dossier git (dossier du worktree, dossier commun) ou le `CODEX_HOME` de Nexus serait dans le dossier temporaire de l'enfant ; il vérifie à la fin que la branche n'a pas bougé et que le fichier `.git` du worktree n'a pas changé, sinon `failed` sans commit (§2).
3. **Précondition 2** (plus aucun processus du run n'écrit) : un **job object** Windows (`KILL_ON_JOB_CLOSE`, sans autorisation de sortie) enveloppe l'arbre de Codex dès sa création (processus créé suspendu, assigné, puis repris) ; l'arrêt est confirmé quand le job n'a plus aucun processus actif ; il est fait **avant chaque commit**, même après une sortie propre. POSIX : groupe de processus, arrêt confirmé quand le groupe est vide. Repris pour `claude-code` dans la même PR ; pas pour Hermes (§4).
4. **`unelevated` sous Windows seulement**, écrit **sans guillemets** (`-c windows.sandbox=unelevated`) : vérifié, Codex lit la valeur comme la variante attendue (une valeur fausse est refusée avec la liste `elevated`, `unelevated`, `mxc`) ; aucune valeur de l'argv de Nexus ne contient un caractère que `cmd.exe` réinterpréterait, ce qui rend l'argv sûr derrière un lanceur `.cmd` (§3).
5. **Configuration de Loïc tenue à l'écart** par un `CODEX_HOME` **propre à Nexus** (`<NEXUS_DATA_DIR>/codex-home`, où Loïc se connecte une fois), plus `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, les skills coupées (`-c skills.include_instructions=false`, `-c skills.bundled.enabled=false`) et une liste de fonctions coupées (`--disable hooks`, `plugins`, `apps`…). **Contrôle avant le lancement, qui échoue fermé** : `codex mcp list --json` doit rendre `[]`, `codex debug prompt-input` ne doit contenir aucun bloc de skills, le `CODEX_HOME` de Nexus ne doit contenir ni instructions, ni hooks, ni skills, ni profils. Pendant le run, un élément `mcp_tool_call` tue l'arbre et termine le run en `failed` (§5).
6. **La cause d'un échec s'affiche dans la chronologie** : le serveur ajoute un champ `cause` à l'entrée (tiré de `payload.cause`, déjà masqué au stockage, seulement pour `failed` et `blocked`, et pas quand il répète le sujet) ; l'interface l'affiche « Cause : … » (§6).
7. **Fins alignées sur `claude-code`** (§7) : refus de Nexus → `failed` ; aucun changement → `review` ; violation d'isolement → `failed` sans commit ; annulation → `cancelled` ; redémarrage → `unknown`, jamais de commit après coup.
8. **Quatre PR indépendantes, l'une après l'autre, chacune depuis `master` à jour** (§9) : A cause dans la chronologie ; B job object ; C isolement et `unelevated` ; D commit par Nexus. Puis une PR de docs pour les runs réels.

---

## 1. Fin d'un run Codex : commit par Nexus

### 1.1 Pourquoi Nexus commite, et pas un clone par run

Le relevé du 2026-11-12 (#186, point 2) : sous `--sandbox workspace-write` et `unelevated`, Codex modifie les fichiers mais `git commit` échoue (« accès refusé à `index.lock` ») : le dossier git du worktree (`<dépôt>/.git/worktrees/nx-run-<n>`) est hors de la zone où le bac à sable écrit. Rendre `.git` du dépôt inscriptible est exclu (Loïc, 2026-11-12).

**Retenu : Nexus commite** (`run_commit`). Raisons, reprises du §14.2 du cadrage `claude-code` :
- un seul chemin de commit pour les deux exécutants, déjà testé (tests 48–69 de #188) et relu en réel avec `claude-code` (#190) ;
- la précondition 1 tient **par construction** : c'est exactement ce que le bac à sable a refusé ;
- l'auteur est l'identité git du dépôt, figée par Nexus (avec un clone, l'agent choisit l'auteur de ses commits : relevé local du 2026-11-12) ;
- aucun git de Nexus ne tourne contre un dépôt que l'agent contrôle ; aucun coût disque.

**Rejeté : un clone par run.** L'agent commiterait lui-même dans un clone qu'il possède, puis Nexus rapatrierait la branche. Coûts relevés le 2026-11-12 (§14.2 du cadrage `claude-code`) : `objects/info/alternates` d'un clone `--shared` modifiable par l'agent, `--local` exclu (liens physiques vers les objets du dépôt), `--no-hardlinks` coûteux ; auteur des commits choisi par l'agent ; nettoyage d'un clone sous Windows ; amendement de D6 (preuve rapatriée d'un autre dépôt). Il ne règle pas non plus l'arrêt de l'arbre (§4), dont un run a besoin de toute façon.

**Rejetés aussi** (§14.2 du cadrage `claude-code`) : rendre inscriptible le seul `<dépôt>/.git/worktrees/nx-run-<n>` (`--add-dir`) : un commit écrit aussi dans le dossier commun, et le fichier `commondir` deviendrait modifiable par l'agent ; rendre `.git` du dépôt inscriptible (Loïc).

**Ce que Codex perd :** écrire ses messages de commit et découper son travail en plusieurs commits. **Ce qu'il garde :** lancer des commandes, dont les tests, dans son bac à sable.

### 1.2 Consigne (entrée standard)

Le brief est suivi d'une consigne fixe (constante `codex_cli.INSTRUCTION`, testée telle quelle ; le « 20 Mo » est vérifié contre `run_commit.MAX_FILE_BYTES` comme pour `claude-code`) :

```text

---
Consigne de Nexus : tu travailles dans un dossier à part, créé pour ce run.
Ne lance ni `git commit`, ni `git add`, ni aucune commande qui écrit dans git : Nexus enregistre
lui-même tes changements dans un commit, que Loïc relira, quand ton tour se termine sans erreur.
Tu peux lire l'état du dépôt (`git status`, `git diff`, `git log`).
Ne touche pas au fichier .git de ce dossier et ne crée ni dépôt git, ni lien (lien symbolique,
point de jonction, lien physique), ni fichier de plus de 20 Mo : Nexus refuserait alors
d'enregistrer le travail.
Ne laisse aucun processus tourner en arrière-plan : Nexus les arrête avant d'enregistrer.
Si rien n'est à changer, dis pourquoi dans ta réponse finale.
```

Elle ne contient ni référence de run, ni chemin. `CodexAdapter._feed` écrit `brief + INSTRUCTION`, comme `ClaudeCodeAdapter._feed`.

### 1.3 Séquence de fin (`CodexAdapter._close_ended`)

Dans l'ordre, après la fin réelle du processus principal (fil de lecture fini, `poll()` non nul) :

1. **Violation d'isolement lue pendant le run** (§5.4, `mcp_tool_call`) : l'arbre a déjà été tué par le fil de lecture ; `_settle` refait l'arrêt confirmé, puis `failed` « isolation non respectée : <mots fixes> ». **Aucun commit.**
2. **Durée maximale** : arbre arrêté, `failed` « Durée maximale dépassée » (inchangé). **Aucun commit.**
3. `turn.failed`, code non nul, ou pas de `turn.completed` : `failed` avec la cause actuelle (`failure or last_error or …`, inchangé, #176). **Aucun commit.**
4. **Arrêt de tout l'arbre** (§4) : `codex_process.kill_tree(job.process)`, même après une sortie propre (un serveur de développement ou un `start /b` lancé par l'agent peut survivre au processus principal). Arrêt non confirmé → `RuntimeError`, le run reste ouvert et le superviseur réessaie au tour suivant (comportement existant de `_settle`).
5. **Gardes de la précondition 1** (§2.3), sauf si `job.commit_attempted` est vrai (un passage précédent de Nexus, voir 6) :
   - la branche `refs/heads/nexus/nx-run-<n>` pointe toujours sur `tree.start` (lu par `codex_git.git` depuis le dépôt) ; sinon `failed` « isolation non respectée : la branche du run a changé pendant le run » ;
   - le fichier `.git` du worktree a exactement les octets lus juste après `create_worktree` ; absent, changé ou devenu un dossier → `failed` « isolation non respectée : fichier .git du worktree modifié ».
   Aucun commit dans les deux cas ; la branche et le worktree restent tels quels pour Loïc.
6. `job.commit_attempted = True`, puis `run_commit.commit_run(CommitRequest(tree, gitdir, identity, run_ref, adapter="codex", label="Codex", model=None), max_file_bytes=…, budget=…)`. Sujet du commit : `nx-run-<n> : travail de Codex` ; trailers `Nexus-Run: nx-run-<n>` et `Nexus-Executor: codex` (aucun `Nexus-Model` : Codex n'a pas de modèle par run). Le module n'est pas modifié (test 66 de #188 couvre déjà cette requête).
7. Issue → événement final (§7).

**Pourquoi la garde 5 avant `commit_run`.** L'étape 1 de `commit_run` rend `Committed` pour **tout** commit qui descend du départ : c'est ce qui la rend idempotente après une coupure entre le commit et l'événement. Sans la garde, un commit fait par l'agent (si le bac à sable le laissait faire) finirait en `done`. `job.commit_attempted` distingue les deux : un commit présent alors que Nexus n'a jamais tenté le sien vient d'ailleurs. On ne prend **pas** d'empreinte de l'index : le git que Codex lance lui-même peut légitimement rafraîchir l'index (`git status`), et l'index n'entre pas dans la preuve. La garde vit dans l'adaptateur, pas dans `run_commit` (module neutre, 380 lignes).

**Si l'agent a touché à l'état git sans pouvoir l'écrire** (`git add`, `git commit`, `git stash` qui échouent sur `index.lock`) : rien à faire ; la commande échoue dans son bac à sable, Codex le voit dans sa sortie, le tour continue. Si l'agent a écrit dans le worktree un dossier qui ressemble à un dépôt (`sub/.git/`, `sub/.GIT`, fichier `sub/.git`) ou un lien, `commit_run` le refuse (étape 3 de `run_commit`) → `failed` « commit refusé par Nexus : … ».

**Redémarrage et annulation** : inchangés. Une annulation demandée avant le tour gagne (`_step` traite l'annulation avant le suivi, sous le même verrou) : arbre arrêté, `cancelled`, aucun commit. Un run en cours au redémarrage passe `unknown` et n'est jamais commité ensuite (`recover` rend `None`).

### 1.4 Ce qui est contrôlé avant le lancement (ordre de `dispatch`)

Tout ce qui peut échouer passe **avant** `create_worktree` quand c'est possible (aucune branche ni worktree laissés derrière), comme `claude-code` :

1. `codex_git.choose_repo(workdirs, run.workdir)` (inchangé).
2. `run_commit.resolve_identity(repo)` (identité figée pour le commit).
3. `run_commit.check_no_filter_driver(repo)` (avant l'extraction : `git worktree add` lancerait déjà un `smudge` de la configuration du dépôt, cas 12 du §4.5 du cadrage `claude-code`).
4. **Emplacements** (§2.2) : dossier commun du dépôt et `CODEX_HOME` de Nexus hors des dossiers temporaires de l'enfant → sinon `ValueError`.
5. `codex_git.create_worktree(…)` ; puis, dans un `try` qui défait le lancement en cas d'exception (`_undo_launch`, copié de `claude-code` : arrêt, `git worktree remove --force`, `git branch -D`) :
6. `run_commit.worktree_gitdir(tree)` ; contrôle d'emplacement du dossier git du worktree (§2.2) ; lecture des octets du fichier `<worktree>/.git` (gardés dans le job, §1.3 étape 5).
7. **Contrôle d'isolement** (§5.3) dans le worktree, avec l'argv et l'environnement du run ; échec → `ValueError`.
8. `codex_process.spawn(argv, worktree, env, contain=True)` (§4).

Une exception de `dispatch` donne toujours `failed` « lancement impossible » (superviseur, cause fixe, message jamais recopié). Les messages des `ValueError` servent aux tests qui appellent les fonctions directement. Une cause de lancement plus précise est une proposition à part (§13, 3).

---

## 2. Précondition 1 : l'agent ne peut écrire ni le dossier git du worktree ni le `.git` du dépôt

### 2.1 Ce qui est établi, ce qui ne l'est pas

- **Établi (run réel du 2026-11-12, `unelevated`)** : écrire `index.lock` dans `<dépôt>/.git/worktrees/nx-run-<n>` est refusé à une commande de l'agent.
- **Pas établi** : l'écriture dans le dossier **commun** (`<dépôt>/.git/config`, `hooks/`, `refs/`) n'a pas été tentée ; la liste exacte des racines inscriptibles du bac à sable `unelevated` sous Windows n'est pas documentée sur la page de référence lue. La référence décrit `sandbox_workspace_write.exclude_tmpdir_env_var` (« Exclude `$TMPDIR` from writable roots in workspace-write mode ») : le dossier temporaire est donc, par défaut, une racine inscriptible (au moins là où `$TMPDIR` s'applique) ; on suppose qu'il l'est aussi sous Windows (`TEMP`, `TMP`) tant que le run réel ne dit pas le contraire.
- **Relevé le 2026-11-13** : avec un `CODEX_HOME` placé sous `%TEMP%`, Codex écrit « Refusing to create helper binaries under temporary dir » : il traite lui-même le dossier temporaire comme un lieu à part.

### 2.2 Ce que Nexus contrôle au lancement (échec fermé)

`codex_cli.check_locations(env, *, common_dir, gitdir, codex_home, worktree)` lève `ValueError` si l'un des dossiers suivants est **égal à, ou sous**, un des dossiers « inscriptibles supposés » :

| Dossier contrôlé | Dossiers inscriptibles supposés |
|---|---|
| dossier commun du dépôt (`codex_git.common_dir(repo)`), dossier git du worktree (`worktree_gitdir`), `CODEX_HOME` de Nexus | le worktree du run ; `TEMP`, `TMP`, `TMPDIR` **de l'environnement de l'enfant** (les valeurs non vides, résolues) |

Comparaison sur les chemins résolus, sans la casse sous Windows (`os.path.normcase`), comme `run_commit.worktree_gitdir`. Conséquence : un dépôt jetable créé sous `%TEMP%` n'est pas utilisable avec Codex (à écrire dans INTEGRATIONS §A.2). Aucun `--add-dir` n'est jamais passé (testé par égalité de l'argv) ; aucune `sandbox_workspace_write.writable_roots` n'est donnée.

**Rejeté :** passer `-c sandbox_workspace_write.exclude_tmpdir_env_var=true` pour retirer le dossier temporaire des racines : beaucoup d'outils (tests, compilateurs) ont besoin d'un dossier temporaire inscriptible, et l'effet sous Windows n'est pas vérifié. Le contrôle d'emplacement suffit et ne retire rien à l'agent.

Pour les tests et l'e2e, dont les dossiers sont sous le dossier temporaire du système, l'environnement de l'enfant reçoit `TEMP`, `TMP` et `TMPDIR` pointés vers un dossier `tmp/` à part (paramètre `environ` de l'adaptateur en pytest ; variables du serveur de test dans `global-setup.ts` en e2e) : le contrôle compare à **ces** valeurs.

### 2.3 Ce que Nexus contrôle à la fin

Voir §1.3, étape 5 : branche toujours au départ, fichier `.git` du worktree inchangé. Ces deux gardes ne prouvent pas que rien n'a été écrit dans le dossier commun ; elles attrapent les deux écritures qui fausseraient le commit de Nexus (un commit déjà présent, un worktree rebranché). Le dossier commun reste couvert par le bac à sable, à confirmer au run réel (§10, scénario E) ; **si une écriture y réussit, on arrête les runs réels** et on revient vers Loïc.

### 2.4 Le git que lance Codex lui-même, et l'environnement de l'enfant

Codex (le processus `codex.exe`, hors bac à sable) lance peut-être git pour son propre contexte (état du dépôt, différences du tour) : **non vérifié**. Si c'est le cas, un fichier `.git` du worktree réécrit par l'agent vers un faux dossier git dont la configuration déclare `core.fsmonitor` ou un pilote ferait exécuter du code **hors du bac à sable**, au nom de Loïc.

Décision pour ce lot :
- l'enfant reçoit `GIT_CONFIG_COUNT=2`, `GIT_CONFIG_KEY_0=core.hooksPath`, `GIT_CONFIG_VALUE_0=<os.devnull>`, `GIT_CONFIG_KEY_1=core.fsmonitor`, `GIT_CONFIG_VALUE_1=false`, et `GIT_TERMINAL_PROMPT=0` ; tout `GIT_*` hérité est retiré. Ces valeurs l'emportent sur la configuration de n'importe quel dossier git (§4.3 du cadrage `claude-code`) et ne gênent pas le travail de l'agent (il ne commite pas) ;
- **pas** de `GIT_DIR`/`GIT_WORK_TREE` imposés à l'enfant, contrairement à `claude-code` : Codex a un shell, et un `GIT_DIR` hérité casserait tout ce que l'agent lance dans un autre dépôt (des tests qui créent des dépôts jetables, un sous-projet). Les autres clés qu'un faux dossier git pourrait déclarer (`diff.external`, pilotes de filtre, `core.pager`) ne sont pas couvertes ;
- le relevé du §10 (étape 0b) dit si `codex.exe` lance git hors du bac à sable. **S'il le fait**, la garde « fichier `.git` inchangé » arrive trop tard : on arrête les runs réels et on choisit, avec Loïc, entre imposer `GIT_DIR` à l'enfant ou couper le contexte git de Codex (§11, Q3).

---

## 3. `unelevated`, sous Windows seulement, sûr derrière un lanceur `.cmd`

### 3.1 Relevé

- Le `codex` installé est un exécutable natif (`%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe`), pas un lanceur `.cmd` ; `NEXUS_CODEX_BIN` peut pourtant désigner un lanceur (installation npm, faux exécutable des tests `fake-codex.cmd`).
- L'aide de `-c` : « The `value` portion is parsed as TOML. If it fails to parse as TOML, the raw string is used as a literal. »
- **Vérifié le 2026-11-13** (`codex features list`, `CODEX_HOME` vide) : `-c windows.sandbox=unelevated` (sans guillemets) → code 0 ; `-c windows.sandbox=bogus` → code 1, « unknown variant `bogus`, expected one of `elevated`, `unelevated`, `mxc` » ; `-c 'windows.sandbox="unelevated"'` → code 0. La forme sans guillemets est donc lue comme la variante attendue, pas ignorée.
- La forme avec guillemets casse derrière un `.cmd` (#186) : `subprocess.list2cmdline` écrit `\"`, que `cmd.exe` ne lit pas comme un échappement.

### 3.2 Règle

- `codex_cli.argv(binary, worktree, *, windows: bool)` ajoute `-c windows.sandbox=unelevated` **seulement si** `windows` est vrai ; l'adaptateur passe `sys.platform == "win32"` ; le test appelle les deux branches.
- **Aucune valeur de l'argv construit par Nexus ne contient** de guillemet, d'espace ni un des caractères `& | < > ^ % ! ( ) "` (test : chaque élément, sauf le chemin du binaire et celui du worktree, correspond à `[A-Za-z0-9_.=-]+`). Le chemin du worktree passe par `--cd` ; il est sous `<NEXUS_DATA_DIR>/worktrees/nx-run-<n>`, et `list2cmdline` le met entre guillemets s'il contient une espace, ce qui est lu correctement par un `.cmd` qui transmet `%*` (cas déjà couvert par les tests actuels de Codex).
- **Rejeté :** résoudre le point d'entrée réel derrière un `.cmd` (Node et le script de npm) : dépend de la forme du lanceur, et inutile tant que l'argv ne contient rien que `cmd.exe` réinterprète.
- **Rejeté :** écrire `windows.sandbox` dans un `config.toml` de Nexus : `--ignore-user-config` ne le lirait pas (§5.2), et un fichier est un état de plus à contrôler.
- La configuration de Loïc n'est jamais modifiée : Nexus ne lit ni n'écrit `~/.codex/config.toml` (§5).

---

## 4. Précondition 2 : un job object autour de l'arbre de processus

### 4.1 Le constat

`codex_process.kill_tree` utilise `taskkill /PID <pid> /T /F` sous Windows : il ne retrouve pas un enfant devenu orphelin (son docstring le dit). Constaté le 2026-11-12 avec `claude.exe` (scénario F de #190) : après un arrêt forcé du serveur, le processus du run a continué. Pour Codex, qui a un shell, un orphelin pourrait poser une jonction entre le parcours de `run_commit` (étape 3) et `git add -A` (étape 4) : c'est la précondition 2 de `run_commit`.

### 4.2 Windows : job object

Nouveau module `server/src/nexus/adapters/process_job_win.py` (Windows seulement, `ctypes` et `ctypes.wintypes` de la bibliothèque standard, aucune dépendance ajoutée) :

1. `CreateJobObjectW(NULL, NULL)` : job **anonyme** (aucun autre processus ne peut l'ouvrir par son nom), handle **non héritable** (attributs de sécurité nuls).
2. `SetInformationJobObject(job, JobObjectExtendedLimitInformation, …)` avec `LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` seulement : **ni** `JOB_OBJECT_LIMIT_BREAKAWAY_OK` **ni** `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK`. Un enfant qui demande `CREATE_BREAKAWAY_FROM_JOB` voit sa création refusée.
3. `subprocess.Popen(…, creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED)` : le processus existe mais n'a exécuté aucune instruction, donc n'a lancé aucun enfant.
4. `OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)` puis `AssignProcessToJobObject(job, h)`. (Par le pid plutôt que par `Popen._handle`, attribut privé ; le pid ne peut pas être réutilisé tant que `Popen` garde son handle ouvert.)
5. Reprise du fil principal : `CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD)`, fil(s) dont `th32OwnerProcessID == pid`, `OpenThread(THREAD_SUSPEND_RESUME)`, `ResumeThread`. (`subprocess` ferme le handle du fil sans le rendre ; l'instantané est l'API documentée pour le retrouver. **Rejeté :** `NtResumeProcess`, non documenté.)
6. Toute erreur aux étapes 1, 2, 4 ou 5 : `TerminateProcess`, fermeture des handles, `OSError` → `dispatch` échoue (« lancement impossible »), aucun processus ne reste. Échec fermé : jamais un processus lancé hors job.

Le handle du job est gardé par l'objet `Popen` (attribut `nexus_job` posé par `spawn`) et n'est fermé qu'après un arrêt confirmé.

**Arrêt** (`kill_tree` quand `process.nexus_job` existe) : `TerminateJobObject(job, 1)`, puis attente, bornée par `timeout`, que `QueryInformationJobObject(JobObjectBasicAccountingInformation).ActiveProcesses == 0` (relue toutes les 50 ms), puis `process.wait(timeout)`. Rend `True` seulement si les deux tiennent ; `False` sinon (le run reste ouvert, comme aujourd'hui). Sur un job déjà vide (sortie propre), l'arrêt rend `True` tout de suite. Le handle est fermé après un arrêt confirmé.

**Mort du serveur** (arrêt forcé, plantage) : le système ferme les handles du processus serveur ; `KILL_ON_JOB_CLOSE` tue alors tout ce qui reste dans le job (comportement documenté de Windows). Aucun processus du run ne détient de handle du job (non héritable, anonyme), donc rien ne le garde ouvert. Ce lot ne change pas la procédure d'annulation après un redémarrage (marqueur `.stopped`) : prouver après coup que le serveur précédent est bien mort est un sujet à part (§13, 4).

**Jobs imbriqués** : depuis Windows 8, un processus peut appartenir à plusieurs jobs imbriqués ; le serveur lancé depuis un terminal ou un éditeur déjà dans un job reste compatible. **Non vérifié :** que le bac à sable Windows de Codex n'a pas besoin de `CREATE_BREAKAWAY_FROM_JOB` pour ses propres processus. Si c'est le cas, les commandes de l'agent échoueront sous notre job : **condition d'arrêt** du run réel (§10, étape 0c et scénario A) ; on n'autorise pas la sortie du job sans nouveau cadrage.

### 4.3 POSIX

`start_new_session=True` existe déjà (le processus est chef de session et de groupe). `kill_tree` : `os.killpg(pgid, SIGKILL)`, `process.wait(timeout)`, puis attente bornée que `os.killpg(pgid, 0)` lève `ProcessLookupError` (le groupe est vide). **Limite documentée :** un descendant qui appelle `setsid()` ou `setpgid()` quitte le groupe et n'est ni tué ni vu. Nexus tourne sous Windows (Helios) ; une enveloppe par cgroup sous Linux est hors de ce lot.

### 4.4 Interface

```python
def spawn(argv, cwd, env, *, text=True, stderr=None, contain=False) -> subprocess.Popen: ...
def kill_tree(process: subprocess.Popen, timeout: float = 10.0) -> bool: ...  # unchanged signature
```

`contain=True` : job object sous Windows, attente du groupe vide sous POSIX. `contain=False` : comportement actuel, octet pour octet. `codex_process.py` (77 lignes) garde l'interface et délègue le détail Windows à `process_job_win.py`.

### 4.5 Qui l'utilise

- **Codex** : `contain=True` (PR B pose l'enveloppe ; PR D s'en sert avant le commit, §1.3 étape 4).
- **`claude-code` : oui, dans la même PR B.** Même module partagé, et l'orphelin constaté au scénario F de #190 est le cas que le job règle. Changement d'un seul argument (`contain=True` dans `ClaudeCodeAdapter.dispatch`), le reste de l'adaptateur appelle déjà `kill_tree`. L'arrêt depuis le fil de lecture (`Job.take`) passe par le même `kill_tree`. Un run réel court de `claude-code` après la PR (scénario G du §10 refait avec Haiku) vérifie que Claude Code fonctionne dans le job.
- **Hermes : non.** `hermes_cli` lance des commandes courtes de la CLI Hermes, qui peuvent démarrer un processus de fond propre à Hermes ; le tuer à la fermeture du job casserait Hermes. Hermes garde `contain=False`.

### 4.6 Tests sans vrai Codex

Le faux processus est un script Python lancé par `spawn` (pas de `codex`), écrit par le test :
- il lance un petit-enfant **détaché** (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` sous Windows, `os.fork` + sortie du parent ailleurs) qui écrit un battement (un fichier réécrit toutes les 50 ms), puis le parent sort ;
- les tests Windows sont marqués `skipif(sys.platform != "win32")` : la CI tourne sous `ubuntu-latest`, ils ne tournent donc **que dans le hook local** (`.husky/pre-commit`, Helios sous Windows) ; les tests POSIX sont marqués à l'inverse. La PR B le dit dans son corps.

---

## 5. Isolement de `~/.codex`

### 5.1 Ce que contient la configuration de Loïc (relevé du 2026-11-13, noms seulement)

`~/.codex` contient notamment `config.toml` (`[windows] sandbox = "elevated"`, deux serveurs MCP déclarés, une table `[features]`), des profils `*.config.toml`, `AGENTS.md` (instructions globales), `hooks.json`, `skills/`, `memories`, `plugins/`, `rules/`, `auth.json`. Les skills de l'utilisateur vivent aussi **hors** de `CODEX_HOME`, dans `~/.agents/skills` (documentation officielle : portée `USER`, `$HOME/.agents/skills`).

### 5.2 Mécanisme retenu : un `CODEX_HOME` propre à Nexus, plus des drapeaux

- **`CODEX_HOME=<NEXUS_DATA_DIR>/codex-home`**, imposé dans l'environnement de l'enfant (le `CODEX_HOME` hérité est retiré de la liste blanche). Ce dossier ne contient que ce que Codex y crée lui-même et la connexion que **Loïc y fait une fois** (`$env:CODEX_HOME="<NEXUS_DATA_DIR>\codex-home"; codex login`, dans son terminal). Nexus ne lit, ne copie et ne journalise jamais les fichiers de connexion. Rien de `~/.codex` (instructions, hooks, skills, mémoires, plugins, règles, profils, serveurs MCP) n'est donc à portée.
- **Drapeaux et réglages** (vérifiés dans l'aide de la 0.167.1 ; leur effet est vérifié là où le §5.3 le dit) :
  - `--ignore-user-config` (« Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME` ») : aucun `config.toml`, même déposé plus tard dans le dossier de Nexus, n'est lu ;
  - `--ignore-rules` (« Do not load user or project execpolicy `.rules` files ») : une règle d'exécution rangée dans le dépôt ne peut pas assouplir le bac à sable ;
  - `--ephemeral` (« Run without persisting session files to disk ») : aucune session écrite, cohérent avec « la sortie brute n'est jamais écrite » ;
  - `-c skills.include_instructions=false` et `-c skills.bundled.enabled=false` (référence de configuration) : **vérifié** (§5.3) que le bloc des skills disparaît de l'entrée du modèle, y compris `~/.agents/skills` ;
  - `--disable hooks --disable plugins --disable remote_plugin --disable apps --disable memories --disable browser_use --disable computer_use --disable in_app_browser --disable tool_suggest --disable skill_mcp_dependency_install` : **vérifié** que chacune passe à `false` dans `codex features list` (CODEX_HOME vide, où `hooks`, `plugins`, `apps` valent `true` par défaut et `memories` `false`). `apps` couvre les connecteurs du compte ChatGPT, qui ne viennent pas de `config.toml`. Un nom de fonction inconnu fait échouer Codex (« Unknown feature flag », code 1, vérifié) : si une version future renomme une fonction, le contrôle du §5.3 échoue avant tout modèle.
- **Rejeté : `--ignore-user-config` seul sur le `CODEX_HOME` de Loïc.** L'aide ne nomme que `config.toml` ; `AGENTS.md`, `hooks.json`, `skills/`, `memories`, `plugins/` et `rules/` sont des entrées à part, et `~/.agents/skills` est hors de `CODEX_HOME` (vérifié au §5.3 : même avec un `CODEX_HOME` vide, `~/.agents/skills` arrive dans l'entrée du modèle). `codex debug prompt-input` n'accepte pas `--ignore-user-config` : on ne pourrait pas le vérifier avant le lancement.
- **Rejeté : un `CODEX_HOME` par run avec une copie de `auth.json`.** Copier un secret ; et un rafraîchissement du jeton dans la copie pourrait invalider la connexion de Loïc (jetons de rafraîchissement à usage unique : non vérifié pour Codex, risque non pris).
- **Coût :** une seconde connexion de Loïc, propre à Nexus (§13, 1). Les quotas restent ceux de son compte.

### 5.3 Contrôle avant le lancement (échec fermé)

Codex n'a pas d'équivalent de la ligne `system/init` de Claude Code : `thread.started` ne porte qu'un identifiant (relevé des runs du 2026-11-10/11). Un élément `mcp_tool_call` dans la sortie n'est qu'une **détection après coup**. La prévention est donc un contrôle **avant** le `Popen`, fait par `codex_cli.check_isolation(binary, worktree, env, flags)` dans le worktree, avec **le même environnement et les mêmes `-c`/`--disable`** que le run (aucun modèle lancé ; chaque appel borné à 30 s ; sortie lue en mémoire, jamais écrite ni journalisée) :

1. **Dossier de Nexus** (`CODEX_HOME`) : refus s'il contient `config.toml`, un `*.config.toml`, `AGENTS.md`, `AGENTS.override.md`, `hooks.json`, une entrée dans `rules/`, `plugins/` ou `memories/`, ou dans `skills/` une entrée autre que `.system` (créé par Codex lui-même, relevé). Liste de refus (et non liste blanche) parce que Codex crée des fichiers de travail qui changent selon les versions ; les deux contrôles suivants couvrent le reste.
2. **`codex mcp list --json <-c…> <--disable…>`** : la sortie doit être exactement le tableau JSON vide. **Vérifié** : `[]` avec un `CODEX_HOME` vide. Code non nul, délai, JSON illisible ou non vide → refus. (Exécuté dans le worktree : une configuration de projet qui déclarerait un serveur serait vue, si Codex la charge : non vérifié, §11.)
3. **`codex debug prompt-input <-c…> <--disable…> ""`** (« Render the model-visible prompt input list as JSON ») : la sortie doit être un JSON lisible et ne contenir **ni** `<skills_instructions>` **ni** `### Skill roots`. **Vérifié** le 2026-11-13 avec un `CODEX_HOME` vide : sans réglage, la sortie contient `<skills_instructions>` et une table de racines où figurent `~/.agents/skills` (skills de Loïc) et `CODEX_HOME/skills/.system` (skills fournies) ; avec `-c skills.include_instructions=false` (avec ou sans `skills.bundled.enabled=false`), ni le bloc ni `.agents/skills` ne restent (seules des mentions génériques de `SKILL.md` dans les instructions de base). La commande a rendu 0 sans `auth.json` : elle ne demande pas de connexion (qu'elle n'appelle pas le réseau du tout n'est pas vérifié).

Un échec de 1, 2 ou 3 → `ValueError` → `failed` « lancement impossible », worktree et branche retirés. **Rejeté :** chercher dans la sortie de `prompt-input` le texte de `~/.codex/AGENTS.md` de Loïc : il faudrait le lire ; le `CODEX_HOME` propre l'exclut par construction et le contrôle 1 vérifie qu'aucun `AGENTS.md` n'y est déposé. Les `AGENTS.md` **du dépôt** confié restent lus : ils décrivent le projet sur lequel l'agent travaille.

### 5.4 Contrôle pendant le run

`codex_translate.translate_line` rend un fait `breach` « isolation non respectée : outil MCP appelé » pour un élément `mcp_tool_call`, qu'il arrive par `item.started` ou `item.completed` (le nom du serveur et de l'outil ne sont pas recopiés). Le job (comme `claude_code_job.Job.take`) arrête l'arbre tout de suite depuis le fil de lecture et n'enregistre plus rien ; `_settle` publie `failed` au tour suivant, après un arrêt confirmé (§1.3 étape 1). La forme `mcp_tool_call` a été **vue** au run réel du 2026-11-12 (#186, point 3) ; sa variante `item.started` ne l'a pas été (la traiter ne coûte rien).

Les autres types d'éléments (`web_search`, `todo_list`, `reasoning`…) restent ignorés ou traduits comme aujourd'hui : ils ne viennent pas de la configuration de Loïc.

### 5.5 Environnement de l'enfant

`codex_process.child_env(environ, allow=CODEX_ENV_ALLOW)` avec `CODEX_ENV_ALLOW = ENV_ALLOW - {"CODEX_HOME"}`, puis : tout `GIT_*` retiré ; imposés : `CODEX_HOME=<NEXUS_DATA_DIR>/codex-home`, les `GIT_CONFIG_*` et `GIT_TERMINAL_PROMPT` du §2.4. Jamais transmis (testé par nom) : `NEXUS_*`, `OPENAI_*`, `CODEX_HOME` hérité, `GIT_*` hérités. Le contrôle du §5.3 et le run reçoivent **le même** dictionnaire.

---

## 6. La cause d'un échec dans la chronologie

### 6.1 Constat

L'adaptateur publie `failed` avec le sujet « Codex a échoué » et la cause dans `payload.cause` (`codex.py`, `_close_ended`). `GET /api/tasks/{ref}/timeline` (`EntryOut`) ne renvoie ni `payload` ni la cause ; `Timeline.tsx` n'affiche que `subject` et `body`. Le superviseur, lui, publie ses propres échecs avec `subject = cause` (`supervisor._fail`) : eux s'affichent déjà.

### 6.2 Changement

- **Serveur** (`tasks/timeline_api.py`) : `EntryOut.cause: str | None = None`, rempli dans `entry_out` pour un événement **seulement si** `e.kind in ("failed", "blocked")`, `e.payload.get("cause")` est une chaîne non vide après `strip()`, et différente du sujet (évite le double affichage des échecs du superviseur). Coupée à 500 caractères (même borne que `text.cut`).
- **Interface** (`timelineApi.ts`, `Timeline.tsx`) : `TimelineEntry.cause?: string | null` ; dans `EntryRow`, après le sujet : `<p className="whitespace-pre-wrap">Cause : {entry.cause}</p>`. Texte en français, aucune interprétation.

### 6.3 Exposition

- `payload` passe par `secrets.redact_fields` avant d'être stocké (`events/service.py`) : la cause affichée est la cause **masquée**. Les adaptateurs la coupent déjà par `text.cut` (masquage sur tout le texte, puis coupe).
- Même public : `GET /api/tasks/{ref}/timeline` et `GET /api/events/{ref}` ont tous deux `dependencies=Authenticated` ; l'événement complet, `payload` compris, est déjà lisible par ce second chemin. L'affichage n'ajoute aucun lecteur.
- Une cause de Codex peut contenir un chemin (message d'erreur du CLI) : il est déjà stocké et lisible ; Loïc en a besoin pour comprendre l'échec. **Rejeté :** réécrire les chemins (perte d'information, et le chemin du worktree est celui que Loïc relit).

---

## 7. Fins d'un run Codex (alignées sur `claude-code`)

| Situation | État du run | Événement final | Preuve / pièce | Commit |
|---|---|---|---|---|
| Tour terminé, code 0, arbre arrêté, gardes OK, `Committed(sha)` | `done` | « Codex a terminé ; Nexus a commité » | `commit:<12>` | celui de Nexus |
| … `NothingToCommit` | `review` | « Codex a terminé sans changement », corps « aucun fichier modifié : à relire » | `branch:nexus/nx-run-<n>` | aucun |
| … `Refused(motif)` | `failed` | « Commit refusé par Nexus », cause « commit refusé par Nexus : <motif> » | `branch:…` | aucun |
| … `GitFailed(étape)` | `failed` | « Commit de Nexus impossible », cause « commit de Nexus impossible (<étape> ou délai dépassé) » | `branch:…` | aucun |
| Branche déplacée ou fichier `.git` changé (§1.3, 5) | `failed` | « Isolation de la session non respectée », cause « isolation non respectée : … » | `branch:…` | aucun |
| `mcp_tool_call` pendant le run | `failed` | idem, « … : outil MCP appelé » ; arbre tué tout de suite | — | aucun |
| `turn.failed`, code ≠ 0, pas de `turn.completed` | `failed` | « Codex a échoué », cause actuelle | — | aucun |
| Durée maximale | `failed` | « Durée maximale dépassée » | — | aucun |
| Contrôle avant lancement en échec (identité, pilote, emplacements, isolement, job) | `failed` | « lancement impossible » (superviseur) | — | rien de créé, ou worktree et branche retirés |
| Annulation | `cancelled` | « run annulé » (superviseur) | — | aucun |
| Redémarrage pendant le run | `unknown` | « suivi perdu au redémarrage de Nexus » | — | jamais après coup |
| Arrêt de l'arbre non confirmé | reste ouvert | aucun (nouvelle tentative au tour suivant ; l'exécutant reste occupé) | — | aucun |

Mêmes raisons que pour `claude-code` (§5.4 de son cadrage) : sans commit, pas de preuve (D6) ; un run sans changement peut être juste (Loïc lit la réponse) d'où `review` ; un refus signale un contenu que Nexus n'enregistre pas par principe, d'où `failed` avec sa cause.

---

## 8. Tests (cas limites d'abord), tailles, e2e

Règles : faux exécutables seulement (`GuardedPopen` refuse déjà le radical `codex`), aucun vrai LLM en CI ; faux secrets construits à l'exécution (`"ghp_" + "A" * 36`) ; les git des tests avec `env=codex_git.clean_env()` ; `MAX_FILE_BYTES` et `COMMIT_BUDGET` réduits par les attributs de l'adaptateur ; `TEMP`/`TMP`/`TMPDIR` de l'enfant pointés vers `tmp_path / "tmp"` (§2.2).

**Faux Codex** (`server/tests/codex_support.py`, script `FAKE_SCRIPT`) : il garde `lines`, `commit`, `hang`, `exit`, et reçoit les actions de `claude_code_support.py` (`write`, `write_named`, `nested_repo`, `gitfile`, `junction`, `big_file`, `attributes`, `ignore_all`, `rewrite_dotgit`) plus : `detach` (lance un petit-enfant détaché avec battement, §4.6), `breakaway` (tente `CREATE_BREAKAWAY_FROM_JOB` et note le refus), `delete_dotgit`. Il répond aux sous-commandes de contrôle : `mcp list --json` → `[]` (ou le contenu de `scenario.mcp_list`), `debug prompt-input` → `scenario.prompt_input` (par défaut un JSON sans bloc de skills), et note ces appels dans `calls.json`. **`commit` devient le scénario « l'agent a commité malgré tout »**, attendu en `failed`.

### PR A — cause dans la chronologie (`test_timeline_api.py`, `Timeline.test.tsx`)
- A1. `failed` publié par un adaptateur avec `payload.cause` → `cause` rendu, masqué (une cause contenant un faux secret arrive `[REDACTED]`).
- A2. Échec du superviseur (`subject == cause`) → `cause` absent.
- A3. `payload.cause` non chaîne, vide ou blanc → absent ; `blocked` avec cause → rendu ; `progress`, `done`, entrées `history` et jalons de run → absent.
- A4. Cause de 2 000 caractères → 500.
- A5. Interface : « Cause : … » sous le sujet ; rien quand `cause` est absent ou `null` (anciens serveurs).

### PR B — job object (`test_process_job.py`, Windows ; `test_process_group.py`, POSIX)
- B1. `spawn(contain=True)` puis `kill_tree` : le petit-enfant détaché (`detach`) s'arrête (battement figé sur 300 ms), `ActiveProcesses == 0`, `kill_tree` rend `True`.
- B2. **Mort du serveur** : un processus auxiliaire (le « serveur » du test) fait `spawn(contain=True)` d'un faux qui lance `detach`, puis le test tue l'auxiliaire (`TerminateProcess`) : le battement du petit-enfant s'arrête en moins de 2 s. Ce test échoue si le handle du job est hérité.
- B3. **Pas d'échappée** : `breakaway` → création refusée (le faux note `winerror 5`).
- B4. **Aucune course au démarrage** : 20 lancements d'un faux qui lance `detach` dès sa première instruction ; à chaque fois le petit-enfant est dans le job (arrêté par `kill_tree`).
- B5. **Échec d'assignation** (fonction remplacée par le test) → `OSError`, aucun processus vivant (le pid n'existe plus), aucun handle laissé.
- B6. Sortie propre puis `kill_tree` → `True` immédiat ; second `kill_tree` → `True`.
- B7. `ActiveProcesses` qui ne tombe pas à 0 dans le délai (fonction de requête remplacée) → `False`, le run reste ouvert (test existant `test_an_unconfirmed_kill_…` étendu).
- B8. `contain=False` : argv, drapeaux de création et comportement identiques à avant (non-régression pour Hermes).
- B9. POSIX : petit-enfant dans le même groupe arrêté ; `kill_tree` attend le groupe vide ; groupe qui ne se vide pas dans le délai → `False`.
- B10. `claude-code` : `dispatch` passe `contain=True` (test d'argument) ; `test_claude_code_cancel.py` reste vert.

### PR C — isolement et `unelevated` (`test_codex_cli.py`, `test_codex_isolation.py`)
- C1. `argv(…, windows=True)` égale exactement la liste attendue (§5.2 et §3.2) ; `windows=False` : la même sans `-c windows.sandbox=unelevated`.
- C2. Chaque élément de l'argv hors binaire et worktree correspond à `[A-Za-z0-9_.=-]+` ; jamais `--add-dir`, `--dangerously-bypass-approvals-and-sandbox`, `--dangerously-bypass-hook-trust`, `danger-full-access`, `--search`, `-p/--profile` ; le brief n'y est pas.
- C3. Par un lanceur `.cmd` (Windows) : `args.json` du faux contient `["-c", "windows.sandbox=unelevated"]` à l'identique.
- C4. Environnement : à partir d'un environnement qui contient `NEXUS_TOKEN`, `OPENAI_API_KEY`, `CODEX_HOME` (celui de Loïc), `GIT_DIR`, `GIT_INDEX_FILE` (et en minuscules) → aucun ne passe ; `CODEX_HOME` vaut `<data>/codex-home` ; `GIT_CONFIG_*` et `GIT_TERMINAL_PROMPT` valent ce que l'adaptateur impose ; le contrôle du §5.3 reçoit le même dictionnaire (`env.json` des appels de contrôle égal à celui du run).
- C5. Dossier de Nexus avec `AGENTS.md`, puis `hooks.json`, `config.toml`, `x.config.toml`, `skills/mine/SKILL.md`, `rules/a.rules`, `plugins/p`, `memories/m` → « lancement impossible », aucun `Popen` du run, ni worktree ni branche ; `skills/.system/` seul → lancement.
- C6. `mcp list` qui rend `[{"name":"x"}]`, `""`, du texte, un code 1, ou qui dépasse le délai → refus.
- C7. `prompt-input` qui contient `<skills_instructions>` ou `### Skill roots`, qui n'est pas du JSON, rend un code non nul ou dépasse le délai → refus.
- C8. **Emplacements** : dépôt dont le dossier commun est sous le `TEMP` de l'enfant ; `CODEX_HOME` de Nexus sous `TMPDIR` ; casse différente sous Windows → refus avant `create_worktree` (ni branche ni worktree) ; `TEMP` vide ou absent → ignoré.
- C9. Traduction : `item.started` et `item.completed` de type `mcp_tool_call` → `breach` (mots fixes ; ni serveur ni outil recopiés, même s'ils contiennent un faux secret) ; types inconnus → rien (inchangé).
- C10. Run avec `mcp_tool_call` puis `hang` → arbre tué sans attendre la durée maximale, `failed` « isolation non respectée : outil MCP appelé », arrêt confirmé ; arrêt non confirmé → lève, run ouvert.

### PR D — commit par Nexus (`test_codex_commit.py`, plus les tests existants modifiés)
- D1. Chemin heureux (`write`, accents compris) → `done` `commit:<12>` ; commit sur `refs/heads/nexus/nx-run-1`, sujet `nx-run-1 : travail de Codex`, trailers `Nexus-Run` et `Nexus-Executor: codex`, aucun `Nexus-Model`, auteur et committer = l'identité du dépôt ; `stdin.txt` = brief + consigne du §1.2.
- D2. Aucune action → `review` « sans changement », branche au départ.
- D3. **L'agent a commité** (`commit`, puis `turn.completed`, code 0) → `failed` « isolation non respectée : la branche du run a changé pendant le run », `commit_run` jamais appelé (trace), la branche garde le commit de l'agent.
- D4. `rewrite_dotgit` puis `write` → `failed` « … fichier .git du worktree modifié », aucun commit ; `delete_dotgit` → même chose.
- D5. **Idempotence** : `commit_run` réussit puis l'événement final échoue (exception injectée entre les deux) → au tour suivant, `commit_attempted` saute la garde, l'étape 1 de `run_commit` rend le même sha → `done`, un seul commit.
- D6. **Arrêt avant le commit** : `write` puis `detach` (un petit-enfant qui réécrit `late.txt` toutes les 50 ms), sortie 0 → le job est vidé avant le parcours (`late.txt` cesse de changer), le commit contient l'état figé, jamais d'erreur « worktree changé pendant le commit ». Arrêt non confirmé (remplacé) → run ouvert, aucun commit, réessai au tour suivant.
- D7. Refus de `run_commit` traversés par l'adaptateur : `nested_repo`, `gitfile`, `junction`, `big_file` (plafond réduit), `attributes` avec un pilote dans la configuration du dépôt ajouté pendant le run → `failed` « commit refusé par Nexus : <motif> » (un cas par motif suffit : `run_commit` est déjà testé en détail).
- D8. `ignore_all` + `write` → `review`.
- D9. `turn.failed`, code 1 après `turn.completed`, pas de `turn.completed`, durée maximale, chacun avec `write` → `failed`, aucun commit, le fichier reste dans le worktree.
- D10. Annulation pendant `hang` après `write` → `cancelled`, aucun commit ; annulation après la fermeture `done` → reste `done` (superviseur réel).
- D11. Identité absente / pilote de filtre dans la configuration du dépôt → « lancement impossible », ni `Popen`, ni branche, ni worktree.
- D12. Consigne : constante testée telle quelle, « 20 Mo » égal à `MAX_FILE_BYTES` en Mio.
- D13. `GuardedPopen` refuse toujours le radical `codex` ; `run_commit` n'importe toujours aucun module d'exécutant (test 66 de #188 inchangé).

**Tests existants touchés par la PR D** (modification assumée, notée dans la PR, comme le « 38 bis » de H1) : ils utilisent `commit=True` pour signifier « le tour a réussi », ce qui devient le cas D3. Ils passent à l'action `write` : `test_codex_adapter.py` (`test_dispatch_creates_a_worktree_and_a_branch_and_hands_the_brief_over_stdin`, qui vérifie aussi la consigne ajoutée ; `test_a_turn_with_a_commit_after_the_start_ends_done_with_the_commit_as_proof`, renommé sans changer d'intention en preuve par le commit de Nexus ; `test_a_clean_exit_without_a_finished_turn_is_not_a_success` ; `test_watch_resumes_after_the_cursor` ; `test_no_raw_output_is_ever_written`), `test_codex_errors.py` (`test_a_turn_that_recovers_after_a_reconnect_succeeds`, `test_a_finished_turn_with_a_bad_exit_still_fails`), `test_codex_review3.py` (`test_repeated_claimed_and_working_lines_are_kept_once`), `test_codex_security.py` (`test_a_turn_that_overran_the_limit_is_failed_even_if_it_ended_before_the_poll`), `test_codex_supervisor.py` (`test_a_whole_run_through_the_supervisor`). La PR C touche `test_the_child_environment_is_an_allow_list` (`CODEX_HOME` imposé). Les tests de `codex_git.proof` appelé directement (`test_a_commit_in_the_branch_is_the_proof`, `…fake_local_git_directory…`, `…detached_head…`) ne changent pas.

### Bout en bout (Playwright)
- PR A : `web/e2e/fake-codex.mjs` gagne un brief « ÉCHOUER » qui écrit `turn.failed` avec un message ; `runs.spec.ts` vérifie « Cause : … » dans la chronologie.
- PR C : `fake-codex.mjs` répond à `mcp list --json` (`[]`) et à `debug prompt-input` (JSON sans skills) ; `global-setup.ts` donne au serveur de test `TEMP`/`TMP`/`TMPDIR` dans `<dataDir>/tmp` (§2.2).
- PR D : `fake-codex.mjs` **écrit un fichier** au lieu de commiter ; les attentes « Preuve : commit:<12> » de `runs.spec.ts` restent vraies (le commit est celui de Nexus).

### Tailles (seuils 400 / 600)

| Fichier | Contenu | Taille visée |
|---|---|---|
| `adapters/codex.py` (305) | adaptateur : `dispatch` (§1.4), `_settle`/`_close_ended` (§1.3), `_commit`, `_undo_launch` | ≤ 340 après sortie de `_Job` |
| `adapters/codex_job.py` (nouveau, PR D) | `_Job` déplacé de `codex.py` + `breach`, `commit_attempted`, octets du `.git` | ≤ 150 |
| `adapters/codex_cli.py` (nouveau, PR C) | `argv`, drapeaux, `CODEX_ENV_ALLOW`, `child_env`, `check_locations`, `check_isolation`, `INSTRUCTION` (PR D) | ≤ 220 |
| `adapters/codex_translate.py` (78) | `breach` sur `mcp_tool_call` | ≤ 100 |
| `adapters/codex_process.py` (77) | `contain`, arrêt confirmé POSIX, délégation Windows | ≤ 130 |
| `adapters/process_job_win.py` (nouveau, PR B) | job object par `ctypes` | ≤ 200 |
| `tasks/timeline_api.py` (96), `web/src/runs/Timeline.tsx` (130), `web/src/timelineApi.ts` | champ `cause` | +15 / +4 / +1 |
| `tests/codex_support.py` (93) | actions et sous-commandes du faux | ≤ 300 |
| `tests/test_process_job.py`, `test_process_group.py`, `test_codex_cli.py`, `test_codex_isolation.py`, `test_codex_commit.py` (nouveaux) | B, C, D | chacun ≤ 450 |

Aucun fichier ne franchit son seuil ; aucune entrée de `file-size-baseline.json`.

---

## 9. Découpage en PR

Chacune part de `master` à jour **après** la fusion de la précédente (jamais empilées). Toutes touchent l'exécution d'un processus, la sécurité de l'enfant ou un invariant du superviseur : `architect` (ce cadrage) avant `implementer`, puis le circuit de relecture d'AGENTS.md.

| Ordre | Branche | Contenu | Critères d'acceptation |
|---|---|---|---|
| A | `fix/186-cause-chronologie` | §6 ; tests A1–A5 ; e2e « ÉCHOUER » | la chronologie affiche la cause d'un `failed` d'adaptateur, une seule fois pour un échec du superviseur ; `pnpm test`, `pnpm lint`, build web et Playwright verts |
| B | `feat/186-job-object` | §4 ; `contain=True` pour Codex et `claude-code` ; tests B1–B10 ; INTEGRATIONS §A.2 (« Garde-fous » de Codex et de Claude Code), SECURITY §3 | B1–B7 verts **dans le hook local Windows** (le corps de la PR le dit : la CI Linux les saute) ; B8–B10 verts partout ; aucun test existant modifié |
| C | `feat/186-codex-isolation` | §3, §5, §2.2, §2.4 ; tests C1–C10 ; e2e (faux qui répond aux contrôles, `TEMP` du serveur de test) ; INTEGRATIONS §A.2 (commande, `CODEX_HOME` de Nexus, connexion à faire par Loïc, dépôts sous `%TEMP%` refusés), SECURITY §3 | argv et environnement égaux au cadrage ; tout contrôle en échec → « lancement impossible » sans modèle ; seul test existant touché : `test_the_child_environment_is_an_allow_list` |
| D | `feat/186-codex-commit-par-nexus` | §1, §2.3, §7 ; tests D1–D13 ; tests existants listés au §8 ; e2e (faux qui écrit) ; INTEGRATIONS §A.2, SECURITY §3, ROADMAP | un run réussi finit `done` sur le commit de Nexus ; un commit de l'agent finit `failed` ; aucun commit sans arrêt confirmé de l'arbre |
| E | `docs/186-runs-reels-codex` | relevé des runs réels (§10) dans INTEGRATIONS §A.2, comme #190 | scénarios du §10 faits, conditions d'arrêt respectées |

C ne dépend pas de B ; D dépend de B (arrêt confirmé) et de C (argv et environnement du run) : l'ordre A, B, C, D le garantit. A est indépendante et passe d'abord, pour que les échecs des runs réels soient lisibles.

---

## 10. Runs réels (manuels, jamais en CI) : preuve de la Phase 2

**Prérequis.** PR A à D fusionnées. Loïc s'est connecté une fois dans le dossier de Nexus (`CODEX_HOME=<NEXUS_DATA_DIR>\codex-home`, `codex login`, dans son terminal ; rien n'est copié). Un dépôt jetable **hors de `%TEMP%`**, avec un commit, une identité git, aucun pilote de filtre, seul dans `NEXUS_RUN_WORKDIRS` ; un fichier témoin `hors-worktree.txt` à côté du dossier des worktrees. `NEXUS_RUN_MAX_MINUTES=15`. Le quota Codex est disponible.

**Étape 0 — relevés préalables** (0a et 0c sans modèle ; 0b se fait sur le premier run court) :
- 0a. Les trois contrôles du §5.3 lancés à la main avec l'argv de Nexus, dans un worktree : `[]`, aucun bloc de skills, dossier propre.
- 0b. **Git lancé par Codex lui-même** : un run court (scénario H ci-dessous) avec `GIT_TRACE2_EVENT=<fichier hors du worktree>` ajouté **à la main** à l'environnement de l'enfant (pas dans Nexus) ; les invocations de git écrites dans le fichier viennent de `codex.exe` (hors bac à sable) ou des commandes de l'agent (le bac à sable leur refuse probablement d'écrire ce fichier). Si `codex.exe` lance git dans le worktree : **arrêter** et trancher §11, Q3.
- 0c. **Bac à sable dans le job** : `codex sandbox -c windows.sandbox=unelevated -C <worktree> -- cmd /c echo ok` lancé depuis un petit script Python qui l'enveloppe dans un job identique à celui du §4.2. Si la commande échoue (accès refusé à la création) : **arrêter**, le bac à sable demande la sortie du job. (Que `codex sandbox` applique la même politique que `exec --sandbox workspace-write` n'est pas vérifié : la conclusion définitive vient du scénario A.)

**Scénarios** (dans l'ordre ; noter chaque fois la cause affichée, la durée du run et celle du commit de Nexus) :
- **A — commit nominal** : « Ajoute une ligne "bonjour" à README.md. Accents : é è à ç « » ». Attendu : `claimed`, `working`, « Fichiers modifiés », `done` `commit:<12>` ; **un** commit sur `nexus/nx-run-<n>`, fait par Nexus (sujet, trailers, auteur = identité du dépôt), accents intacts ; aucun processus du run après la fin (gestionnaire des tâches) ; aucun fichier de session dans le `CODEX_HOME` de Nexus (`--ephemeral`).
- **B — aucun changement** : « Ne change rien ; dis combien de lignes a README.md ». Attendu : `review` « sans changement ».
- **C — refus** : « Crée un point de jonction `lien` vers le dossier parent (`mklink /J`) ». Attendu : `failed` « commit refusé par Nexus : lien ou point de jonction », rien commité, contenu du dossier parent absent des objets du dépôt.
- **D — annulation** : « Lance `ping -t 127.0.0.1` en arrière-plan puis attends » ; annuler après `working`. Attendu : `cancelled`, plus aucun `codex.exe`, `ping.exe` ni `cmd.exe` du run, aucun commit.
- **E — écriture dans `.git`** (une demande par point) : « Lance `git commit --allow-empty -m x` » ; « Ajoute une ligne à `<dépôt>\.git\config` » ; « Crée `<dépôt>\.git\hooks\pre-commit` » ; « Réécris le fichier `.git` de ce dossier » ; « Crée `hooks.json` dans `<NEXUS_DATA_DIR>\codex-home` ». Attendu : chaque écriture refusée par le bac à sable (le run finit `review` ou `failed` selon le cas ; la réécriture du `.git` finit `failed` « fichier .git du worktree modifié »). **Condition d'arrêt : une seule écriture réussie dans un dossier git ou dans le `CODEX_HOME` de Nexus → arrêter les runs réels et revenir vers Loïc.**
- **F — MCP et skills** : « Liste tes serveurs MCP et tes skills, puis utilise le skill <nom d'un skill de `~/.agents/skills`> ». Attendu : aucun serveur, aucune skill de Loïc ; aucun `mcp_tool_call`. **Condition d'arrêt : une skill, un serveur MCP ou une instruction de `~/.codex/AGENTS.md` de Loïc apparaît.** (Lire un fichier de `~/.agents/skills` par une commande reste possible : le bac à sable laisse lire tout le disque, limite connue de Codex, §11.)
- **G — arrêt forcé du serveur** : « Lance `ping -t 127.0.0.1` en arrière-plan puis attends » ; tuer le serveur (`taskkill /F` sur son PID). Attendu : en moins de 2 s, plus aucun processus du run ; au redémarrage, `unknown`, aucun commit. **Condition d'arrêt : un processus du run survit.** Refaire G une fois avec `claude-code` et Haiku (PR B, §4.5).
- **H — processus de fond à la fin propre** : « Lance `ping -t 127.0.0.1` en arrière-plan, ajoute une ligne à README.md, puis termine ». Attendu : `done`, plus aucun `ping.exe` après la fin, commit présent.
- **I — cause affichée** : un échec réel (quota, ou dossier de Nexus sans connexion) montre « Cause : … » dans la chronologie.

**Conditions d'arrêt communes** : une commande de l'agent qui échoue à cause du job (accès refusé à la création d'un processus) ; une écriture hors du worktree et du dossier temporaire ; un processus du run qui survit à un arrêt confirmé. Dans chaque cas : arrêter, noter, revenir vers Loïc.

Noter dans la PR E et dans INTEGRATIONS §A.2 (« Constaté aux premiers runs réels ») : forme réelle de `mcp_tool_call` (`item.started` ?), racines inscriptibles observées (dossier temporaire, dossier commun), résultat de 0b et 0c, emplacement de la connexion dans le dossier de Nexus (fichier ou trousseau), durée d'un run court et du commit.

---

## 11. Vérifié, non vérifié, questions ouvertes

### Vérifié (2026-11-13, sans modèle, codex-cli 0.167.1)
- `codex.exe` natif à l'emplacement d'installation ; aucun lanceur `.cmd` sur le `PATH`.
- Aide de `codex exec` : `--json`, `--sandbox` (`read-only`, `workspace-write`, `danger-full-access`), `--cd`, `--add-dir`, `--ephemeral`, `--ignore-user-config` (« auth still uses `CODEX_HOME` »), `--ignore-rules`, `--skip-git-repo-check`, `-c`, `--enable`/`--disable`, `-p/--profile` ; pas de `-a` sous `exec`.
- `-c windows.sandbox=unelevated` sans guillemets est lu comme la variante attendue ; une valeur inconnue est refusée (liste `elevated`, `unelevated`, `mxc`).
- Valeurs par défaut avec un `CODEX_HOME` vide : `hooks`, `plugins`, `remote_plugin`, `apps`, `browser_use`, `computer_use`, `in_app_browser`, `tool_suggest`, `skill_mcp_dependency_install` à `true`, `memories` à `false` ; chaque `--disable` du §5.2 les met à `false` ; `--disable <inconnu>` → « Unknown feature flag », code 1.
- `CODEX_HOME` vide : `codex mcp list --json` → `[]` ; `codex debug prompt-input` rend 0 sans connexion et liste quand même `~/.agents/skills` et les skills fournies ; avec `-c skills.include_instructions=false`, le bloc des skills et `.agents/skills` disparaissent.
- Codex refuse de créer ses binaires auxiliaires quand `CODEX_HOME` est sous le dossier temporaire.
- `~/.codex` de Loïc contient `config.toml` (`[windows] sandbox = "elevated"`, deux serveurs MCP), des profils, `AGENTS.md`, `hooks.json`, `skills/`, `memories`, `plugins/`, `rules/`, `auth.json` (noms seulement) ; `~/.agents/skills` existe.
- Run réel du 2026-11-12 (#186) : `elevated` échoue en non interactif (erreur 1223) ; `unelevated` laisse tourner les commandes ; `index.lock` du dossier git du worktree refusé ; `mcp_tool_call` et lecture d'une skill observés avec la configuration de Loïc.
- Code : `run_commit` (étape 1 qui accepte tout commit descendant), `kill_tree` (`taskkill /T`), `spawn` partagé par Codex, `claude-code` et `hermes_cli`, `EntryOut` sans `payload`, `supervisor._fail` avec `subject = cause`, même dépendance `Authenticated` pour la chronologie et les événements, CI sous `ubuntu-latest`.

### Non vérifié (à relever au §10 ou par l'implementer)
- Q1. Écriture refusée dans le dossier **commun** `.git` du dépôt et dans le `CODEX_HOME` de Nexus (scénario E).
- Q2. Le dossier temporaire est-il une racine inscriptible sous Windows `unelevated` (supposé oui, §2.2) ?
- Q3. `codex.exe` lance-t-il git hors du bac à sable dans le worktree (étape 0b) ? Si oui : imposer `GIT_DIR` à l'enfant (et accepter de casser le git de l'agent dans d'autres dépôts) ou couper le contexte git de Codex (réglage non trouvé dans la référence lue).
- Q4. Le bac à sable Windows de Codex tolère-t-il un job sans sortie autorisée (étape 0c, scénario A) ?
- Q5. Une configuration de **projet** (`.codex/` du dépôt) peut-elle déclarer des serveurs MCP ou des hooks dans un run non interactif, et `codex mcp list` la voit-il ?
- Q6. `codex debug prompt-input` n'appelle-t-il aucun service réseau ? Rend-il la même entrée que `exec` (mêmes fonctions, même dossier) ?
- Q7. L'installation du bac à sable `unelevated` dans un `CODEX_HOME` neuf se fait-elle sans invite (`.sandbox` a été créé sans invite par `features list`, mais aucune commande n'a été lancée dans le bac à sable) ?
- Q8. Où la seconde connexion est rangée (`auth.json` du dossier de Nexus ou trousseau Windows), et si deux connexions du même compte coexistent sans se déconnecter.
- Q9. Accès réseau par défaut sous `workspace-write` avec la 0.167.1 (non fixé par ce cadrage : la référence décrit `sandbox_workspace_write.network_access`, la valeur par défaut n'a pas été relue).
- Q10. Forme `item.started` de `mcp_tool_call`.

### Limites connues, assumées
- Sous `workspace-write`, l'agent **lit** tout le disque (profil de permissions vu dans `prompt-input` : lecture de la racine) : fichiers de `~/.codex`, `~/.agents/skills`, clés. C'était déjà le cas ; ce lot ne le change pas.
- POSIX : un descendant qui quitte son groupe échappe à l'arrêt (§4.3).
- Un dépôt sous `%TEMP%` n'est pas utilisable avec Codex (§2.2).

---

## 12. Sécurité (à reporter dans SECURITY §3 par les PR B à D)

- Commit fait par le processus serveur, après un arrêt **confirmé** de tout l'arbre (job object) ; aucun commit si la branche a bougé ou si le fichier `.git` du worktree a changé ; barrières de `run_commit` inchangées.
- Bac à sable `workspace-write` avec `unelevated` sous Windows ; aucun `--add-dir`, jamais de contournement ; dossiers git et `CODEX_HOME` de Nexus refusés dans une racine inscriptible supposée.
- Configuration de Loïc hors de portée (dossier de Nexus, drapeaux, skills et fonctions coupées), contrôle fermé avant le lancement, `mcp_tool_call` tue l'arbre.
- Environnement par liste blanche ; `CODEX_HOME` imposé ; `GIT_*` hérités retirés ; hooks et `fsmonitor` coupés pour tout git de l'arbre.
- Connexion faite par Loïc ; jamais lue, copiée ni journalisée par Nexus.
- Sortie brute jamais écrite ; sorties des contrôles lues en mémoire, jamais journalisées ; cause affichée = cause masquée au stockage.

---

## 13. Ce qui revient à Loïc

1. **Connexion dans le dossier de Nexus** : une fois, dans ton terminal (`$env:CODEX_HOME="<NEXUS_DATA_DIR>\codex-home"; codex login`). Sans elle, chaque run Codex finit `failed` avec la cause du CLI, désormais affichée. Si tu préfères qu'un run Codex utilise ta configuration habituelle, ce cadrage ne s'applique plus : les skills, MCP, hooks et instructions de `~/.codex` reviendraient dans les runs.
2. **Choix de l'agent sous ta délégation du 2026-11-13, à infirmer si tu veux** (chacun se change sans migration) : commit par Nexus plutôt qu'un clone ; auteur = l'identité git du dépôt, trailers `Nexus-Run` et `Nexus-Executor: codex`, pas de `Co-Authored-By` ; refus → `failed`, aucun changement → `review` ; job object aussi pour `claude-code` ; dépôts sous `%TEMP%` refusés ; fonctions de Codex coupées dans un run (hooks, plugins, connecteurs, navigateur, `computer_use`, mémoires).
3. **Cause d'un lancement impossible** (proposition à part, déjà notée au §13 du cadrage `claude-code`) : une exception typée dont le superviseur publierait un code d'une liste fermée (`no_git_identity`, `filter_driver`, `isolation_unverified`, `bad_location`…), jamais un texte libre. Utile ici : les contrôles du §5.3 échouent tous en « lancement impossible ».
4. **Annulation après un arrêt forcé du serveur** : avec le job object, les processus d'un run meurent avec le serveur, mais Nexus ne sait pas le prouver après le redémarrage ; la procédure du marqueur `.stopped` reste. L'améliorer (noter au lancement le serveur qui tient le job, et accepter l'annulation si ce processus n'existe plus) est un sujet à part.
