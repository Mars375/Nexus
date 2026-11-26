# Codex : le git que `codex.exe` lance hors du bac à sable (§11, Q3) — addendum

**Date :** 2026-11-25
**Issue :** #186 (refs #183, Phase 2). Répond à §11, Q3 et à la condition d'arrêt de l'étape 0b (§10) de `2026-11-13-codex-commit-par-nexus-design.md` (§1.4, §2.4, §5.5).
**Statut :** proposition d'un subagent, retenue telle quelle (A et B, sans `GIT_DIR`) : choisie par l'agent sous la délégation totale de Loïc du 2026-11-25 (ADR-024 ; DECISIONS, addendum du 2026-11-25 à ADR-023).
**Entrées :** ADR-023 et ses addenda (2026-11-13, 2026-11-20, 2026-11-23), ADR-024, `codex.py`, `codex_cli.py`, `codex_git.py`, `codex_process.py`, `run_commit.py`, `server/tests/test_codex_*.py`, `codex_support.py`, `web/e2e/fake-codex.mjs`. `CONTEXT.md` est absent à la racine du dépôt : les décisions viennent de `DECISIONS.md`.
**Expériences :** `C:\Users\Orion\nexus-realrun-codex\q3\` (`exp2.sh` à `exp5.sh`, git 2.55.0.windows.3). Aucun modèle n'a été appelé, ni `codex exec`. `exp.sh` (premier essai) est nul : un chemin MSYS dans `commondir` faisait sortir chaque appel en 128.

---

## 0. En bref

1. **Constat (0b, run réel, codex-cli 0.167.1).** `codex.exe` lance lui-même quatre git dans le worktree, hors du bac à sable, en 0,15 s au début du tour : `rev-parse HEAD`, `remote -v`, `config --null --get core.fsmonitor` et `status --porcelain`. Il les lance avant toute commande de l'agent, et aucun à la fin du tour. Il leur passe lui-même `-c safe.bareRepository=explicit -c core.hooksPath=NUL -c core.fsmonitor=false`, sauf à `config`, qui ne prend que le premier.
2. **Menace réelle.** `git status` lance les pilotes de filtre `clean` et `process` que déclare la configuration qu'il lit. Il le fait **dès le début du tour, sans aucune action de l'agent**, quand un `.gitattributes` suivi nomme un pilote défini dans la configuration **système ou globale**, que le contrôle de lancement ne lit pas (exp4, 5 essais sur 5).
3. **Recommandation.** Elle tient en deux changements, sans `GIT_DIR` :
   - **A.** L'enfant reçoit `GIT_CONFIG_NOSYSTEM=1` et `GIT_CONFIG_GLOBAL=<os.devnull>`. Le git de Codex lit alors exactement ce que lit `check_no_filter_driver`.
   - **B.** Le lancement est refusé si `codex --version` n'est pas une version relevée (`codex-cli 0.167.1`). « Git seulement au début du tour » devient une précondition vérifiée, et chaque nouvelle version refait 0b.
4. **Runs A–H avant le correctif.** Ils peuvent continuer, sous les conditions du §8.

---

## 1. Ce que `git status --porcelain` exécute (relevés locaux)

Chaque appel reprend l'argv relevé de `codex.exe` et l'environnement actuel de l'enfant (`GIT_CONFIG_COUNT=2` : `core.hooksPath=NUL`, `core.fsmonitor=false`). Un fichier « sale » a la même taille et un `mtime` nouveau, ce qui oblige git à relire son contenu. Le témoin est un fichier qu'écrit la commande configurée.

| # | Situation | Exécuté hors bac à sable |
|---|---|---|
| exp2 E1 | `.git` du worktree réécrit vers un faux dossier git (filtre `clean`, `core.fsmonitor`, hook `post-index-change`, `diff.*.textconv`, `diff.external`, `core.pager`), fichier sale | **le filtre `clean`** ; ni `fsmonitor` ni hook (coupés) ; `status --porcelain` ne lance ni `textconv`, ni `diff.external`, ni pager |
| exp2 E1 | même faux dossier git, `rev-parse HEAD`, `remote -v`, `config --get core.fsmonitor` | rien |
| exp2 E1b | même chose, sans aucun `-c` ni `GIT_CONFIG_*` | `clean`, `fsmonitor` et le hook : les deux coupures servent |
| exp2 E2 | E1 avec `GIT_DIR`/`GIT_WORK_TREE` imposés vers le dossier git de Nexus | rien |
| exp2 E3 | pilote dans la configuration **commune** réelle, `.gitattributes` du worktree, `.git` honnête | **`clean`** |
| exp2 E3b | E3 avec `GIT_ATTR_SOURCE=<arbre vide>` | rien |
| exp3 R1 | E1 avec `GIT_ATTR_SOURCE=<arbre vide>`, plus un `info/attributes` dans le faux dossier commun | **`clean`** : contourné |
| exp2 E4 | sous-module (gitlink dans le commit de départ), `sm/.git` créé vers un faux dossier git | **`clean` du sous-module** |
| exp2 E4b | E4 avec `GIT_DIR` imposé | **`clean` du sous-module** : `GIT_DIR` ne protège pas les sous-modules |
| exp2 E4c | E4 avec `diff.ignoreSubmodules=all` | rien |
| exp2 E5 | `.git` déplacé, racine du worktree fabriquée en dépôt nu | refusé par `safe.bareRepository=explicit` (Codex le passe déjà) ; le git de l'agent, sans cette clé, prend la racine comme dépôt |
| **exp4** | **worktree neuf** créé comme Nexus le crée, **aucune action, aucun `touch`** ; `.gitattributes` suivi (`*.txt filter=probe`, `*.bin filter=lfs`), aucun pilote dans le dépôt ; `probe` défini dans le fichier `GIT_CONFIG_GLOBAL`, `lfs` dans la configuration système de Git for Windows | **`probe.clean` et `git-lfs filter-process`, 5 essais sur 5** (les entrées fraîches de l'index sont « racy » : git relit leur contenu) |
| **exp5** | exp4 avec `GIT_CONFIG_NOSYSTEM=1` et `GIT_CONFIG_GLOBAL=NUL` dans l'environnement | rien, 3 essais sur 3 ; aucun `child_start` dans la trace |

## 2. Ce qui est atteignable aujourd'hui

- **Au début du tour, sans l'agent : oui, par la configuration système ou globale.**
  - `check_no_filter_driver` lit la configuration du dépôt, avec `GIT_CONFIG_NOSYSTEM=1` et `GIT_CONFIG_GLOBAL=NUL`. Le git de `codex.exe` lit en plus les configurations système et globale de Loïc. L'écart vient de là.
  - Ce qu'il y a aujourd'hui (noms des clés seulement) : la configuration système définit `filter.lfs.*` (un binaire de confiance, mais lancé hors du bac à sable) ; la configuration globale ne contient que des clés `credential.*`.
  - Il suffit qu'un `.gitattributes` suivi dans l'historique nomme `lfs` (un dépôt LFS) ou un pilote global ajouté plus tard. Un commit fait par Nexus pour un agent, puis fusionné par Loïc, peut amener ce `.gitattributes`.
- **Après une action de l'agent (E1 `.git` réécrit, E4 sous-module) : non observé.** Cela suppose que `codex.exe` lance git après la première commande de l'agent. Le relevé 0b n'en montre aucun, mais il repose sur **un** run (brief H) et **une** version. Une version future qui relirait l'état git à la fin du tour, pour un diff ou un instantané, rouvrirait E1 et E4.
- **D'un run à l'autre.**
  - Si le bac à sable laissait écrire la configuration commune (Q1, scénario E), le run suivant lancerait le filtre au début du tour. Le contrôle de lancement attrape un pilote écrit dans la configuration du dépôt, mais pas un pilote écrit dans `modules/*/config`.
  - Un worktree neuf n'a pas de sous-module peuplé, donc pas de récursion au début du tour.
  - Le fichier `.git` est neuf à chaque run.
- **Course.** Les quatre appels finissent en 0,15 s, et la première commande de l'agent attend un aller-retour du modèle, soit plusieurs secondes. Rien ne garantit cet ordre dans le code de Codex, mais aucune course n'est atteignable en pratique. Même pendant une telle course, un `.gitattributes` écrit en cours de `status` ne pourrait nommer qu'un pilote déjà défini : le fichier `.git` est lu une fois, au départ.
- **La trace 0b ne montre pas le git de l'agent.** On ne peut rien en conclure : le brief H ne lui demande pas de lancer git.

## 3. Options évaluées

| Option | E1 (`.git` réécrit) | E3 (configuration commune) | E4 (sous-module) | exp4 (système/global au début du tour) | Coût pour l'agent |
|---|---|---|---|---|---|
| `GIT_DIR`+`GIT_WORK_TREE` imposés à l'enfant | fermé | ouvert (même configuration commune) | **ouvert** (E4b) | ouvert | casse son git dans tout autre dépôt (dépôts jetables des tests) ; l'en exclure par `-c shell_environment_policy.exclude=['GIT_DIR','GIT_WORK_TREE']` n'est **pas vérifié** |
| `GIT_ATTR_SOURCE=<arbre vide>` | **ouvert** (R1) | fermé | non testé | fermé pour les attributs du worktree | attributs ignorés (fins de ligne, LFS) ; casse les dépôts SHA-256 |
| `diff.ignoreSubmodules=all` | ouvert | ouvert | fermé | ouvert | ne voit plus les changements de ses sous-modules |
| `safe.bareRepository=explicit` | ouvert | ouvert | ouvert | ouvert | déjà passé par Codex (E5) |
| `GIT_CEILING_DIRECTORIES` | ouvert | ouvert | ouvert | ouvert | utile seulement si `.git` disparaît et qu'un dépôt parent existe (non testé) |
| **A** : `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=NUL` | ouvert | couvert par le contrôle de lancement | ouvert | **fermé** (exp5) | voir §4.1 |
| Contrôle de la configuration du dossier git du worktree avant le lancement | rien de neuf : Nexus vient de le créer | déjà fait sur le dépôt | — | ouvert (mauvaise portée) | aucun |
| **B** : s'en tenir au « début du tour seulement », vérifié par la version | non observé sur la version relevée | idem | idem | ouvert | aucun |

Aucune option d'environnement ne ferme toute la classe E1/E4 : seule la propriété « aucun git de `codex.exe` après la première commande de l'agent » la ferme. Le critère de choix est donc de **vérifier** cette propriété plutôt que de la supposer (B), et de fermer l'écart réellement atteignable aujourd'hui (A). `GIT_DIR` coûte cher à l'agent et laisse E4 ouvert : il reste un repli conçu d'avance (§4.3). Aucune option ne touche `run_commit`, qui construit son propre environnement (`FORCED_ENV`, `GIT_DIR` imposé).

## 4. Recommandation : changements exacts

### 4.1 A — portée de configuration du git de l'enfant (`codex_cli.child_env`)

- Les deux clés s'ajoutent à l'`update` existant : `"GIT_CONFIG_NOSYSTEM": "1"` et `"GIT_CONFIG_GLOBAL": os.devnull`. Le reste ne change pas (`GIT_CONFIG_COUNT=2`, `GIT_TERMINAL_PROMPT=0`, `GIT_*` hérités retirés).
- Le même dictionnaire sert au run et aux contrôles. Si les contrôles `mcp list` et `prompt-input` lancent git (non relevé), ils sont couverts de la même façon.
- **L'argv du run ne change pas.**
- Effet : le git de `codex.exe` lit la même portée que `check_no_filter_driver` et que le worktree créé par `codex_git.git` (déjà sans configuration système ni globale).
- **Coût pour le git de l'agent (sandboxé)** :
  - plus d'identité globale : un `git commit` dans un dépôt jetable sans `user.name` échoue (exp5 : « Author identity unknown ») ;
  - plus de `credential.helper`, ce qui est voulu : l'agent ne pousse pas ;
  - plus de `filter.lfs` ;
  - plus de `core.autocrlf=true` ni de `http.sslbackend` venus du système. HTTPS depuis git n'a pas été vérifié.
- **`run_commit` n'est pas touché** : il construit son propre environnement, qui a déjà les deux clés.

### 4.2 B — version relevée (`codex_cli.check_version`)

- **Constante :** `MEASURED_VERSIONS = frozenset({"codex-cli 0.167.1"})` dans `codex_cli.py`, avec en commentaire la date et la référence du relevé 0b.
- **Appel :** `_control([binary, "--version"], cwd, env, timeout)` :
  - `cwd` est `self.codex_home`, créé juste avant ; `env` est le dictionnaire du run ;
  - l'appel est contenu et borné à `CONTROL_TIMEOUT`, et sa sortie est lue en mémoire.
- **Acceptation :** la sortie est exactement `<version>\n` (relevé : `codex-cli 0.167.1` suivi de `\n`, sans `\r`) avec `<version>` dans la constante. Sont refusés, par `ValueError("contrôle d'isolement : version de Codex non relevée")` : une autre version, une ligne de plus, une espace, une sortie vide, un code non nul ou un délai dépassé.
- **Place dans `dispatch` :** après `check_locations(gitdir=None)` et `codex_home.mkdir`, **avant** `create_worktree`. Un refus ne laisse ni branche ni worktree. Si l'arrêt de l'appel n'est pas confirmé, `ControlNotStopped` remonte en « lancement impossible » ; il n'y a rien à garder.
- **`probe` ne change pas** : il ne sert qu'à l'enregistrement.
- **Règle :** monter Codex de version, c'est ajouter la nouvelle version à la constante **dans la PR qui joint un nouveau relevé 0b** (§6). Jamais sans ce relevé.

### 4.3 Repli, si un relevé montre du git de `codex.exe` après la première commande de l'agent

Les runs réels s'arrêtent. On ajoute alors, dans cet ordre de preuve :

1. `GIT_DIR` et `GIT_WORK_TREE` (le dossier git du worktree et le worktree) dans l'environnement de `codex.exe` ;
2. `-c shell_environment_policy.exclude=['GIT_DIR','GIT_WORK_TREE']`, des apostrophes et non des guillemets, à cause de `CMD_SPECIAL` ; un run réel doit prouver que les commandes de l'agent ne voient pas ces variables ;
3. `GIT_CONFIG_COUNT=3` avec `GIT_CONFIG_KEY_2=diff.ignoreSubmodules`, `GIT_CONFIG_VALUE_2=all` (git ne lit que les paires d'indice inférieur au compteur), ce qui ferme E4.

Rien de ce repli n'est à coder maintenant.

## 5. Tests à écrire d'abord (faux `codex`, jamais de modèle en CI)

**Dans `test_codex_cli.py` (240 lignes)**

1. Le test d'égalité de l'environnement (`test_the_child_environment_drops_every_secret…`) attend les deux clés en plus ; un `GIT_CONFIG_NOSYSTEM=0` ou un `GIT_CONFIG_GLOBAL` hérité est remplacé.
2. `check_version` :
   - accepte `codex-cli 0.167.1\n` ;
   - refuse `codex-cli 0.168.0\n`, `codex-cli 0.167.1\nx\n`, ` codex-cli 0.167.1\n`, une sortie vide, un code 1 et un délai (`version_hang`) ;
   - l'argv est exactement `[binary, "--version"]`.

**Dans `test_codex_isolation.py` (358 lignes)**

3. Une version refusée donne « lancement impossible », aucune branche `nexus/…`, aucun dossier de worktree, et aucun appel `mcp list` ni `exec` enregistré.
4. L'appel de version reçoit **le même** environnement que les contrôles et le run (extension du test `test_the_controls_and_the_run_get_the_very_same_environment`).
5. Ordre des appels enregistrés : `version`, `mcp`, `prompt`, `exec`.

**Le faux exécutable `codex_support.py`**

- Aujourd'hui, il répond `codex-cli 0.0.0-fake` **avant** `record()`.
- Désormais, `--version` passe par `control("version", "codex-cli 0.167.1\n")`, qu'on peut changer par le scénario.
- Les tests qui comptent les appels (le `probe` appelle aussi `--version`) sont à revoir.

**Le faux exécutable de l'e2e `web/e2e/fake-codex.mjs`**

- Il imprime `codex-cli 0.167.1`.
- Un test pytest lit ce fichier et y vérifie chaque version de `MEASURED_VERSIONS`, pour qu'une montée de version ne casse pas l'e2e en silence.

**Test de bout en bout du point A (Windows et POSIX, avec un vrai git, sans Codex)**

- Il reprend exp4 en pytest : dépôt avec un `.gitattributes` suivi `*.txt filter=probe`, worktree créé par `codex_git.create_worktree`.
- Le pilote est défini dans le `.gitconfig` d'un dossier personnel temporaire, pas dans `GIT_CONFIG_GLOBAL` : `child_env` retire tout `GIT_*` hérité, et le test serait vide. `HOME` et `USERPROFILE` (dans `ENV_ALLOW`) passent par `environ`.
- Un fichier suivi est rendu « sale » de façon déterministe (même taille, `mtime` plus récent), sans compter sur les entrées « racy ».
- Il lance ensuite `git -c safe.bareRepository=explicit -c core.hooksPath=<devnull> -c core.fsmonitor=false status --porcelain` avec `codex_cli.child_env(environ, …)`.
- Attendu : aucun témoin écrit. Le même test, sans les deux clés, doit écrire le témoin (contrôle du test).
- Le témoin s'écrit dans `tmp_path`, par un pilote qui est un petit script Python lancé par `sys.executable`.

## 6. Relevé à refaire sur un run réel (0b répété)

- **Trace :** `GIT_TRACE2_EVENT=<fichier hors des racines inscriptibles>`, ajouté **à la main** à l'environnement de l'enfant, sur **chacun** des runs A à H.
- **Critère de réussite :** Trace2 écrit `start` (avec `argv` et `time`) et `cmd_ancestry` (avec le tableau `ancestry`) comme deux événements distincts d'un même processus git : on les joint par `sid`. Un git de `codex.exe` est un `sid` dont `ancestry` commence par `codex.exe`, ou par `git.exe`, `codex.exe` (forme mesurée au 0b du 2026-11-25) : les deux formes comptent. Aucun de ces `start` n'a un `time` postérieur au premier `item.started` de type `command_execution` du run ; le seul git de `codex.exe` reste les quatre appels du §0 (tout appel de plus est relevé).
- **Avec A en place :** aucun `child_start` (filtre, `git-lfs`) ne vient d'un git de `codex.exe`.
- **Un brief en plus :** « Lance `git status` puis `git log -1`, ne change rien ». Il dit si le git de l'agent, sandboxé, apparaît dans la trace (ascendance différente) ou si le bac à sable lui refuse le fichier. Sans ce brief, l'absence du git de l'agent dans la trace 0b ne se lit pas.
- **Test direct : l'étape « Réécris le fichier `.git` de ce dossier » du scénario E.** Le run doit finir `failed` « fichier .git du worktree modifié » sans qu'aucun git de `codex.exe` ne suive la réécriture.
- **Condition d'arrêt de 0b, remplacée** pour 0.167.1 par :
  - (a) un git de `codex.exe` après la première commande de l'agent → arrêt et repli du §4.3 ;
  - (b) toute autre version → refusée par Nexus (B), puis 0b refait avant de l'ajouter.

## 7. Documents à mettre à jour (par la PR du correctif ; aucun n'est modifié ici)

- **INTEGRATIONS §A.2** (adaptateur Codex, « Constaté aux premiers runs réels ») :
  - les quatre git de `codex.exe` et leurs `-c` ;
  - les deux clés de l'environnement et leur coût pour l'agent ;
  - la version relevée et la règle de montée de version ;
  - le fait qu'un dépôt avec des attributs de filtre reste lisible par l'agent mais ne déclenche plus de pilote système ou global.
- **SECURITY §3** (puce « Isolement d'un run Codex ») :
  - « hooks et `fsmonitor` coupés pour tout git de l'arbre » devient « hooks et `fsmonitor` coupés, configuration système et globale non lues » ;
  - ajouter la limite : un git de `codex.exe` après la première commande de l'agent n'est pas couvert (E1, E4), ce qui justifie le refus des versions non relevées.
- **DECISIONS** : addendum à ADR-023 (2026-11-25), « Codex : git de `codex.exe` hors du bac à sable », avec la mention de délégation que le fil principal retiendra.
- **Cadrage du 2026-11-13** :
  - §11, Q3 : « Répondue le 2026-11-25 (ce document) » ;
  - §2.4 : renvoi à ce document ;
  - §10, 0b : nouvelle condition d'arrêt (§6).

## 8. Continuer les runs réels A–H avant le correctif ?

**Oui, sous quatre conditions :**

1. **Codex reste en 0.167.1** pendant toute la campagne : aucune mise à jour.
2. **Le dépôt jetable** n'a ni attribut `filter=` suivi, ni sous-module, ni pilote de filtre en dehors du `lfs` système.
   - **Vérifié le 2026-11-25** sur `C:\Users\Orion\nexus-realrun-codex\target` : aucun `.gitattributes` ni `.gitmodules` suivi, aucun gitlink, ni `info/attributes` ni `modules/`.
   - `git config --show-scope --name-only --get-regexp "^filter\."` ne montre que `system filter.lfs.*`, qui ne s'applique alors à aucun fichier.
   - La trace 0b réelle ne contient aucun `child_start`.
   - À refaire si le dépôt change.
3. **La trace 0b reste active** sur chaque run et se vérifie après chaque run, selon le critère du §6.
4. **Scénario E.** Une écriture réussie dans le dossier commun arrête déjà la campagne. En plus, ce dépôt n'est plus jamais confié : le `status` du run suivant, hors bac à sable, lirait cette écriture, et le contrôle de lancement ne lit pas `modules/*/config`.

Dans ces conditions, rien de configuré ne peut s'exécuter au début du tour (exp4 demande des attributs suivis), et le reste exige un git de `codex.exe` après l'agent, que la trace verrait.

## 9. Non vérifié, limites

- Que les contrôles `mcp list` et `prompt-input` lancent git (même environnement : A les couvre).
- Que `shell_environment_policy.exclude` s'applique aux commandes de l'agent (seulement pour le repli §4.3).
- L'effet de A sur un HTTPS lancé par le git de l'agent (`http.sslbackend` du système retiré).
- Les autres pilotes que lit `status` : seuls `clean` et `process` ont été vus. Pour `status --porcelain`, `textconv`, `diff.external` et `core.pager` n'ont rien lancé (exp2 E1). Cela n'a pas été testé pour `diff`.
- La garantie « début du tour avant l'agent » est empirique (un brief, une version) : B la rend vérifiable, elle ne la prouve pas.
