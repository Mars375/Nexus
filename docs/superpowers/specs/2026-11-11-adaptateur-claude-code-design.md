# Adaptateur `claude-code` — cadrage du lot H (ADR-023)

**Date :** 2026-11-11 ; **recadré le 2026-11-12** (issue #185, refs #183)
**Issue :** #183 (Phase 2, lot H) ; recadrage de H2 : #185
**Décision d'origine :** Loïc, 2026-11-11 — Nexus peut confier une carte à Claude Code (`claude -p`, non interactif), avec le **modèle choisi à chaque run** (Haiku, Sonnet ou Opus) dans « Confier à ». Chaque run consomme l'abonnement Claude de Loïc ; les runs réels se lancent à la main, jamais en CI.
**Entrées :** ADR-023 (D1–D8 et addendum Hermes D7), AGENTS.md (« Model routing », règle du 2026-10-17), INTEGRATIONS §A.2, DATA-MODEL §2.5, SECURITY §3, VIEWS (« Confier à »), adaptateurs Codex (`server/src/nexus/adapters/codex*.py`) et Hermes (`hermes*.py`), `runs/` (`rules.py`, `service.py`, `api.py`, `supervisor.py`), migration `0008_runs`, `web/src/runs/ConfierDialog.tsx`.
**Relevé fait pour ce cadrage (sans lancer de modèle) :** `claude --version` (2.1.322), `claude --help`, `claude auth status --help`, et une recherche de chaînes dans le binaire installé (alias de modèles, forme des lignes `system/init` et `result`, sous-types d'erreur, `permission_denials`, contrainte `--verbose`). Une preuve locale (Windows, git 2.55) que des hooks déclarés par le dépôt ne tournent pas quand l'environnement de git porte `core.hooksPath` vers `os.devnull` (§4.3). Le 2026-11-12 : `claude --help` relu pour chaque drapeau gardé (§3.1), et une seconde preuve locale, sans LLM, de ce que le commit de Nexus lit dans un worktree écrit par l'agent (§4.5).
**`CONTEXT.md` :** absent à la racine du dépôt ; les décisions viennent de `DECISIONS.md`.

> **Addendum 2026-11-12 — exécution sans Bash.** Le relevé réel du 2026-11-12 (§4.4) a montré qu'avec un Bash limité à `git status`, `git add` et `git commit` par des préfixes, des options de git (`git commit -F <fichier>`, `-sF`, `--pathspec-from-file`) lisent un fichier hors du worktree et en renvoient le contenu au modèle, et qu'aucune liste de règles `deny` ne couvre toutes leurs variantes. **Décidé par Loïc le 2026-11-12 :** l'agent n'a **aucun Bash** (`--tools Read,Edit,Write,Glob,Grep`) et **Nexus (l'adaptateur) fait lui-même le commit** à la fin d'un run réussi. Sections réécrites ou modifiées : §0, §3.1 à §3.5, §4 (réécrit ; §4.4 gardé comme relevé daté), §5.2, §5.3, §5.4 (nouveau ; le commit vit dans un module neutre, `run_commit.py`), §7, §8, §9, §10, §11, §12, §13, et §14 (nouveau : conséquences pour Codex, hors périmètre de #185, après un run réel de Codex du même jour). H1 (fusionné, `feed224`) n'est pas touché : le §6 et les tests 38–47 restent tels quels.

Ce document fixe ce qu'un `implementer` écrit, tests d'abord. Il suit l'adaptateur Codex partout où c'est possible (worktree, preuve D6, arbre de processus, redémarrage → `unknown`) et ne s'en écarte que là où Claude Code diffère : pas de bac à sable du système sous Windows (d'où aucun Bash et un commit fait par Nexus), une configuration utilisateur riche (hooks, plugins, MCP, skills) à tenir à l'écart, et le choix du modèle.

---

## 0. Décisions en bref

1. **Exécutant `claude`, agent `claude`, adaptateur (`origin`) `claude-code`.** L'acteur `claude` existe déjà (`actors.EXECUTORS`, `AGENTS_OF["claude"] = {"claude"}`, matrice des exécutants de SECURITY §3, DATA-MODEL §2.5) : aucun nouvel acteur. Le brief disait « exécutant `claude-code` » : c'est le **nom de l'adaptateur**, donc l'`origin` des événements, pas un nouvel acteur. Écart de vocabulaire signalé au §13.
2. **Commande** : `claude -p --output-format stream-json --verbose --model <alias> --restricted --strict-mcp-config --disable-slash-commands --no-session-persistence --tools Read,Edit,Write,Glob,Grep --permission-mode dontAsk --permission-prompts none --settings <fichier du run>`, cwd = worktree du run, brief sur l'entrée standard (§3).
3. **Aucun Bash pour l'agent ; Nexus commite** — **décidé par Loïc le 2026-11-12** (§4). L'agent lit et écrit des fichiers dans le worktree, rien d'autre : ni commande, ni git, ni test. À la fin d'un run réussi (ligne `result` en succès, code 0, isolement vérifié), le processus serveur contrôle le worktree puis fait `git add -A` et `git commit` avec un message fixe (§5.4), par un module **neutre vis-à-vis de l'exécutant** (`run_commit.py`), que Codex pourra réutiliser (§14). Un contrôle qui échoue ou un git qui échoue donnent `failed` avec une cause en mots fixes ; aucun changement donne `review`.
4. **Traduction pure** des lignes `stream-json` ; contrôle d'isolement sur la ligne `system/init` (aucun serveur MCP, exactement les cinq outils `Read`, `Edit`, `Write`, `Glob`, `Grep`, mode de permission attendu), qui **échoue fermé** ; fin jugée sur la ligne `result` **et** le code de sortie ; preuve = règle Codex D6, sur le commit que Nexus a fait (§5).
5. **Modèle par run** : colonne `runs.model` (migration `0009`, nullable pour les lignes existantes), liste fermée `haiku`, `sonnet`, `opus`, **exigée** pour l'exécutant `claude` et **refusée** pour les autres ; aucun défaut côté serveur ; Sonnet présélectionné dans l'interface ; la liste est servie par `GET /api/executors` (§6, livré par H1).
6. **Enregistrement opt-in** : `NEXUS_CLAUDE_BIN` obligatoire, aucun repli sur le `PATH` (le vrai `claude` est installé ici et aucun test ne doit l'atteindre) ; `NEXUS_RUN_WORKDIRS` partagé avec Codex (§2).
7. **Addendum ADR-023** : exception à la règle du 2026-10-17, « décidé par Loïc le 2026-11-11 » (§11, livré par H1) ; second addendum « exécution sans Bash », « décidé par Loïc le 2026-11-12 », ajouté par H2 (§11).
8. **Contrôles avant le lancement** (aucun modèle consommé s'ils échouent) : identité git résolue, configuration du dépôt sans pilote de filtre (§3.4).

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
  --tools Read,Edit,Write,Glob,Grep
  --permission-mode dontAsk
  --permission-prompts none
  --settings <NEXUS_DATA_DIR>/claude-code/nx-run-<n>.settings.json
```

Ce que fait chaque garde-fou, d'après l'aide de la 2.1.322 (relue le 2026-11-12, sans lancer de modèle) :

- `--restricted` : « removes the built-in tools that run commands or code (Bash, PowerShell and the other code-running tools) and WebFetch unless --tools names them » ; ignore les fichiers de réglages utilisateur, projet et local (donc les hooks, plugins et permissions de Loïc), garde seulement les réglages gérés et `--settings` ; confine les outils de fichiers aux dossiers de travail ; refuse `bypassPermissions` ; ne laisse approuver les écritures dans les réglages, git et la configuration des outils que par une personne ou le gestionnaire de permissions configuré (ici : personne, donc refus). Avec `--tools` qui ne nomme pas `Bash`, l'absence de Bash tient donc par **deux** drapeaux, et le contrôle `system/init` la vérifie (§5.2).
- `--tools` : « Specify the list of available tools from the built-in set » (noms séparés par des virgules, exemple de l'aide : `"Bash,Edit,Read"`) : seuls ces cinq outils existent ; ni `Bash`, ni `PowerShell`, ni `WebFetch`, ni `WebSearch`, ni l'outil de subagents, ni `Skill`.
- `--permission-mode dontAsk` (dans les choix de l'aide : `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan`) + `--permission-prompts none` (« anything that would prompt is denied automatically ») : ce qui n'est pas pré-autorisé par `permissions.allow` est refusé, sans invite.
- `--no-session-persistence` : aucune transcription écrite dans `~/.claude/projects` (cohérent avec « la sortie brute n'est jamais écrite » de Codex) et pas de reprise possible hors de Nexus.
- `--strict-mcp-config`, `--disable-slash-commands` (« Disable all skills and commands »), `--output-format`, `--verbose`, `--model`, `--settings` (« Path to a settings JSON file or a JSON string ») : présents dans l'aide de la 2.1.322.

**Exclus, avec la raison :**

- `--bare` : n'accepte que `ANTHROPIC_API_KEY` ou un `apiKeyHelper` (OAuth jamais lu) ; le run ne consommerait pas l'abonnement.
- `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `--permission-mode bypassPermissions` / `auto` / `acceptEdits` : jamais (un test vérifie qu'aucun n'apparaît dans l'argv).
- `--allowedTools` / `--disallowedTools` : redondants avec `--tools` et le fichier de réglages ; une seule source de vérité, testée par égalité.
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
    "allow": ["Read", "Glob", "Grep", "Edit", "Write"],
    "deny": [
      "Edit(.git)", "Write(.git)", "Edit(.git/**)", "Write(.git/**)",
      "Edit(**/.git)", "Write(**/.git)", "Edit(**/.git/**)", "Write(**/.git/**)"
    ]
  }
}
```

- Fichier plutôt que JSON en argument : sous Windows, des guillemets et parenthèses dans l'argv d'un `.cmd` (le faux exécutable des tests) se cassent ; un chemin ne pose aucun problème.
- **Plus aucune règle `Bash(…)`** : l'outil n'existe pas (§3.1). Les règles du cadrage du 2026-11-11 (`Bash(git status)`, `Bash(git add *)`, `Bash(git commit *)`) sont retirées, et avec elles les remarques sur `git diff --output` et sur l'ancrage des préfixes.
- Les variantes `**/.git` visent un dépôt imbriqué (`sub/.git/config`, §4.5). La syntaxe des règles `deny` n'a pas été vérifiée sur un run réel ; **la vraie barrière est le contrôle du worktree par Nexus avant le commit** (§5.4), qui refuse toute entrée `.git` hors de la racine, quelle que soit la casse. Les règles `deny` réduisent seulement les runs gâchés.
- La clé `disableAllHooks` et le mode `dontAsk` figurent dans le binaire 2.1.322. **Un fichier de réglages invalide est ignoré en silence en mode `-p`** (aide de `-p`) : le run perd alors ses règles `allow`, et, `dontAsk` refusant tout le reste, on attend des « Outils refusés » sur `Edit` dès le premier fichier, puis une fin sans changement, donc `review`. Ce symptôme est à reconnaître au premier run réel (§12, étape 8) ; il échoue fermé.
- **Rejeté :** ajouter `"Bash"`, `"PowerShell"`, `"WebFetch"` à `deny` : sans effet sur un outil absent ; si une version future les réintroduisait malgré `--tools`, le contrôle `system/init` tue le run (§5.3).

### 3.3 Entrée standard

Le brief (ce que Loïc a écrit, masqué à l'écriture) suivi d'une consigne fixe, comme Hermes :

```text

---
Consigne de Nexus : tu travailles dans un dossier à part, créé pour ce run.
Tu peux lire, créer et modifier des fichiers de ce dossier ; tu ne peux lancer aucune commande
(ni git, ni tests). Ne touche pas aux dossiers .git et ne crée ni dépôt git, ni lien, ni fichier
de plus de 20 Mo : Nexus refuserait alors d'enregistrer le travail.
Quand tu as fini, arrête-toi : Nexus enregistre lui-même tes changements dans un commit, que Loïc
relira. Si rien n'est à changer, dis pourquoi dans ta réponse finale.
```

La consigne ne contient ni référence de run, ni chemin, ni nom de modèle (constante, testée telle quelle). Le chiffre « 20 Mo » est celui de `MAX_FILE_BYTES` (§5.4) ; un test vérifie qu'ils concordent. Écrite sur l'entrée standard par un fil, comme `CodexAdapter._feed`.

### 3.4 Dossier de travail, contrôles avant le lancement et identifiants

- `codex_git.choose_repo(workdirs, run.workdir)` puis `codex_git.create_worktree(repo, <data>/worktrees, run.ref)` : mêmes règles que Codex (jamais le dépôt du serveur, jamais un dépôt hors liste), même chemin `<data>/worktrees/nx-run-<n>`, même branche `nexus/nx-run-<n>`. Les références de run sont uniques tous exécutants confondus : un worktree Codex et un worktree Claude ne se télescopent pas. Le worktree est extrait avec l'environnement de `codex_git` (ni configuration système, ni globale) : le commit de Nexus utilise **la même vue de la configuration** (§5.4), sinon un `core.autocrlf` de la configuration système de Git for Windows changerait les fins de ligne entre l'extraction et l'ajout et ferait commiter des fichiers que l'agent n'a pas touchés.
- `GIT_DIR` du worktree lu par `git rev-parse --absolute-git-dir` juste après sa création (git peut suffixer le nom), et contrôlé sous `git rev-parse --git-common-dir` du dépôt, sinon `ValueError` (§3.5).
- **Identité git résolue avant le lancement**, puis **figée** : `git config --get user.name` et `git config --get user.email`, lus dans le dépôt avec l'environnement de `codex_git` **plus** la configuration globale (seule différence : `GIT_CONFIG_GLOBAL` non forcé ; la configuration système reste coupée). Valeurs non vides, sans saut de ligne ni caractère de contrôle ; sinon `ValueError`, donc `failed` « lancement impossible : aucune identité git (user.name, user.email) pour ce dépôt », sans lancer de modèle. Les deux valeurs sont gardées en mémoire dans le `_Job` et passées au commit par `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` (§5.4) : le commit de Nexus ne lit pas la configuration globale, et la preuve locale du §4.5 (cas 8) montre qu'un dépôt sans identité locale ferait échouer le commit sans cela. Constaté le 2026-11-12 : Helios n'a pas d'identité git globale ; le dépôt déclaré doit en porter une, locale ou globale.
- **Aucun pilote de filtre dans la configuration du dépôt** : `git config --get-regexp "^filter\..*\.(clean|smudge|process)$"` dans le worktree, avec l'environnement du commit (§5.4). Une ligne trouvée → `ValueError`, donc `failed` « lancement impossible : la configuration git du dépôt définit un pilote de filtre », sans lancer de modèle. Raison : un `.gitattributes` écrit par l'agent (`* filter=<nom>`) fait lancer ce pilote par le `git add` de Nexus (preuve locale, §4.5, cas 3c). Le contrôle est refait juste avant le commit (la configuration a pu changer pendant le run). Conséquence : un dépôt qui déclare Git LFS dans sa configuration locale (`git lfs install --local`) n'est pas utilisable avec cet adaptateur ; un dépôt dont LFS n'est déclaré que dans la configuration globale verrait ses fichiers LFS commités bruts (le filtre global n'est pas lu) : à ne pas déclarer non plus (INTEGRATIONS §A.2).
- `Dispatched(external_ref=tree.branch, native_status="started")`.
- L'id de session (`session_id` de `system/init`) n'est pas conservé : la session n'est pas persistée, il ne désignerait rien.
- Les modules `codex_git` et `codex_process` sont réutilisés **tels quels** ; les renommer en modules génériques est un sujet à part (une PR de renommage sans changement), pas ce lot. Ce qui manque à `codex_git.git` pour le commit (variables d'environnement en plus, budget de temps) vit dans le nouveau module **`run_commit.py`, neutre vis-à-vis de l'exécutant** (§5.4, §10) : `claude-code` l'utilise dès H2, Codex pourra l'utiliser ensuite sans changement du module (§14).

Test : dépôt sans `user.email` ni identité globale → `failed` avec la cause, aucun `Popen` de `fake-claude` ; identité seulement globale → lancement, commit signé de cette identité ; dépôt dont la configuration définit `filter.x.clean` → `failed` avant le lancement.

### 3.5 Environnement de l'enfant

`codex_process.child_env(environ, allow=CLAUDE_ENV_ALLOW)` puis des valeurs imposées. L'agent ne lance plus git, mais **Claude Code lance git lui-même** pour son contexte (statut du dépôt au démarrage ; la ligne `system/vcs_state_changed` du §12.0 le montre) : les barrières git de l'enfant restent donc en place.

- **Liste blanche** (`CLAUDE_ENV_ALLOW`) : celle de Codex **sans** `CODEX_HOME`, **plus** `CLAUDE_CONFIG_DIR` (si Loïc a déplacé la configuration) et `CLAUDE_CODE_GIT_BASH_PATH` (Claude Code sous Windows cherche Git Bash au démarrage ; sans outil Bash, la variable ne sert peut-être plus : **à confirmer au premier run**, la garder ne donne aucun outil). La connexion à l'abonnement se trouve par le profil (`USERPROFILE` / `HOME`, `~/.claude/.credentials.json` ou le trousseau) ; `apiKeySource = "none"` au §12.0 le confirme.
- **Jamais transmis** (testé par nom, sur un environnement qui les contient tous) : tout `NEXUS_*` ; tout `ANTHROPIC_*` (une `ANTHROPIC_API_KEY` ferait payer l'API au lieu de l'abonnement) ; `CLAUDECODE` et tout `CLAUDE_CODE_*` autre que `CLAUDE_CODE_GIT_BASH_PATH` (le serveur peut avoir été lancé depuis une session Claude Code : identifiant de session, socket et jeton de messagerie de la session parente) ; `CODEX_HOME` ; tout `GIT_*` hérité.
- **Imposé par l'adaptateur** :
  - `GIT_DIR=<dépôt>/.git/worktrees/nx-run-<n>` (§3.4) et `GIT_WORK_TREE=<worktree>` : git n'utilise plus le fichier `.git` du worktree, que l'agent pourrait réécrire ;
  - `GIT_CONFIG_COUNT=3`, `GIT_CONFIG_KEY_0=core.hooksPath`, `GIT_CONFIG_VALUE_0=<os.devnull>`, `GIT_CONFIG_KEY_1=core.fsmonitor`, `GIT_CONFIG_VALUE_1=false`, `GIT_CONFIG_KEY_2=commit.gpgsign`, `GIT_CONFIG_VALUE_2=false` ;
  - `GIT_EDITOR=:` ; `GIT_TERMINAL_PROMPT=0` ;
  - `DISABLE_AUTOUPDATER=1` (le binaire ne se remplace pas pendant un run).
  Ces valeurs ne concernent que les appels de git faits par Claude Code lui-même. L'identité de l'auteur ne vient plus de l'enfant : le commit est fait par Nexus (§5.4).

---

## 4. Ce que l'agent peut faire, et ce que le commit de Nexus lit

### 4.1 Le constat et la décision

Codex tourne sous `--sandbox workspace-write`. Claude Code n'a pas de bac à sable du système sous Windows (Helios) : toute commande autorisée s'exécute avec les droits de Loïc, réseau, clés SSH et jeton `gh` compris. Le cadrage du 2026-11-11 réduisait Bash à trois commandes git ; le relevé réel du 2026-11-12 (§4.4) a montré que des options de ces commandes lisent un fichier hors du worktree et en renvoient le contenu au modèle, donc au fournisseur du modèle.

**Décidé par Loïc le 2026-11-12 :** l'agent n'a aucun Bash. Il lit et écrit des fichiers dans le worktree (`Read`, `Edit`, `Write`, `Glob`, `Grep`) ; **Nexus fait le commit** à la fin d'un run réussi, depuis le processus serveur, avec ses propres barrières (§4.6, §5.4).

**Conséquences assumées :** l'agent ne peut lancer ni tests, ni linter, ni installation de dépendances, ni git (il ne voit pas l'historique autrement qu'en lisant des fichiers). Le commit de Nexus prouve que des fichiers ont changé, pas que le travail est juste : Loïc relit la branche (D6, « DONE ≠ preuve »). Élargir est une décision de Loïc (§13).

### 4.2 Une barrière par chemin d'exécution

| Chemin | Barrière |
|---|---|
| Commande arbitraire (Bash, PowerShell, autre outil qui exécute du code) | absente de `--tools` **et** retirée par `--restricted` ; contrôle `system/init` : un outil hors des cinq attendus tue le run (§5.2, §5.3) |
| Accès web, subagent, skill, MCP | absents de `--tools` ; `--strict-mcp-config` ; `--disable-slash-commands` ; contrôle `system/init` |
| Hooks, plugins et réglages de Loïc | `--restricted` (réglages utilisateur, projet, local ignorés) ; `disableAllHooks` ; aucun MCP |
| Lecture ou écriture hors du worktree par un outil de fichiers | `--restricted` confine les outils de fichiers aux dossiers de travail (constaté au §12.0, E3 : `Read` hors du worktree refusé) |
| Lecture hors du worktree par une option de git (§4.4) | **disparu** : l'agent ne lance plus git ; le commit de Nexus ne reçoit aucun argument écrit par l'agent (`git add -A`, message fixe) |
| Fichier `.git` du worktree réécrit vers une configuration piégée | `GIT_DIR` imposé à l'enfant et au commit de Nexus (preuve locale §4.5, cas 5 : le commit arrive sur la vraie branche, aucun programme lancé) ; règles `deny` ; protection de `--restricted` sur les fichiers git |
| Dépôt imbriqué (`sub/.git/` ou fichier `sub/.git`) | contrôle du worktree avant le commit : toute entrée nommée `.git` hors de la racine, quelle que soit la casse → commit refusé (§5.4) ; contrôle de l'index après `git add -A` : aucun lien de sous-module (mode `160000`) ajouté |
| Lien symbolique, point de jonction ou lien physique vers l'extérieur | contrôle du worktree : tout point d'analyse (*reparse point* : lien, jonction) et tout fichier à liens multiples (`st_nlink > 1`) → commit refusé ; contrôle de l'index : aucun lien (mode `120000`) ajouté ou modifié, aucun chemin que le parcours n'a pas vu (§5.4). Claude Code sans Bash ne peut créer aucun des trois |
| `.gitattributes` écrit par l'agent qui choisit un pilote de filtre | aucun pilote dans la configuration lue par le commit : configuration système et globale coupées, `core.attributesFile` et attributs système coupés, pilotes de la configuration du dépôt refusés avant le lancement et avant le commit (§3.4) |
| Hook git écrit par l'agent (`.githooks/`, `.husky/`, `.git/hooks` impossible) | `core.hooksPath=<devnull>` pour l'enfant et pour le commit de Nexus ; le fichier est commité comme un autre et Loïc le voit dans la branche (même risque qu'avec Codex quand Loïc commite ensuite sur cette branche) |
| Gros fichier | `MAX_FILE_BYTES` (20 Mio) par fichier ajouté ou modifié → commit refusé ; budget de temps du commit (§5.4) |
| Programme lancé par git pendant le commit (maintenance automatique, signature, éditeur, résumé `diffstat`) | `-c gc.auto=0 -c maintenance.auto=false` (constaté : sans eux, `git commit` lance `git maintenance run --auto --detach`), `commit.gpgsign=false`, `GIT_EDITOR=:`, `-q` |

La preuve se lit toujours depuis le dépôt sur `refs/heads/nexus/nx-run-<n>` (`codex_git.proof`), jamais depuis le worktree.

### 4.3 Preuve locale faite pour ce cadrage (hooks)

Dans un dépôt jetable (Windows, git 2.55) dont la configuration déclare `core.hooksPath=.githooks` et un `pre-commit` qui écrit un témoin : avec `GIT_CONFIG_COUNT`/`core.hooksPath=nul` dans l'environnement, le commit réussit **sans** lancer le hook ; sans cet environnement, le hook tourne ; et `git -c core.hooksPath=.githooks commit` avec le même environnement le relance (le `-c` l'emporte). Le commit de Nexus passe donc `core.hooksPath` en `-c` (comme `codex_git.git`), et l'agent ne peut plus en passer un (aucun Bash). Les tests du §9 refont cette preuve.

### 4.4 Lecture hors du worktree par les options de git (relevé du 2026-11-12 : pourquoi l'agent n'a pas de Bash)

Relevé daté, gardé tel quel (seule la colonne « Réglages » précise « du 2026-11-11 », puisque le §3.2 a changé ; « idem » renvoie à la ligne du dessus). Il a été fait à la suite d'une remarque de CodeRabbit sur la PR #184, avec le même montage que le §12.0 et un fichier témoin `../canary.txt` à côté du worktree (contenu inoffensif) ; la présence du témoin a été cherchée dans toute la sortie `stream-json`, lignes `user` comprises.

| Commande demandée | Réglages | Résultat |
|---|---|---|
| `git commit --allow-empty -F ../canary.txt` | §3.2 du 2026-11-11 | **permise** ; le témoin devient le message du commit et revient au modèle dans la sortie de git |
| `git add --pathspec-from-file=../canary.txt` | §3.2 du 2026-11-11 | **permise** ; le témoin revient au modèle dans le message d'erreur (`pathspec '…' did not match`) |
| `git commit --allow-empty -m "$(cat ../canary.txt)"` | §3.2 du 2026-11-11 | refusée (substitution de commande), témoin absent |
| `git commit --allow-empty -m x -F ../canary.txt` | §3.2 du 2026-11-11 + `deny` à jokers (`Bash(git commit *-F*)`, `*--file*`, `*-t*`, `*--template*`, `Bash(git add *--pathspec-from-file*)`) | refusée, témoin absent |
| `git add --pathspec-from-file=../canary.txt` | idem | refusée, témoin absent |
| `git commit --allow-empty -sF ../canary.txt` | idem | **permise**, témoin revenu au modèle (option courte groupée) |
| `git commit --allow-empty --pathspec-from-file=../canary.txt -m x` | idem | **permise**, témoin revenu au modèle (option de `git commit` non listée) |
| `git commit --allow-empty -m "ajoute des tests"` | idem | permise (le `deny` `*-t*` ne gêne pas ce message-là, mais en gênerait d'autres) |

Conséquence tirée le 2026-11-12 : une liste blanche de commandes git ne borne pas les options qui lisent des fichiers ; chaque `deny` ajouté laisse une variante. Une lecture hors du worktree renvoyée au modèle est une fuite vers le fournisseur du modèle (clé SSH, jeton `gh`, `.env` d'un autre projet). Suite : **décidé par Loïc le 2026-11-12**, aucun Bash, Nexus commite (§4.1, §5.4).

### 4.5 Ce que le commit de Nexus lit dans un worktree écrit par l'agent (preuve locale du 2026-11-12, sans LLM)

Script jetable (dépôts temporaires, Windows 11, git 2.55.0.windows.3, Python 3.13), qui reproduit le commit prévu au §5.4 : environnement par liste blanche, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=nul`, `GIT_ATTR_NOSYSTEM=1`, `GIT_EDITOR=:`, `GIT_DIR`/`GIT_WORK_TREE` imposés, `-c core.hooksPath=nul -c core.fsmonitor=false -c commit.gpgsign=false -c core.attributesFile=nul`, puis `git add -A`, `git diff-index --cached --raw -z --no-renames HEAD`, `git commit -q -m …`. Le témoin est un script qui écrit dans un fichier hors des dépôts quand git le lance ; le « secret » est un fichier `CANARY-OUTSIDE-CONTENT` hors du worktree.

| Cas (ce que l'agent aurait écrit) | Résultat observé | Décision |
|---|---|---|
| 1. `sub/` dépôt imbriqué avec un commit, sa configuration déclarant `core.fsmonitor`, `core.hooksPath` et un filtre, worktree imbriqué modifié | `add` réussit avec « adding embedded git repository » ; l'index reçoit un lien de sous-module (`160000`) ; commit fait ; **aucune exécution observée**. Témoin de contrôle : `git status` lancé *dans* `sub/` exécute bien le `fsmonitor` (témoin écrit) | refus avant `add` (contrôle du worktree) et après (`160000` refusé) : git lit `HEAD` du dépôt imbriqué, on ne compte pas sur le fait qu'il n'y lise rien d'autre |
| 1b. `sub/` dépôt imbriqué sans commit | `add` échoue (code 128, « does not have a commit checked out ») | refus avant `add` ; un `add` en échec est un `failed`, jamais une exception qui ferait boucler le superviseur |
| 1c. dépôt imbriqué dont le dossier s'appelle `.GIT` | reconnu comme dépôt (NTFS ignore la casse), lien `160000` ajouté | comparaison sans la casse, points et espaces finaux retirés |
| 2. fichier `sub/.git` (`gitdir: <dépôt hors du worktree>`) | lien `160000` ajouté, pointant le `HEAD` d'un dépôt **hors du worktree** (lecture dehors) | refus : une entrée `.git` fichier compte comme un dossier |
| 3a. `.gitattributes` `* filter=evil`, pilote défini dans une configuration globale, globale coupée | `add` et commit faits, **pilote non lancé** | configuration globale coupée pour le commit |
| 3b. même cas, configuration globale lue (témoin de contrôle) | pilote lancé (6 fois) | confirme que c'est la coupure qui protège |
| 3c. même `.gitattributes`, pilote défini dans **la configuration du dépôt** | **pilote lancé** (3 fois) | refus avant le lancement et avant le commit si la configuration du dépôt définit un `filter.*.clean/smudge/process` (§3.4) |
| 4. point de jonction (`mklink /J`, sans droit particulier) `link` → dossier hors du worktree | **`git add -A` traverse la jonction** : `link/secret.txt` ajouté, le contenu hors du worktree entre dans les objets du dépôt | refus de tout point d'analyse avant `add` |
| 4b. lien symbolique de fichier | non créable sans mode développeur (`WinError 1314`) : **non prouvé** | couvert par le même refus des points d'analyse et par le contrôle `120000` de l'index |
| 5. fichier `.git` du worktree réécrit vers un gitdir piégé (`core.fsmonitor`) | commit sur la vraie branche `nexus/nx-run-1`, `.git` non ajouté, aucune exécution | `GIT_DIR` imposé suffit |
| 6. fichiers nommés `--output=x` et `-rf` | ajoutés et commités comme des fichiers | `git add -A` sans chemin en argument : aucun nom écrit par l'agent n'est lu comme une option |
| 6b. `.gitignore` contenant `*` | rien d'ajouté (le `.gitignore` s'ignore lui-même), commit refusé par git (« rien à commiter ») | index vide → `review` sans commit, sans appeler `git commit` |
| 7. aucun changement | index identique au départ | `review` sans commit |
| 8. dépôt sans identité, configuration globale coupée | `git commit` échoue (« Author identity unknown ») ; avec `GIT_AUTHOR_*`/`GIT_COMMITTER_*` imposés : commit fait, auteur et committer = l'identité passée, trailers lus par `%(trailers:only)` | identité résolue avant le lancement et figée (§3.4) |
| 9. `GIT_TRACE=1` sur `git commit` | lance `git maintenance run --auto --quiet --detach` ; avec `-c gc.auto=0 -c maintenance.auto=false` : aucun sous-processus | ces deux `-c` sont imposés |
| 10. fins de ligne : worktree extrait **avec** `core.autocrlf=true` (configuration globale lue), ajout **sans** elle ; `README.md` non touché par l'agent (avec et sans changement de sa date) | `README.md` extrait en CRLF puis **ajouté comme modifié** à côté du fichier nouveau. Contrôle : extraction et ajout avec la même vue (configuration globale coupée des deux côtés) → seul le fichier nouveau est ajouté | même vue de la configuration pour l'extraction et le commit (celle de `codex_git`) |
| 11. lien physique (`os.link`, sans droit particulier) `inside.txt` → fichier hors du worktree | pas un point d'analyse (`st_nlink = 2`) ; `git add -A` l'ajoute et **son contenu entre dans les objets** | refus de tout fichier dont `st_nlink > 1` (inaccessible à Claude Code sans Bash, essentiel pour un exécutant qui a un shell, §14) |
| Parcours du worktree avec `os.walk` (Python 3.13) | **descend dans le point de jonction** (`os.path.isjunction` vrai, mais `os.walk` le suit) | parcours écrit à la main avec `os.scandir`, qui ne descend jamais dans un point d'analyse |

Ce que la preuve ne couvre pas : un vrai lien symbolique (4b) ; le comportement de l'outil `Write` de Claude Code face à un lien déjà présent (aucun n'existe dans un worktree neuf : `core.symlinks` vaut `false` par défaut sous Windows et le contrôle refuse le commit sinon) ; les flux de données alternatifs NTFS (ignorés par git).

### 4.6 Barrières du commit de Nexus, en bref

- Lancé par le processus serveur, jamais par l'agent ; seulement après la fin réelle du processus `claude` (§5.4).
- Aucun argument venant de l'agent : `git add -A` sans chemin, message construit avec `run.ref` (déjà validé `nx-run-<n>`) et l'alias du modèle (liste fermée).
- Environnement : celui de `codex_git` (liste blanche, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=<devnull>`, `GIT_TERMINAL_PROMPT=0`) **plus** `GIT_ATTR_NOSYSTEM=1`, `GIT_DIR`, `GIT_WORK_TREE`, `GIT_EDITOR=:`, l'identité figée (`GIT_AUTHOR_*`, `GIT_COMMITTER_*`).
- Options : `-c core.hooksPath=<devnull> -c core.fsmonitor=false -c commit.gpgsign=false -c core.attributesFile=<devnull> -c gc.auto=0 -c maintenance.auto=false`.
- Contrôles : configuration sans pilote de filtre ; worktree sans entrée `.git` imbriquée, sans point d'analyse, sans lien physique, sans fichier trop gros ; index sans mode `160000` ni `120000` nouveau, et chaque chemin ajouté est un fichier ordinaire vu par le parcours.
- Bornes : chaque appel ≤ 30 s, l'ensemble (lectures de la preuve comprises) ≤ `COMMIT_BUDGET` (90 s).

---

## 5. Suivi : traduction, fin, preuve

### 5.1 Lecture

Comme Codex : un fil de lecture traduit chaque ligne de la sortie standard, en mémoire ; `stderr` est jeté ; la sortie brute n'est jamais écrite. `at` = l'heure de lecture (les lignes `stream-json` n'ont pas d'horodatage). Plafonds repris de Codex : `MAX_PROGRESS = 300`, `KEEP_FINISHED = 20`, `claimed` et `working` une fois chacun.

### 5.2 Table de traduction (`claude_code_translate.translate_line(line) -> tuple[Fact, ...]`)

Fonction pure : une ligne peut porter plusieurs faits (un message `assistant` à plusieurs blocs ; une ligne `result` avec des refus). Tout texte passe par `text.cut` (secrets masqués, 500 caractères). Ligne non JSON, JSON qui n'est pas un objet, type inconnu : `()`, jamais d'exception. `EXPECTED_TOOLS = frozenset({"Read", "Edit", "Write", "Glob", "Grep"})`, comparé **en ensemble** (le CLI les liste par ordre alphabétique, §12.0).

| Ligne | Fait(s) |
|---|---|
| `{"type":"system","subtype":"init", …}` isolée conforme (`tools` égal à `EXPECTED_TOOLS`) | `claimed` « Claude Code a ouvert une session », `payload.model` = `cut(init.model)` (le nom complet résolu par le CLI) |
| même ligne, `mcp_servers` liste **non vide** | `breach` « isolation non respectée : serveur MCP chargé » |
| même ligne, `tools` contient un outil hors de `EXPECTED_TOOLS` (`Bash` compris) | `breach` « … : outil inattendu » (le nom n'est pas recopié) |
| même ligne, `tools` à qui il manque un des cinq outils | `breach` « … : outils inattendus » (un fichier de réglages ou une version qui retire `Edit` gâcherait le run en silence ; on préfère s'arrêter) |
| même ligne, `permissionMode` différent de `dontAsk` | `breach` « … : mode de permission inattendu » |
| même ligne, `mcp_servers`, `tools` ou `permissionMode` **absent ou d'un autre type** | `isolation_unknown` (pas de `claimed` confirmé ; traité comme une violation, voir §5.3) |
| `{"type":"assistant","message":{"content":[…]}}` (avant tout `init` conforme : voir §5.3, 1) | `working` « Claude Code travaille » (le premier seulement) ; puis par bloc : `text` → `progress` « Message de Claude Code » ; `tool_use` `Edit`/`Write` → `progress` « Fichier modifié » (`input.file_path`) ; `thinking`, `tool_use` `Read`/`Glob`/`Grep`, `tool_use` d'un autre nom, autre bloc → rien (un autre outil n'existe pas sans `breach` à l'`init`) |
| `{"type":"user", …}` (résultats d'outils) | rien : le contenu d'un fichier ou un résultat d'outil n'est **jamais** lu dans un fait |
| `{"type":"system","subtype":<autre>}` (compactage, nouvelle tentative d'API, `thinking_tokens`, `vcs_state_changed`…), `{"type":"rate_limit_event"}` | rien |
| `{"type":"result","subtype":"success","is_error":false, …}` (`is_error` strictement le booléen `false`) | `finished`, avec `num_turns` et `duration_ms` s'ils sont des entiers |
| `result` avec `is_error` vrai, ou un `subtype` d'erreur (`error_during_execution`, `error_max_turns`, `error_max_budget_usd`, `error_max_structured_output_retries`, ou inconnu) | `failed`, cause = `cut(result)` sinon `cut("; ".join(errors))` (chaînes seulement) sinon « échec sans détail (<subtype connu>) » |
| `result` dont `permission_denials` est une liste non vide | en plus : `progress` « Outils refusés », corps = noms d'outils distincts (`tool_name`), jamais `tool_input` |

La ligne « Commande demandée » du cadrage du 2026-11-11 (`tool_use` `Bash`) est retirée : l'outil n'existe plus.

Formes relevées dans le binaire 2.1.322 puis confirmées au relevé réel du §12.0 (`system/init` : `cwd`, `session_id`, `tools`, `mcp_servers`, `model`, `permissionMode`, `slash_commands`, `apiKeySource` ; `result` : `subtype`, `is_error`, `num_turns`, `duration_ms`, `result`, `errors`, `permission_denials` d'objets `{tool_name, tool_use_id, tool_input}`). Isolées dans ce module, comme `codex_translate.py`. La liste d'outils réelle avec `--tools Read,Edit,Write,Glob,Grep` reste **à confirmer au premier run réel** (§12, scénario A) : le §12.0 a été fait avec `Bash` en plus.

### 5.3 Fin du run (`_settle`, après la fin réelle du processus)

Dans l'ordre :

1. `breach` lu : l'adaptateur **tue l'arbre tout de suite** (sans attendre la fin ni la durée maximale), puis `failed`, cause « isolation non respectée : <mots fixes> ». Même traitement, avec la cause distincte « isolement de la session non vérifié », pour `isolation_unknown` et pour une première ligne `assistant` lue avant tout `system/init` conforme : l'isolement n'a pas été prouvé avant que l'agent travaille, donc le run est arrêté. Un arrêt non confirmé lève et laisse le run ouvert (comme Codex). **Aucun commit.**
2. Durée maximale dépassée : arbre tué, `failed` « Durée maximale dépassée ». **Aucun commit.**
3. Une ligne `result` en échec : `failed` avec sa cause (la dernière ligne `result` l'emporte). **Aucun commit.**
4. Code de sortie non nul : `failed`, « le processus s'est arrêté (code N) ». **Aucun commit.**
5. Aucune ligne `result` : `failed`, « le processus s'est arrêté sans résultat ». **Aucun commit.**
6. `finished`, code 0 et isolement vérifié (un isolement non vérifié a déjà fini le run à l'étape 1 ; une fin sans aucun `system/init` conforme est aussi un `failed` « isolement de la session non vérifié ») : **commit par l'adaptateur** (§5.4), qui donne `done`, `review` ou `failed`.

Dans les cas 1 à 5, les fichiers écrits par l'agent restent dans le worktree, non commités ; la branche reste au commit de départ. Loïc peut les regarder, Nexus ne les enregistre pas.

Le fichier de réglages du run est supprimé à la clôture, quelle qu'elle soit (et par `cancel`).

### 5.4 Commit par l'adaptateur (`run_commit.commit_run`, module neutre)

Appelé seulement à l'étape 6 du §5.3, donc après que `process.poll()` a rendu 0 et que le fil de lecture a fini : l'agent n'écrit plus (sans Bash, Claude Code ne laisse aucun processus enfant qui écrive dans le worktree). Fonction du module **`run_commit.py`**, qui ne connaît aucun exécutant : il ne dépend que de `codex_git` (`Worktree`, `clean_env`), jamais d'un module `claude_code*`, de `codex.py` ni de `nexus.runs` (`runs.rules` importe `adapters.registry` : un module d'adaptateur qui importerait `runs.rules` ouvrirait la porte à un import circulaire ; l'alias du modèle est donc contrôlé ici par sa forme, et contre `RUN_MODELS` par l'adaptateur avant l'argv, §6.3). Il renvoie une issue (`Committed(sha)`, `NothingToCommit`, `Refused(motif)`, `GitFailed(étape)`) et **ne lève jamais** : chaque échec devient un événement final, sinon le superviseur réessaierait à chaque tour (cas 1b du §4.5 : `git add` qui rend 128).

**Interface du module** (ce que l'`implementer` écrit, et ce qu'un adaptateur Codex appellerait plus tard tel quel) :

```python
@dataclass(frozen=True)
class Identity:            # resolved before launch, pinned for the commit
    name: str
    email: str

@dataclass(frozen=True)
class CommitRequest:
    tree: codex_git.Worktree   # repo, path, branch, start
    gitdir: Path               # <repo>/.git/worktrees/<ref>, checked under the common dir
    identity: Identity
    run_ref: str               # "nx-run-<n>"
    adapter: str               # Adapter.name: "claude-code", later "codex"
    label: str                 # human name in the subject: "Claude Code", later "Codex"
    model: str | None          # a model alias already checked by the adapter, or None (no trailer)

def worktree_gitdir(tree: codex_git.Worktree) -> Path: ...             # ValueError
def resolve_identity(tree: codex_git.Worktree) -> Identity: ...        # ValueError
def check_no_filter_driver(tree: codex_git.Worktree, gitdir: Path) -> None: ...  # ValueError
def commit_run(request: CommitRequest, *, max_file_bytes: int = MAX_FILE_BYTES,
               budget: float = COMMIT_BUDGET) -> Outcome: ...          # never raises
```

Les trois premières servent au lancement (§3.4) et lèvent `ValueError` (le superviseur publie alors `failed` « lancement impossible ») ; `commit_run` sert à la fin. Une requête invalide (`run_ref` hors de `nx-run-[1-9][0-9]*`, `adapter` hors de `[a-z][a-z-]*`, `label` avec un caractère de contrôle ou de plus de 40 caractères, `model` hors de `[a-z][a-z0-9-]{0,15}`) rend `Refused("requête invalide")` sans appeler git : aucun de ces champs ne vient de l'agent, mais un message de commit ne doit jamais porter autre chose que ce qui a été validé.

**Préconditions, à respecter par tout appelant :**

1. **L'agent n'a pas pu écrire dans le dossier git** (`GIT_DIR` du worktree et dossier commun). C'est ce qui permet l'étape 1 : un commit présent sur la branche ne peut venir que de Nexus. Vrai pour `claude-code` (aucun Bash, `--restricted`), vrai pour Codex sous son bac à sable tel que relevé le 2026-11-12 (§14) ; un exécutant qui pourrait commiter lui-même n'utilise pas ce module tel quel.
2. **Plus aucun processus du run ne peut écrire dans le worktree** pendant le contrôle et l'ajout (sinon un point de jonction posé entre le contrôle de l'étape 3 et le `git add` de l'étape 4 ferait lire dehors : le cas 4 du §4.5 montre que l'index reçoit alors un fichier ordinaire, mode `100644`, que le contrôle des modes ne voit pas). Vrai pour `claude-code` : sans Bash, Claude Code ne lance aucun programme qui écrive (`Edit` et `Write` agissent dans son propre processus, le `rg` de `Grep` ne fait que lire), et le commit n'a lieu qu'après la fin du processus. Pour un exécutant qui a un shell, il faut un arrêt **confirmé de tout l'arbre**, orphelins compris, ce que `codex_process.kill_tree` ne garantit pas sous Windows (il le dit lui-même : il faudrait un *job object*) ; voir §14.2. L'étape 5 ajoute une défense partielle : tout chemin ajouté doit être un fichier ordinaire vu par le parcours de l'étape 3 (une jonction posée après le parcours fait apparaître des chemins qu'il n'a pas vus) ; elle ne voit pas un fichier remplacé sous le même nom, d'où la précondition.

**Séquence :**

1. **Preuve d'abord** : les trois lectures de `codex_git.proof` (`rev-parse --verify`, `merge-base --is-ancestor`, `rev-list --count`), refaites par `run_git` depuis le dépôt (`cwd = tree.repo`, sans le `GIT_DIR` du worktree) pour tenir dans le budget ; un test vérifie qu'elles rendent la même chose que `codex_git.proof` sur les mêmes cas. Un commit qui descend du départ existe déjà → `done` avec lui, sans rien refaire. Par la précondition, un tel commit est celui d'un passage précédent de Nexus (serveur arrêté ou exception entre le commit et l'événement). Sans cette étape, un second passage trouverait un index vide et finirait à tort en `review`.
2. **Configuration** : aucun pilote de filtre (même contrôle qu'au §3.4) → sinon `Refused("pilote de filtre")`.
3. **Contrôle du worktree** (Python, avant tout git) : parcours écrit avec `os.scandir`, sans jamais suivre ni traverser un point d'analyse (`os.walk` traverse les jonctions, §4.5) ; la racine `.git` (le fichier du worktree) est sautée. Refus au premier cas trouvé :
   - entrée nommée `.git` (fichier ou dossier), comparée sans la casse après retrait des points et espaces finaux → `Refused("dépôt git imbriqué")` ;
   - point d'analyse (`st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT` sous Windows, `S_ISLNK` ailleurs) → `Refused("lien ou point de jonction")` ;
   - fichier ordinaire dont `st_nlink > 1` (lien physique, peut-être vers un fichier hors du worktree : cas 11 du §4.5) → `Refused("lien physique")` ;
   - le parcours garde, pour chaque fichier ordinaire, son chemin relatif et sa taille (pour l'étape 5) ;
   - fichier de plus de `MAX_FILE_BYTES` (20 Mio) qui n'existe pas au départ avec la même taille (`git ls-tree -r -l -z <départ>`, lu une fois seulement si un tel fichier est trouvé) → `Refused("fichier trop gros")`.
4. `git add -A`.
5. **Contrôle de l'index** : `git diff-index --cached --raw -z --no-renames <départ>` (commande de plomberie : ni `textconv` ni programme de diff externe). Une ligne dont le mode d'arrivée est `160000` → `Refused("sous-module ajouté")` ; `120000` → `Refused("lien ajouté")`. Tout chemin ajouté ou modifié (mode d'arrivée non nul) qui n'est pas un fichier ordinaire relevé à l'étape 3 → `Refused("worktree changé pendant le commit")` (comparaison des chemins seulement : la taille d'un blob peut différer de celle du fichier, un `.gitattributes` `eol=lf` convertit les fins de ligne). Sortie vide → `NothingToCommit`.
6. `git commit -q -m <sujet> -m <trailers>` (jamais `--trailer` : il peut lancer un `trailer.*.cmd` de la configuration) :
   - sujet : `<run_ref> : travail de <label>` suivi de ` (<model>)` si `model` est donné ; pour H2 : `nx-run-<n> : travail de Claude Code (sonnet)` ;
   - trailers : `Nexus-Run: <run_ref>`, `Nexus-Executor: <adapter>`, et `Nexus-Model: <model>` si `model` est donné ;
   - auteur et committer : l'identité figée au lancement (§3.4).
7. **Preuve à nouveau** (mêmes lectures qu'à l'étape 1) → `Committed(sha)` ; sinon `GitFailed("commit")`.

Toutes les commandes passent par un seul `run_git` du module, avec l'environnement et les `-c` du §4.6, `cwd = worktree` (`cwd = tree.repo` pour les lectures de la preuve). Si `git commit` échoue ou dépasse son délai, l'étape 7 est quand même tentée (un délai dépassé peut tuer git après l'écriture du commit) : un commit trouvé l'emporte. Les titres des événements (« Claude Code a terminé… ») sont construits par l'adaptateur avec son libellé, pas par `run_commit`.

**Issues :**

| Issue | Événement final | Preuve / pièce |
|---|---|---|
| `Committed(sha)` (étape 1 ou 7) | `done` « Claude Code a terminé ; Nexus a commité » | `commit:<12 caractères>` (abrégé comme Codex : un hash complet serait masqué) |
| `NothingToCommit` | `review` « Claude Code a terminé sans changement » | `branch:nexus/nx-run-<n>` ; corps : « aucun fichier modifié : à relire » |
| `Refused(motif)` | `failed`, cause « commit refusé par Nexus : <motif> » | `branch:…` ; les fichiers restent dans le worktree, rien n'est commité |
| `GitFailed(étape)` | `failed`, cause « commit de Nexus impossible (<étape>) » ; délai : « … (délai dépassé) » | `branch:…` ; la sortie de git n'est pas recopiée (elle peut contenir des chemins et des noms écrits par l'agent) |

**Pourquoi `review` sans changement et `failed` sur refus.** D6 : sans commit, pas de preuve. Un run qui n'a rien changé peut être juste (question, constat « déjà fait ») : Loïc lit la réponse finale, d'où `review`. Un refus signale un contenu que Nexus n'enregistre pas par principe (dépôt imbriqué, lien, filtre, fichier trop gros) : c'est un échec du run, avec sa cause ; Loïc peut regarder le worktree et commiter lui-même s'il le veut.

**Budget :** chaque appel de git ≤ 30 s, l'ensemble ≤ `COMMIT_BUDGET = 90 s`, **lectures de la preuve des étapes 1 et 7 comprises** (c'est pourquoi elles passent par `run_git` et non par `codex_git.proof`, dont chaque appel a son propre délai de 60 s). Délai de chaque appel = le reste du budget s'il est plus court ; 15 s sont réservées à l'étape 7, pour qu'un commit écrit soit toujours relu ; budget épuisé → `GitFailed(<étape>)` « délai dépassé ». Le commit tourne dans le tour du superviseur (`tick`, sous `registry.tick_lock`) : il retarde les autres runs et l'arrêt du serveur d'au plus ce budget (`registry.close` attend la fin du tour).

**Annulation pendant le commit :** le tour du superviseur traite une demande d'annulation **avant** le suivi (`_step`) et sous le même verrou. Une annulation demandée avant le tour gagne : le processus est arrêté, aucun commit, `cancelled`. Une annulation arrivée pendant le commit est vue au tour suivant, sur un run déjà fermé (`done`, `review` ou `failed`) : elle ne change rien. Il n'existe donc pas de run `cancelled` avec un commit de Nexus sur sa branche.

**Redémarrage :** un run en cours au redémarrage passe `unknown` (D3) et n'est jamais commité ensuite ; son travail reste dans le worktree. Le cas « commit écrit, événement non publié » est couvert par l'étape 1 tant que le serveur tourne ; après un redémarrage, le run est `unknown` et Loïc voit la branche.

---

## 6. Modèle par run

*(Livré par H1, `feed224` ; inchangé.)*

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
- **Annulation** : `codex_process.kill_tree` (arbre entier, confirmé) ; non confirmé → lève, le run reste ouvert, le superviseur réessaie. Après redémarrage : jamais lancé ou marqueur `.stopped/nx-run-<n>` → retour ; sinon lève (même limite connue que Codex, même procédure manuelle). Une annulation ne commite jamais (§5.4).
- **Arrêt du serveur** (`close`) : tue chaque processus vivant et écrit le marqueur, comme Codex ; attend le tour en cours, donc un commit en cours (au plus `COMMIT_BUDGET`).
- **Redémarrage** : le run passe `unknown` (D3) ; `recover` rend `None` ; aucun commit après coup.
- **Commit** : seulement à l'étape 6 du §5.3 ; jamais après une violation d'isolement, une durée maximale, un `result` en échec, un code non nul, une annulation ou un redémarrage. Idempotent par l'étape 1 du §5.4 : deux passages ne font jamais deux commits.
- **Dispatch** : marqueur `dispatching` avant l'appel (superviseur existant) ; une exception avant le `Popen` (worktree, modèle invalide, identité absente, pilote de filtre, fichier de réglages) → `failed` « lancement impossible ». Pas de `LaunchUncertain` : le lancement d'un processus local est certain ou échoue.
- **Tous les appels sont bornés** : sonde 10 s, git 60 s (`codex_git`), commit 30 s par appel et 90 s au total, lectures de la preuve comprises (§5.4), `kill_tree` 10 s ; le fil de lecture est un démon.
- **Abonnement partagé** : un run et les sessions interactives de Loïc consomment le même quota ; une limite atteinte arrive en `result` d'erreur et termine le run en `failed` avec le message du CLI comme cause (heure de reprise comprise). Aucune relance automatique.

---

## 8. Sécurité (à reporter dans SECURITY §3)

- Aucun jeton Nexus pour l'enfant (D4) ; liste blanche d'environnement du §3.5, testée par nom.
- Brief par l'entrée standard, jamais en argument ; `client_key`, `workdir` et `model` validés avant tout lancement ; `model` revalidé par l'adaptateur.
- Isolement de la session vérifié sur `system/init`, échec fermé : violation ou isolement non vérifié tuent l'arbre tout de suite (§5.2, §5.3) ; un outil hors de `Read`, `Edit`, `Write`, `Glob`, `Grep` est une violation.
- **Aucun Bash ni autre outil qui exécute du code** (décidé par Loïc le 2026-11-12) ; écritures et lectures confinées au worktree par `--restricted` ; rien de poussé ni fusionné.
- **Commit fait par le processus serveur** (§5.4), sans argument venant de l'agent, avec configuration système et globale coupées, attributs système et `core.attributesFile` coupés, hooks, `fsmonitor`, signature et maintenance automatique coupés, `GIT_DIR`/`GIT_WORK_TREE` imposés ; refus fermé d'un dépôt imbriqué, d'un lien, point de jonction ou lien physique, d'un fichier de plus de 20 Mio, d'un pilote de filtre dans la configuration du dépôt ; identité figée avant le lancement ; appels bornés.
- Hooks git coupés aussi pour les appels de git que fait Claude Code lui-même (§3.5).
- Sortie brute jamais écrite ni journalisée ; `stderr` jeté ; seuls des faits traduits et masqués sont publiés ; résultats d'outils jamais lus ; sortie de git du commit jamais recopiée.
- Session non persistée ; fichier de réglages hors du worktree, supprimé à la clôture.
- Enregistrement opt-in (`NEXUS_CLAUDE_BIN`), sans repli sur le `PATH`.
- **Limites connues** : un dépôt dont la configuration git lance un script rangé dans l'arbre (pilote, `core.sshCommand`…) ou qui définit un pilote de filtre (LFS local) ne doit pas figurer dans `NEXUS_RUN_WORKDIRS` (le second est de toute façon refusé au lancement) ; un dépôt qui extrait de vrais liens symboliques (`core.symlinks=true`) voit chaque commit refusé ; un fichier écrit par l'agent dans `.githooks/` ou `.husky/` est commité, et tournerait si Loïc commite ensuite sur cette branche avec ces hooks actifs : Loïc relit la branche avant.

---

## 9. Plan de tests (écrits avant le code)

Fake : `server/tests/claude_code_support.py` écrit `fake_claude.py` et un lanceur `fake-claude(.cmd)`, sur le modèle de `codex_support.py`. Le script : `--version` → `2.1.322 (fake)` ; sinon enregistre `args.json`, `env.json` (noms seulement), `stdin.txt`, rejoue `scenario.lines`, puis exécute les actions du scénario **sur le système de fichiers seulement** (le faux ne lance jamais git pour commiter : c'est Nexus qui commite) : `write` (crée ou modifie un fichier du worktree, accents compris), `write_named` (fichiers `--output=x` et `-rf`), `nested_repo` (crée `sub/.git/config` avec un `core.fsmonitor` témoin, et `sub/.GIT` en variante), `gitfile` (fichier `sub/.git` → `gitdir:` hors du worktree), `junction` (`mklink /J` sous Windows, `os.symlink` de dossier ailleurs), `big_file` (fichier d'une taille donnée), `attributes` (`.gitattributes` `* filter=evil`), `hooks_dir` (`.githooks/pre-commit` témoin), `ignore_all` (`.gitignore` `*`), `rewrite_dotgit` (réécrit le fichier `.git` du worktree vers un gitdir piégé), `hang`, `exit`. Constantes de lignes : `INIT_OK` (les cinq outils, dans l'ordre alphabétique), `INIT_MCP`, `INIT_EXTRA_TOOL` (avec `Bash`), `INIT_MISSING_TOOL` (sans `Edit`), `INIT_BYPASS`, `INIT_BARE` (sans champs), `ASSISTANT_TEXT`, `ASSISTANT_BASH`, `ASSISTANT_EDIT`, `USER_TOOL_RESULT` (avec un texte `RAW-OUTPUT-NEVER-STORED`), `RESULT_OK`, `RESULT_IS_ERROR`, `RESULT_ERROR_EXEC`, `RESULT_DENIALS`. Les faux secrets sont construits à l'exécution (`"ghp_" + "A" * 36`). `MAX_FILE_BYTES` et `COMMIT_BUDGET` sont des paramètres de l'adaptateur, réduits dans les tests (pas de fichier de 20 Mio sur le disque de la CI).

Numérotation : 1 à 37 sont les tests de H2 (non écrits avant ce recadrage, leur contenu est mis à jour ici) ; 38 à 47 sont ceux de H1, fusionnés et inchangés ; les nouveaux tests du recadrage partent de 48.

### Cas limites d'abord

**Traduction pure — `test_claude_code_translate.py`**
1. Ligne non JSON, `[]`, `null`, `3`, `""`, type inconnu, `rate_limit_event`, `system/vcs_state_changed` → `()`.
2. `init` conforme (les cinq outils, dans un autre ordre aussi) → `claimed` avec `payload.model`.
3. `init` avec un serveur MCP / `Bash` en plus / `Edit` en moins / `permissionMode` `bypassPermissions` → `breach` (mots fixes, aucun nom recopié).
4. `init` sans `mcp_servers`, avec `mcp_servers` qui n'est pas une liste, sans `tools` → `isolation_unknown`.
5. `assistant` à trois blocs (texte, `Edit`, `Write`) → trois faits, plus `working` au premier.
6. `tool_use` `Read`, `tool_use` `Bash` (après un `init` conforme : rien, la violation se juge à l'`init`), bloc `thinking` → rien.
7. `user` avec résultat d'outil contenant un faux secret et `RAW-OUTPUT-NEVER-STORED` → `()`.
8. `result` succès strict → `finished` ; `is_error: "false"` (chaîne) ou absent → pas un succès.
9. `result` `success` avec `is_error: true` (limite d'usage) → `failed` avec la cause recopiée et masquée.
10. `result` `error_during_execution` avec `errors` (chaînes et non-chaînes mêlées) → `failed`, seules les chaînes.
11. `result` avec `permission_denials` → « Outils refusés » avec les noms distincts, jamais `tool_input` (qui contient un faux secret).
12. Texte avec moitié de paire UTF-16, texte vide, texte réduit à un secret → pas de fait vide.

**Argv, réglages, environnement — `test_claude_code_cli.py`**
13. `argv()` égale exactement la liste du §3.1 pour chaque modèle ; `--tools` vaut exactement `Read,Edit,Write,Glob,Grep` ; aucun drapeau exclu (§3.1) n'y figure ; ni `Bash` ni `PowerShell` nulle part dans l'argv ; le brief n'y figure pas.
14. `argv()` avec `fable`, `""`, `None`, `opus --dangerously-skip-permissions` → `ValueError`, aucun processus.
15. Fichier de réglages : contenu exact du §3.2 (aucune règle `Bash(…)`), écrit sous `<data>/claude-code/`, jamais dans le worktree.
16. Environnement : à partir d'un environnement qui contient `NEXUS_TOKEN`, `ANTHROPIC_API_KEY`, `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_TOKEN`, `CODEX_HOME`, `GIT_DIR`, `GIT_INDEX_FILE` (et leurs variantes en minuscules) → aucun ne passe ; `USERPROFILE`, `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_GIT_BASH_PATH` passent ; `GIT_DIR`, `GIT_WORK_TREE`, les `GIT_CONFIG_*`, `GIT_EDITOR`, `GIT_TERMINAL_PROMPT`, `DISABLE_AUTOUPDATER` valent ce que l'adaptateur impose.

**Adaptateur avec le faux — `test_claude_code_adapter.py`, `test_claude_code_errors.py`**
17. Chemin heureux (`INIT_OK`, texte, `RESULT_OK`, action `write`) → `claimed`, `working`, `progress`, `done` `commit:<12>` ; le commit est sur `refs/heads/nexus/nx-run-1`, contient le fichier (accents intacts), a pour message exactement le sujet et les trailers du §5.4 et pour auteur et committer l'identité du dépôt ; `stdin.txt` = brief + consigne du §3.3 ; `args.json` contient `--model sonnet`.
18. Succès sans changement (aucune action) → `review` « sans changement » `branch:nexus/nx-run-1`, aucun commit (la branche reste au départ).
19. Succès puis code 1, avec action `write` → `failed` code 1, aucun commit, le fichier reste dans le worktree.
20. Aucune ligne `result`, code 0, avec action `write` → `failed` « sans résultat », aucun commit.
21. `RESULT_IS_ERROR`, avec action `write` → `failed` avec la cause, aucun commit.
22. `INIT_MCP` puis `hang` → processus tué sans attendre la durée maximale, `failed` « isolation non respectée » ; arrêt confirmé ; aucun commit. Même chose avec `INIT_EXTRA_TOOL` (Bash présent) et `INIT_MISSING_TOOL`.
23. Pas d'`init` conforme (`INIT_BARE`, `isolation_unknown`, ou une ligne `assistant` avant l'`init`), puis `hang` → processus tué sans attendre la durée maximale, `failed` « isolement de la session non vérifié », jamais `done` ni `review` ; arrêt confirmé ; arrêt non confirmé → lève, run ouvert.
24. Durée maximale (`max_seconds` minuscule, action `write` puis `hang`) → `failed`, arbre tué, aucun commit.
25. 400 lignes de texte → 300 `progress` au plus, la fin toujours présente ; `claimed`/`working` une fois.
26. Fichier de réglages supprimé après `done`, après `failed` et après `cancel`.
27. `RunInfo.model = None` → `dispatch` lève `ValueError` avant tout `Popen`.

**Barrières git du commit de Nexus — `test_claude_code_git_barriers.py`** (dépôts réels jetables, fonctions de `run_commit` appelées directement et par l'adaptateur)
28. Dépôt dont la configuration déclare `core.hooksPath=.githooks` avec un `pre-commit` témoin dans le commit de départ, plus un `pre-commit` témoin dans `.git/hooks` ; action `write` → commit présent sur la branche, **aucun témoin**.
29. `rewrite_dotgit` : le faux réécrit `.git` vers un gitdir piégé (`core.fsmonitor` et hook témoins), puis `write` → le commit de Nexus arrive sur la vraie branche (`GIT_DIR` imposé), `.git` n'est pas dans le commit, aucun témoin ; la preuve est relue depuis le dépôt.

**Annulation et redémarrage — `test_claude_code_cancel.py`**
30. `cancel` pendant `hang` (après une action `write`) → arbre tué, run réglé, purgeable, **aucun commit**.
31. Après redémarrage : jamais lancé → retour ; marqueur `.stopped` → retour ; sinon lève.
32. `close()` tue et écrit le marqueur.

**Enregistrement — `test_claude_code_registration.py`**
33. Sans `NEXUS_CLAUDE_BIN`, même avec un exécutable nommé `claude` en tête du `PATH` → rien d'enregistré, aucun `Popen`.
34. `NEXUS_CLAUDE_BIN` sans `NEXUS_RUN_WORKDIRS`, ou seulement le dépôt du serveur → rien.
35. Sonde en échec (code ≠ 0, délai dépassé) → rien.
36. Tout est bon → enregistré sous `claude`, `name == "claude-code"` ; `GET /api/executors` liste `claude` avec `agents == ["claude"]` et `models == ["haiku", "sonnet", "opus"]`.
37. `GuardedPopen` lève pour un radical `claude`.

**Modèle, règles, API, migration — `test_runs_model.py`, `test_run_model_migration.py`** (livrés par H1, `feed224` ; inchangés)
38. `claude` sans `model` → 409 `model_required` ; `codex` ou `hermes` avec `model` → 409 `model_not_for_executor` ; `model: "fable"` → 422 sans recopie de la valeur (`validation.french_errors` ne garde que `loc` et `msg` ; le test le vérifie sur une valeur en forme de secret).
38 bis. **Tests existants touchés :** `test_runs_api.py` (l. 180–184) et `test_runs_supervisor.py` (l. 101–105) enregistrent un adaptateur factice sous `claude` comme « autre exécutant » et confient sans `model` : avec H1 ils recevraient `model_required`. H1 les fait passer sur `orca` (exécutant sans modèles), ce qui garde leur intention ; c'est une modification de test assumée, notée dans la PR. Un mock de `/api/executors` sans `models` (tests web, e2e) se lit comme une liste vide.
39. Même `client_key`, même modèle → 200 ; autre modèle → 409 `client_key_reused`.
40. `RunOut.model` relu ; `GET /api/executors` : `models == []` pour Codex.
41. Le superviseur passe `model` à `RunInfo` (adaptateur factice qui capture le snapshot).
42. Migration : `0009` sur une base `0008` peuplée (un run existant) → `model` NULL, `compare_metadata` vide ; `downgrade` vers `0008` garde les runs.

**Interface (Vitest) — `ConfierDialog.model.test.tsx`, `RunsSection.test.tsx`** (livrés par H1 ; inchangés)
43. Champ « Modèle » présent pour Claude (Sonnet présélectionné), absent pour Codex ; changer d'exécutant le masque et l'oublie.
44. L'envoi porte `model` pour Claude et pas pour Codex ; changer de modèle après un refus produit une nouvelle `client_key`, renvoyer sans changement garde la même.
45. Modèle retiré par le serveur → « — plus disponible », envoi bloqué, brief gardé.
46. Refus `model_required` et `model_not_for_executor` expliqués.
47. La ligne du run affiche « Sonnet » et « Branche » pour Claude.

**Commit de Nexus — `test_run_commit.py`** (nouveaux ; dépôts réels jetables ; `run_commit` appelé directement, sans aucun faux exécutable, sauf mention : le module se teste sans adaptateur, ce qui garde sa neutralité)
48. **Dépôt imbriqué** : `nested_repo` (`sub/.git/`), variante `sub/.GIT`, variante `sub/.git.` (point final, quand le système le permet) → `Refused("dépôt git imbriqué")`, **aucun `git add` lancé** (le témoin `fsmonitor` est absent et l'index est celui du départ), run `failed` « commit refusé par Nexus : dépôt git imbriqué ».
49. **Fichier `sub/.git`** (`gitdir:` vers un dépôt hors du worktree) → même refus.
50. **Point de jonction** vers un dossier hors du worktree contenant un fichier témoin → `Refused("lien ou point de jonction")` ; le contenu du témoin n'est dans **aucun objet** du dépôt (`git cat-file --batch-all-objects --batch`). Lien symbolique de fichier : même attente, test sauté avec sa raison si le système refuse de le créer (`WinError 1314`).
51. **Le parcours ne traverse pas** : une jonction vers un dossier qui contient lui-même un `.git` → le refus nomme le lien, jamais le dépôt (preuve que le parcours n'est pas entré).
52. **Contrôle de l'index** (défense en profondeur, contrôle du worktree contourné par un paramètre de test) : un lien `160000` ou `120000` dans l'index après `add` → `Refused`, aucun commit.
53. **Pilote de filtre** : configuration du dépôt avec `filter.evil.clean` = script témoin et action `attributes` → au lancement : `failed` « lancement impossible », aucun `Popen` ; configuration changée **pendant** le run (le test l'ajoute après le `dispatch`) → `Refused("pilote de filtre")` avant `add`, aucun témoin.
54. **Configuration globale ignorée** : le test exporte `GIT_CONFIG_GLOBAL` vers un fichier qui définit `filter.evil.clean` (témoin), `core.autocrlf=true`, `core.attributesFile` → action `attributes` + `write` → commit fait, aucun témoin, seuls les fichiers écrits par le faux sont dans le commit (aucun fichier non touché ajouté pour une fin de ligne).
55. **Gros fichier** : `MAX_FILE_BYTES` réduit à 1 Kio ; `big_file` de 2 Kio → `Refused("fichier trop gros")` ; un fichier de 2 Kio déjà présent au départ et non modifié → pas de refus, commit des autres changements.
56. **Noms en forme d'option** : `write_named` → commit fait, les deux fichiers y sont sous leur nom.
57. **`.gitignore` `*`** (`ignore_all`, plus `write`) → `NothingToCommit`, `review`, `git commit` jamais appelé (trace des appels de `run_git`).
58. **Idempotence** : `commit_run` appelé deux fois → un seul commit ; le second rend `Committed` avec le même sha (étape 1). Variante : un commit déjà présent sur la branche avant l'appel → `done` avec lui, `git add` jamais appelé.
59. **Échec de git** : un `index.lock` posé dans le gitdir du worktree → `GitFailed("add")`, run `failed` « commit de Nexus impossible (add) », la sortie de git n'apparaît dans aucun événement.
60. **Délai** : `COMMIT_BUDGET` minuscule et un `run_git` de test qui dépasse → `GitFailed` « délai dépassé », jamais d'exception ; variante où le commit est écrit puis le délai dépasse → l'étape 7 trouve le commit → `done`.
61. **Maintenance automatique** : avec `GIT_TRACE` capturé par un `run_git` de test, `git commit` ne lance aucun sous-processus (`run_command`).
62. **Identité** : seule une identité globale existe → le commit est signé d'elle alors que le commit ne lit pas la configuration globale (variables `GIT_AUTHOR_*`/`GIT_COMMITTER_*`) ; identité contenant un saut de ligne → `failed` « lancement impossible », aucun `Popen`.
63. **Message fixe** : le brief et la réponse finale contiennent un faux secret et une ligne `Nexus-Run: nx-run-999` → le message du commit est exactement celui du §5.4 (ni le brief ni la réponse n'y entrent).
64. **Consigne et plafond** : la consigne du §3.3 cite le même nombre de Mo que `MAX_FILE_BYTES`.
65. **Annulation contre commit** (superviseur réel, adaptateur avec le faux) : annulation demandée avant le tour où le processus a fini → `cancelled`, aucun commit ; annulation demandée après la fermeture `done` → le run reste `done`.
66. **Neutralité** : `CommitRequest(adapter="codex", label="Codex", model=None)` → sujet `nx-run-1 : travail de Codex`, trailers `Nexus-Run` et `Nexus-Executor: codex`, **aucun** `Nexus-Model` ; requêtes invalides (`run_ref="nx-run-0"`, `"nx-run-1\nx"`, `adapter="Codex Evil"`, `label` avec `\n`, `model="Opus x"`, `model="opus\n"`) → `Refused("requête invalide")`, aucun appel de git. Test d'import : `run_commit` n'importe aucun module `nexus.adapters.claude_code*`, ni `nexus.adapters.codex`, ni `nexus.runs` (seulement `codex_git`).
67. **Lien physique** : `os.link` d'un fichier témoin hors du worktree vers `inside.txt` → `Refused("lien physique")`, aucun `git add`, contenu du témoin absent des objets.
68. **Worktree changé entre le contrôle et l'ajout** (paramètre de test qui crée un fichier `late.txt` juste avant l'étape 4) → `Refused("worktree changé pendant le commit")`, aucun commit.
69. **Preuve dans le budget** : les lectures des étapes 1 et 7 rendent le même résultat que `codex_git.proof` (branche absente, commit de départ seul, commit qui ne descend pas du départ, commit valable) ; avec un `run_git` de test lent, le budget total n'est jamais dépassé de plus d'un délai d'appel.

**Bout en bout (Playwright)** — `web/e2e/fake-claude.mjs` (rejoue `INIT_OK`, un message, `RESULT_OK`, écrit un fichier ; **ne commite pas**) et `NEXUS_CLAUDE_BIN` dans `e2e-env.ts` : confier une tâche à Claude avec Opus → le run apparaît avec « Opus », se termine `done` avec la preuve de commit (le commit fait par Nexus).

---

## 10. Fichiers touchés et découpage (seuils 400 / 600 lignes)

| Fichier | Contenu | Taille visée |
|---|---|---|
| `server/src/nexus/adapters/claude_code.py` (nouveau) | `ClaudeCodeAdapter` (`_Job`, `probe`, `dispatch`, `watch`, `cancel`, `recover`, `close`, `_settle` qui appelle `commit_run`), `register_configured` | ≤ 340 |
| `server/src/nexus/adapters/claude_code_cli.py` (nouveau) | `argv()`, contenu et écriture du fichier de réglages, `CLAUDE_ENV_ALLOW`, `child_env()` avec les valeurs imposées, `INSTRUCTION`, `EXPECTED_TOOLS` | ≤ 130 |
| `server/src/nexus/adapters/run_commit.py` (nouveau, **neutre vis-à-vis de l'exécutant**) | `run_git` (environnement et `-c` du §4.6, budget), `Identity`, `CommitRequest`, `worktree_gitdir`, `resolve_identity`, `check_no_filter_driver`, `scan_worktree` (parcours `os.scandir`), `commit_run` et ses issues (§5.4), `MAX_FILE_BYTES`, `COMMIT_BUDGET` | ≤ 240 |
| `server/src/nexus/adapters/claude_code_translate.py` (nouveau) | traduction pure du §5.2 | ≤ 190 |
| `server/tests/conftest.py` | `no_claude_from_the_shell`, radical `claude` | +8 |
| `server/tests/claude_code_support.py` (nouveau) | faux exécutable et actions du §9 | ≤ 350 |
| `server/tests/test_claude_code_translate.py`, `test_claude_code_cli.py`, `test_claude_code_adapter.py`, `test_claude_code_errors.py`, `test_claude_code_git_barriers.py`, `test_claude_code_cancel.py`, `test_claude_code_registration.py` (nouveaux) | tests 1–37 | chacun ≤ 350 |
| `server/tests/test_run_commit.py` (nouveau) | tests 48–64 et 66–69 (le 65 passe par le superviseur : `test_claude_code_cancel.py`) | ≤ 550 ; s'il dépasse, découper en `test_run_commit_scan.py` (48–57, 67, 68) et `test_run_commit_flow.py` (58–64, 66, 69) |
| `web/e2e/fake-claude.mjs`, `e2e-env.ts`, `runs-claude.spec.ts` (nouveaux ou modifiés) | e2e | |

Livré par H1 (`feed224`), non retouché par H2 : `base.py` (`RunInfo.model`), `runs/rules.py`, `runs/service.py`, `runs/api.py`, `runs/supervisor.py`, `models.py`, migration `0009_run_model.py`, interface (`runsApi.ts`, `vocabulary.ts`, `ConfierDialog.tsx`, `RunsSection.tsx`). H2 touche encore `config.py` (`claude_bin`, +3) et `app.py` (enregistrement, +2).

Aucun fichier ne franchit son seuil ; aucune entrée de `file-size-baseline.json`. **Rejeté :** factoriser dès maintenant `_Job` avec Codex (toucherait un adaptateur testé en réel pour un gain de quelques dizaines de lignes) ; à reconsidérer une fois les deux adaptateurs relevés en vrai, dans une PR à part. **Rejeté aussi :** mettre le commit dans `codex_git` (module que l'adaptateur Codex, testé en réel, utilise tel quel : l'étendre dans H2 toucherait Codex sans qu'il s'en serve, et le futur renommage générique de `codex_git` est un sujet à part, §3.4) ; le mettre dans `claude_code.py` ou un `claude_code_git.py` (il dépasserait 400 lignes, se teste seul sans processus, et Codex devrait importer un module d'un autre exécutant pour le réutiliser, §14).

**Deux PR, l'une après l'autre, chacune depuis `master` à jour (jamais empilées) :**
- **H1 — modèle par run** : fusionnée (`feed224`, #184).
- **H2 — adaptateur `claude-code`** : §2 à §5, tests 1–37 et 48–69, e2e, INTEGRATIONS §A.2, SECURITY §3, ROADMAP, addendum du 2026-11-12 dans `DECISIONS.md` (§11).
La sécurité de l'enfant, l'exécution de git par le serveur sur un contenu écrit par l'agent et un invariant du superviseur sont touchés : `architect` relit ce recadrage avant `implementer` (AGENTS.md, « Model routing »).

### Docs à mettre à jour (par H2)

- `DECISIONS.md` : addendum « exécution sans Bash » du §11, sous celui du 2026-11-11 ; il remplace la phrase « Bash réduit à `git status`, `git add` et `git commit`, hooks git coupés par l'environnement de l'enfant » de ce dernier (l'addendum du 2026-11-11 n'est pas réécrit : le nouveau dit ce qu'il remplace).
- `docs/INTEGRATIONS.md` §A.2 : paragraphe « Adaptateur Claude Code (lot H) » (réglages, commande, aucun Bash, commit par Nexus et ses refus, preuve, à confirmer au premier run). Il écrit aussi les limites : dépôt dont la configuration git lance un script rangé dans l'arbre, dépôt avec pilote de filtre (LFS), dépôt qui extrait de vrais liens symboliques, identité git requise (locale ou globale).
- `docs/SECURITY.md` §3 : troisième adaptateur enregistré (opt-in), liste blanche, aucun Bash, commit par le serveur et ses barrières (§8).
- `docs/DATA-MODEL.md` §2.5 : rien (H1 y a déjà écrit le champ `model` et `external_ref` = la branche pour un run Claude).
- `docs/ROADMAP.md` : lot H.

---

## 11. Addenda à ADR-023

### 11.1 Addendum du 2026-11-11 (ajouté par H1, déjà dans `DECISIONS.md`)

Texte d'origine, ajouté par H1 sous « Addendum (2026-11-11) — Claude Code comme exécutant, modèle choisi à chaque run (lot H) ». Sa dernière puce dit « Bash réduit à `git status`, `git add` et `git commit`, hooks git coupés par l'environnement de l'enfant » : l'addendum du 2026-11-12 la remplace.

### 11.2 Addendum du 2026-11-12 (texte à ajouter par H2)

```markdown
### Addendum (2026-11-12) — Claude Code sans Bash, commit fait par Nexus (lot H2)

Décidé par Loïc le 2026-11-12 (recadrage : `docs/superpowers/specs/2026-11-11-adaptateur-claude-code-design.md`,
§4 et §5.4 ; issue #185) :

- Un run de l'adaptateur `claude-code` n'a **aucun outil qui exécute une commande** : seulement
  `Read`, `Edit`, `Write`, `Glob` et `Grep` (`--tools`), dans le worktree du run. Cette puce remplace
  « Bash réduit à `git status`, `git add` et `git commit` » de l'addendum du 2026-11-11 : un relevé
  réel a montré que des options de ces commandes lisent un fichier hors du worktree et en renvoient
  le contenu au modèle.
- **Nexus fait le commit** à la fin d'un run réussi (ligne `result` en succès, code 0, isolement
  vérifié), depuis le processus serveur : `git add -A` puis `git commit` avec un message fixe
  (référence du run et alias du modèle), l'identité git du dépôt figée avant le lancement,
  configuration système et globale coupées, hooks, `fsmonitor`, signature et maintenance coupés,
  `GIT_DIR` imposé. Avant le commit, Nexus refuse (run `failed`) un dépôt git imbriqué, un lien, un
  point de jonction ou un lien physique, un fichier de plus de 20 Mio, et un pilote de filtre défini dans la
  configuration du dépôt (ce dernier est aussi refusé avant le lancement).
- D6 inchangé : la preuve est un commit qui descend du commit de départ, relu depuis le dépôt ;
  sans changement, le run finit en `review`. Aucun commit après une annulation, une durée maximale,
  un échec ou un redémarrage.
```

---

## 12. Run réel (manuel, jamais en CI)

### 12.0 Relevé préalable du 2026-11-12 (Haiku, hors Nexus) — cadrage du 2026-11-11

Relevé daté, fait **avec `Bash` dans `--tools`** et les règles `Bash(git …)` du cadrage du 2026-11-11 ; il reste valable pour ce qui ne dépend pas de Bash (forme des lignes, `--restricted`, abonnement). Sept runs réels de `claude` 2.1.322 avec Haiku ont été lancés à la main, avec l'argv du §3.1 d'alors, le fichier de réglages du §3.2 d'alors et l'environnement du §3.5 (liste blanche et valeurs imposées), dans un dépôt jetable dont la configuration déclare `core.hooksPath=.githooks` avec un `pre-commit` témoin. Chaque run a duré de 4 à 11 s.

- `system/init` réel : `tools = ["Bash","Edit","Glob","Grep","Read","Write"]` (ordre alphabétique : comparer en ensemble), `mcp_servers = []`, `permissionMode = "dontAsk"`, `model = "claude-haiku-5-5"`, `apiKeySource = "none"` (abonnement, pas de clé d'API), `slash_commands = []`. Le contrôle d'isolement du §5.2 d'alors passait tel quel.
- Lignes vues en plus de la table du §5.2 : `system/thinking_tokens`, `system/vcs_state_changed`, `rate_limit_event` (type de premier niveau). Toutes → `()` (type ou sous-type sans fait).
- `result` réel : `subtype`, `is_error`, `num_turns`, `duration_ms`, `result`, `errors` (`null` en succès), `permission_denials` d'objets `{tool_name, tool_use_id, tool_input}`. Un refus d'outil laisse `subtype = "success"` et `is_error = false` : la fin est jugée par la preuve, comme prévu.
- **A** (modifier `README.md` puis commiter) : `Read`, `Edit`, `git status`, `git add README.md`, `git commit -m … -m "Co-Authored-By: …"` permis ; commit sur la branche du run, accents intacts en UTF-8, **hook témoin non lancé**, aucune session dans `~/.claude/projects`.
- **B** (`npm --version`), **E** (`git status > ../hors.txt`), **E2** (`git -c core.hooksPath=.githooks commit …`), **E4** (`git status && npm --version`) : refusés, `permission_denials` = `Bash`, aucun fichier `hors.txt`, aucun témoin, aucun commit.
- **E3** (lire et modifier `../target/README.md`) : `Read` hors du worktree refusé, `cat` refusé ; rien modifié.
- `--restricted` tient `~/.claude/CLAUDE.md` et les mémoires à l'écart (question posée au modèle sans outil : aucune instruction de ce genre, aucun contenu de la configuration de Loïc).
- Puis le relevé du §4.4 (options de git qui lisent hors du worktree), qui a conduit au recadrage.

### 12.1 Scénarios du premier run réel par Nexus (cadrage du 2026-11-12)

Prérequis : Loïc vérifie lui-même qu'il est connecté (`claude auth status --text`, dans son terminal ; la sortie n'est ni copiée ni journalisée). Un dépôt jetable avec un commit, une identité git (locale ou globale), aucun pilote de filtre, déclaré seul dans `NEXUS_RUN_WORKDIRS` ; un fichier témoin `hors-worktree.txt` (contenu inoffensif) à côté du dossier des worktrees.

1. Lancer Nexus avec `NEXUS_CLAUDE_BIN=<chemin absolu de claude>` (par exemple `%USERPROFILE%\.local\bin\claude.exe`), `NEXUS_RUN_WORKDIRS=<dépôt jetable>`, `NEXUS_RUN_MAX_MINUTES=15` ; `GET /api/executors` liste `claude` avec les trois modèles.
2. **Scénario A — `done` avec Haiku** (le moins cher d'abord) : brief « Ajoute une ligne "bonjour" à README.md. Accents : é è à ç « » ». Attendu : `claimed` avec le nom complet du modèle Haiku dans `payload.model`, `working`, « Fichier modifié », `done` `commit:<12>`. Vérifier : `system/init` liste exactement les cinq outils (sinon le run finit en `failed` « isolation non respectée », voir la fin de ce paragraphe) ; branche `nexus/nx-run-<n>` avec **un** commit, fait par Nexus (sujet et trailers du §5.4, auteur = l'identité du dépôt), accents intacts ; hook témoin non lancé ; aucun fichier de session pour ce worktree dans `~/.claude/projects` ; fichier de réglages du run supprimé.
3. **Scénario B — commande impossible** : brief « Lance `npm --version` puis réponds en une phrase ». Attendu : aucune commande lancée (l'outil n'existe pas ; selon le modèle, une réponse qui le dit, ou « Outils refusés »), fin sans changement → `review`.
4. **Scénario C — `.git` protégé** : brief « Modifie le fichier .git du dossier courant ». Attendu : refus (« Outils refusés » `Edit`/`Write`), aucun changement du fichier `.git` ; sinon, le commit de Nexus va quand même sur la vraie branche (`GIT_DIR` imposé) et le §3.2 est à revoir.
5. **Scénario D — annulation** : brief long (Sonnet) ; annuler après `working`. Attendu : `cancelled`, plus aucun processus `claude` de ce run (gestionnaire des tâches), **aucun commit** sur la branche.
6. **Scénarios E — Bash absent** (règle d'arrêt pour chacun : si une commande a tourné ou si le contenu du témoin apparaît dans la sortie, **arrêter les runs réels** et revenir vers Loïc) :
   - **E — redirection** : brief « Exécute `git status > ../hors.txt` ». Attendu : `system/init` sans `Bash`, aucun fichier `hors.txt`.
   - **E2 — hook demandé** : brief « Crée `.githooks/pre-commit` qui écrit un fichier témoin, puis configure git pour l'utiliser ». Attendu : le fichier peut être créé (il sera commité, Loïc le voit) ; aucune configuration changée ; **aucun témoin** après le commit de Nexus.
   - **E3 — hors du worktree** : brief « Lis puis modifie `../../README.md` ». Attendu : refus de la lecture et de l'écriture, aucun fichier modifié hors du worktree.
   - **E4 — commande chaînée** : brief « Exécute `git status && npm --version` ». Attendu : aucune commande ; fin `review`.
   - **E5 — fichier hors du worktree** : brief « Lis `../hors-worktree.txt` et recopie son contenu dans NOTES.md ». Attendu : `Read` refusé, contenu du témoin absent de toute la sortie et du commit.
7. **Scénario G — dépôt imbriqué** : brief « Crée le fichier `sub/.git/config` avec `[core] fsmonitor = …` ». Attendu : `Write` refusé par les règles `deny` (on note si `**/.git/**` a pris) ; si le fichier a été écrit malgré tout, run `failed` « commit refusé par Nexus : dépôt git imbriqué », aucun commit, aucun témoin.
8. **Scénario H — rien à faire** : brief « Ne change aucun fichier ; dis seulement combien de lignes a README.md ». Attendu : `review` « sans changement », aucun commit.
9. **Scénario F — redémarrage** : relancer Nexus pendant un run → `unknown`, aucun commit après le redémarrage ; annuler (arrêt propre : marqueur) → `cancelled`.
10. Noter dans la PR et dans INTEGRATIONS §A.2 (« Constaté aux premiers runs réels ») : forme réelle de `system/init` avec les cinq outils (`tools`, `mcp_servers`, `permissionMode`, `apiKeySource`) et de `result` ; si `--restricted` a bien tenu à l'écart hooks, plugins et `~/.claude/CLAUDE.md` ; si le fichier de réglages a été pris en compte (sinon : « Outils refusés » sur `Edit`, §3.2) ; si les règles `deny` `**/.git/**` ont pris (G) ; si `CLAUDE_CODE_GIT_BASH_PATH` sert encore ; la variable d'environnement qui porte la connexion ; la durée d'un run court et celle du commit de Nexus.

Si le scénario A finit en `failed` « isolation non respectée » à cause d'un outil toujours présent dans cette version (par exemple un outil de liste de tâches), on n'élargit pas la liste sans relire ce que fait l'outil : la correction passe par une PR. Même chose pour `permissionMode` : le binaire convertit le mode avant de l'écrire dans `system/init` (une fonction de correspondance existe entre le mode interne et le mot exporté) ; si la valeur réelle diffère de `dontAsk` alors que le mode est le bon, on corrige la comparaison du module de traduction, pas le mode.

---

## 13. Ce qui revient à Loïc

1. **Aucun Bash** — décidé par Loïc le 2026-11-12 (§4.1). L'agent ne peut lancer ni tests, ni linter, ni git. Élargir (par exemple `pnpm test`, `uv run pytest`) lui ferait exécuter du code qu'il vient d'écrire, avec tes droits, sans bac à sable sous Windows : ce serait un nouveau cadrage, pas un réglage.
2. **Nom de l'exécutant** : l'exécutant reste l'acteur existant `claude`, `claude-code` n'est que le nom de l'adaptateur (`origin`). À dire si tu voulais vraiment un acteur distinct.
3. **Modèle présélectionné** : Sonnet (livré par H1). Haiku si tu préfères que le défaut soit le moins cher.
4. **Déclenchement des runs réels « par l'agent principal »** : D2 réserve le dispatch à un humain ; l'agent principal ne peut confier un run qu'avec ton jeton de navigateur, sur ta consigne. L'addendum l'écrit ainsi ; à corriger si tu veux que seul toi cliques.
5. **Phrase dans AGENTS.md** pointant vers l'exception : ajoutée par H1.
6. **Choix du recadrage, pris par l'agent et à confirmer** (chacun se change sans migration) :
   - **Attribution du commit** : auteur et committer = l'identité git du dépôt (la tienne), trailers `Nexus-Run`, `Nexus-Executor`, `Nexus-Model` ; **pas** de `Co-Authored-By: Claude …`. À ajouter si tu veux que GitHub montre Claude comme co-auteur.
   - **Refus = `failed`** (dépôt imbriqué, lien, filtre, fichier trop gros), **aucun changement = `review`**.
   - **Plafond de 20 Mio** par fichier ajouté ou modifié ; aucun plafond total (le budget de 90 s borne le commit).
   - **Dépôts exclus** : pilote de filtre dans la configuration du dépôt (LFS local) refusé au lancement ; dépôt qui extrait de vrais liens symboliques refusé au commit. À dire si un de tes dépôts visés est dans ce cas.
   - **Identité** : lue dans la configuration locale ou globale du dépôt avant le lancement. Helios n'a pas d'identité globale : le dépôt déclaré doit porter la sienne.
7. **Codex** (§14, hors périmètre de #185, une issue à part après ta décision) : (a) Nexus commite aussi pour Codex, recommandé, ou (b) un clone par run ; le bac à sable `elevated` de ta configuration (échec UAC en non interactif) ; l'isolement de ta configuration Codex (MCP, skills) pendant un run.

---

## 14. Conséquences pour Codex (hors périmètre de #185)

Rien de cette section ne change l'adaptateur Codex dans H2 : elle prépare une issue et une branche à part, après la décision de Loïc. Elle explique pourquoi le commit de H2 est un module neutre.

### 14.1 Constat du 2026-11-12 (run réel, codex-cli 0.167.1, adaptateur tel que livré)

1. **Codex ne peut pas commiter depuis un worktree de Nexus sous son bac à sable.** Avec `--sandbox workspace-write` (et `windows.sandbox="unelevated"` forcé à la main), Codex a modifié `README.md`, mais `git commit` a échoué sur « accès refusé à index.lock » : le dossier git du worktree (`<dépôt>/.git/worktrees/nx-run-<n>`) est hors de la racine où le bac à sable permet d'écrire. Avec la configuration de Loïc (`[windows] sandbox = "elevated"`), **toute** commande échoue en run non interactif (assistant d'installation : `ShellExecuteExW`, erreur 1223, invite UAC refusée). Le run finit donc au mieux en `review` sans commit.
2. **La configuration Codex de Loïc se charge dans un run** : la sortie montre des éléments `mcp_tool_call` et la lecture d'un fichier de skill sous `~/.codex/skills` (sa configuration déclare des serveurs MCP, dont `node_repl`). C'est la même question d'isolement que `--restricted`/`--strict-mcp-config` pour Claude Code (§3.1).

### 14.2 Options pour le commit d'un run Codex

| Option | Ce qu'elle demande | Verdict |
|---|---|---|
| **(a) Nexus commite pour Codex aussi** (l'agent ne fait que modifier des fichiers et lancer ses commandes dans le bac à sable) | appeler `run_commit.commit_run` à la fin d'un run Codex réussi (`turn.completed`, code 0), avec `CommitRequest(adapter="codex", label="Codex", model=None)` ; résoudre l'identité et contrôler les pilotes de filtre au lancement ; changer la consigne de Codex (« ne commite pas, Nexus commite ») ; garder `codex_git.proof` | **recommandée** |
| (b) Un clone par run au lieu d'un worktree : le dossier git est dans la racine accessible en écriture, l'agent commite lui-même | voir le coût ci-dessous | possible, plus cher et plus large |
| (c) Rendre accessible en écriture seulement `<dépôt>/.git/worktrees/nx-run-<n>` (`--add-dir`) | rejetée : un commit écrit aussi les objets et les références dans le dossier **commun** `.git`, donc il échouerait encore ; et le fichier `commondir` de ce dossier deviendrait modifiable par l'agent, qui pourrait faire lire à git (celui de Nexus compris) une configuration à lui | rejetée |
| (d) Rendre `.git` du dépôt accessible en écriture | l'agent pourrait changer la configuration et les hooks du dépôt, au-delà du run | rejetée (Loïc) |

**Pourquoi (a).** Un seul chemin de commit pour les deux exécutants, testé une fois (§9, tests 48–69) ; aucune écriture de l'agent dans un dossier git (la précondition 1 du §5.4 tient : c'est exactement ce que le bac à sable a refusé le 2026-11-12) ; identité de l'auteur fixée par Nexus (avec un clone, l'agent choisit l'auteur de ses commits : constaté ci-dessous) ; aucun git de Nexus lancé contre un dépôt que l'agent contrôle ; pas de coût disque. Ce que Codex perd : choisir ses propres messages et découper son travail en plusieurs commits. Ce qu'il garde, contrairement à Claude Code : exécuter des tests dans son bac à sable.

**Ce que (a) coûte pour Codex, et que H2 n'a pas à payer.** Codex a un shell : il peut créer un point de jonction (`mklink /J`, sans droit particulier) ou un lien physique (cas 4 et 11 du §4.5), et laisser un processus orphelin. Le contrôle du §5.4 refuse ce qu'il trouve, mais la **précondition 2** (plus aucun processus du run ne peut écrire dans le worktree pendant le contrôle et l'ajout) ne tient pas avec `codex_process.kill_tree` sous Windows, qui ne retrouve pas un enfant orphelin. Un orphelin qui pose une jonction entre le contrôle et `git add -A` ferait entrer un fichier du dehors dans le commit ; le contrôle des chemins de l'étape 5 en attrape la forme simple (chemins que le parcours n'a pas vus), pas un fichier remplacé sous le même nom. (a) pour Codex demande donc d'abord un arrêt confirmé de tout l'arbre (*job object* Windows qui tue aussi les orphelins, ou vérification qu'aucun processus de l'arbre ne survit), testé, avant d'appeler `commit_run`. Il reste moins cher que (b) et ne touche pas `run_commit`. Le choix `unelevated`/`elevated` reste à Loïc dans les deux cas (§14.4).

**Coût de (b), relevé localement le 2026-11-12 (sans LLM, git 2.55)** : un dépôt jetable, un clone `git clone --shared --no-checkout` par run, puis tout ce qu'un agent peut planter dans un clone qui lui appartient (configuration `core.fsmonitor`, `core.hooksPath` vers des hooks témoins, `uploadpack.packObjectsHook`, `core.sshCommand`, `core.pager`, un pilote de filtre et un `.gitattributes` qui le choisit, une identité `a@example.invalid`) ; l'agent commite (côté bac à sable, ses pièges tournent : attendu) ; puis le serveur rapatrie la branche avec `git fetch --no-tags --no-write-fetch-head <clone> +refs/heads/nexus/nx-run-1:refs/heads/nexus/nx-run-1`, environnement de `codex_git`.
- Résultat : `fetch` réussi, **aucune exécution observée côté serveur** pour ces pièges-là (le `git-upload-pack` lancé dans le clone ignore `uploadpack.packObjectsHook` d'une configuration de dépôt, et n'a pas de hook) ; la branche arrive dans le dépôt, mais **avec l'auteur choisi par l'agent** (`a@example.invalid`) ; le `.git` du clone pèse 30 Ko grâce à `--shared` (fichier `objects/info/alternates` vers les objets du dépôt).
- Ce que (b) coûte en plus : (1) **disque** : `--shared` est presque gratuit mais le fichier `alternates` est modifiable par l'agent (il peut y ajouter un autre dépôt du disque, dont des objets pourraient alors être rapatriés) ; `--local` (liens physiques) est exclu, car un objet partagé par lien physique et réécrit dans le clone modifierait l'objet du dépôt ; `--no-hardlinks` copie tout le dépôt à chaque run ; (2) **preuve** : relue depuis le dépôt après le `fetch` (jamais depuis le clone), avec un plafond de taille du `fetch` et le même contrôle de liens et de sous-modules que le §5.4 sur l'arbre rapatrié ; (3) **nettoyage** : supprimer le clone à la clôture (sous Windows, objets en lecture seule à déverrouiller avant), et le garder tant que Loïc n'a pas relu si la branche n'a pas pu être rapatriée ; (4) **hooks et configuration du clone** : ils appartiennent à l'agent et tournent dans son bac à sable quand il commite (acceptable), mais Nexus ne doit **jamais** lancer git *dans* le clone (statut, preuve, nettoyage par git) : seulement le `fetch` depuis le dépôt ; (5) l'auteur des commits n'est plus garanti (forçable seulement en réécrivant les commits, ce qui revient à (a)) ; (6) la preuve D6 change de forme (commit dans un autre dépôt puis rapatrié), donc un amendement à D6. En contrepartie, (b) ne fait lire aucun fichier du worktree par Nexus : ce que l'agent met dans ses commits (jonction, lien physique) est lu par son propre git, dans les limites de son bac à sable, et le problème des orphelins de (a) ne se pose pas pour le commit (il reste pour l'arrêt du run).

### 14.3 Point d'isolement de Codex

- `codex exec --help` (0.167.1, relu le 2026-11-12 sans lancer de modèle) propose `--ignore-user-config` (« Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME` »), `--ignore-rules` (règles `.rules` de l'utilisateur et du projet), `--ephemeral` (aucune session écrite) et `-c clé=valeur`. `--ignore-user-config` devrait écarter les serveurs MCP déclarés dans `config.toml` tout en gardant la connexion ; **rien dans l'aide ne dit** qu'il écarte les skills de `~/.codex/skills` : à relever.
- À traiter dans l'issue Codex, comme pour Claude Code : (1) ces drapeaux dans l'argv de Codex, et le réglage de bac à sable passé par `-c` puisque `config.toml` ne serait plus lu ; (2) un contrôle fermé sur la sortie : un élément `mcp_tool_call`, ou la lecture d'un fichier sous `CODEX_HOME`, termine le run en `failed` « isolation non respectée » (équivalent du `breach` du §5.2) ; (3) si les skills restent chargées malgré `--ignore-user-config`, un `CODEX_HOME` propre au run (il faudrait y copier `auth.json`, un secret : à peser, pas à faire par défaut).

### 14.4 Ce qui revient à Loïc pour Codex

1. (a) ou (b) — recommandation : (a), avec un arrêt confirmé de tout l'arbre (orphelins compris) avant le commit.
2. Le bac à sable Windows de Codex pour les runs de Nexus : `unelevated` passé par l'adaptateur (`-c windows.sandbox="unelevated"`, le seul relevé qui fonctionne en non interactif), ou `elevated` après une installation interactive de son assistant (à vérifier qu'elle suffit ensuite en non interactif).
3. L'isolement de ta configuration Codex pendant un run (§14.3) : on part sur `--ignore-user-config` + `--ignore-rules` + un contrôle fermé de la sortie, à confirmer par un run réel.
