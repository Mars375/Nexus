# Codex : l'entrée de confiance que `codex exec` écrit dans le `CODEX_HOME` de Nexus

- Issue #186. Addendum au cadrage `2026-11-13-codex-commit-par-nexus-design.md` : il répond à §11 Q12, complète la réponse à Q5 et ajuste la règle 1 du §5.3, comme le prévoyait Q12 (« la liste de refus s'ajuste alors par une PR »).
- **Choisi par l'agent sous la délégation de Loïc du 2026-11-13.** Ce n'est pas Loïc qui a choisi ; il peut l'infirmer (§7).
- Les mesures ont été faites le 2026-11-23 avec codex-cli 0.167.1 sous Windows 11, sans connexion. Aucun modèle n'a été appelé : chaque `exec` s'arrête sur un 401 de `api.openai.com`, sans jeton. Les dépôts et les `CODEX_HOME` étaient jetables, sous `C:\Users\Orion\nexus-realrun-codex\trust1` et `trust2`. Aucun `auth.json` n'y existait (vérifié par le nom). Ni `~/.codex` ni le `data\codex-home` du banc n'ont été touchés.

## 1. Le constat

Chaque `codex exec` lancé avec l'argv de Nexus écrit `<CODEX_HOME>\config.toml`, même dans un `CODEX_HOME` vide. Le fichier contient une seule table, `[projects.'<racine du dépôt principal, en minuscules>']`, avec `trust_level = "trusted"`. La règle 1 du §5.3 refuse tout `config.toml` : après le premier run, tous les runs suivants sont refusés (« lancement impossible »). C'est la condition d'arrêt de Q12.

## 2. Mesuré

Montage : un dépôt `repo`, son worktree `wt/w1`, des `CODEX_HOME` neufs (sans entrée, entrée `trusted`, entrée `untrusted`). Chaque `CODEX_HOME` reçoit l'environnement exact de `codex_cli.child_env` et l'argv exact de `codex_cli` (contrôles et run). Pour voir ce qui est chargé, sans modèle, on dépose une configuration de projet sous l'une de deux formes :
- une sonde : `[mcp_servers.probe_<cas>]` plus `developer_instructions = "MARQUEUR_PROJET_<cas>"`, observée dans `mcp list --json` et `debug prompt-input` ;
- un fichier cassé (`[broken`) : Codex échoue au démarrage s'il le lit.

| # | Cas | Résultat |
|---|---|---|
| M1 | `exec` dans un `CODEX_HOME` vide | Il écrit `[projects.'c:\users\…\trust1\repo']` / `trust_level = "trusted"`. La clé est le dépôt **principal**, pas le worktree. Il crée aussi `.sandbox/`, `installation_id`, `tmp/`, `goals_1`, `logs_2`, `memories_1`, `queue_1`, `state_5` (`.sqlite` avec `-shm` et `-wal`). Les contrôles créent en plus `.sandbox_migration`. |
| M2 | Chemin du dépôt avec une espace, un accent et une apostrophe | Codex passe à une chaîne TOML entre guillemets, aux `\` échappés. Après lecture par `tomllib`, la clé vaut `os.path.normcase(str(repo.resolve()))`. |
| M3 | `exec`, entrée `untrusted` déjà présente | Codex la réécrit en `trusted`. |
| M4 | `exec`, entrée `trusted` plus une table `[mcp_servers.extra]` | Codex garde la table et l'entrée. Il modifie le fichier, il ne le remplace pas. |
| M5 | Contrôles (`mcp list`, `prompt-input`, sans `--ignore-user-config`), sonde dans `wt/.codex`, entrée `trusted` (clé du dépôt, ou clé du worktree) | `mcp list` montre `probe_…`. `prompt-input` contient le marqueur. La couche projet du worktree est **chargée**. |
| M6 | Même cas, sans entrée ou avec une entrée `untrusted` | `[]`, pas de marqueur : rien n'est chargé. |
| M7 | Contrôles, fichier cassé dans `repo/.codex` (dépôt principal, hors worktree), entrée `trusted` | Code 1 : « Error parsing project **hooks** config file `…\repo\.codex\config.toml` », malgré `--disable hooks`. Sans entrée : code 0. La sonde au même endroit ne charge ni MCP ni marqueur : Codex ne lit ce fichier que pour les hooks. |
| M8 | `exec` (avec `--ignore-user-config`), fichier cassé dans `wt/.codex` ou `repo/.codex`, sans entrée ou avec une entrée `trusted` | Aucune erreur de configuration. `thread.started`, puis le tour échoue sur le 401. **`exec` ne charge pas la couche projet au démarrage.** |
| M9 | Témoin de M8 : `exec` **sans** `--ignore-user-config`, entrée `trusted`, fichier cassé dans `wt/.codex` | Code 1 : « Error loading config.toml: Error parsing project config file … ». L'observable fonctionne bien dans `exec`. C'est `--ignore-user-config` qui écarte la couche projet. |
| M10 | Contrôles sans aucun `.codex` (dépôt qui ne contient que `README.md`), sans entrée et avec une entrée `trusted` | `mcp list` : `[]` dans les deux cas. `features list` : sorties identiques. `prompt-input` : une seule différence de fond, le mode de bac à sable par défaut décrit (`read-only` sans entrée, `workspace-write` avec le worktree comme racine inscriptible quand l'entrée existe). Aucun bloc de skills dans les deux cas. |
| M11 | `-c projects.'<repo>'.trust_level="untrusted"`, `--skip-git-repo-check` (relevé du 2026-11-22) ; `exec --trust`, `--no-trust` ; `mcp list` et `debug prompt-input` avec `--ignore-user-config` | Les deux premiers n'empêchent pas l'écriture. Les autres options sont inconnues de la 0.167.1 (« unexpected argument », code 2). |

Ce qu'on en tire :
- L'entrée de confiance ne change rien au run lui-même (M8, M9).
- Elle ne change que les contrôles, qui lisent le `config.toml` du `CODEX_HOME`. Avec l'entrée, ils chargent la couche `.codex` du worktree (M5) et lisent le `.codex/config.toml` du dépôt principal, pour les hooks (M7).
- Le `.codex` du worktree est déjà refusé avant les contrôles (DECISIONS, addendum du 2026-11-20). Celui du dépôt principal ne l'est pas : un `.codex` non suivi par git, à la racine du dépôt de Loïc, serait **lu**. Le §5 l'interdit.

## 3. Non vérifié

- N1. Ce que `codex login` et un tour **authentifié** écrivent dans `config.toml`. Si l'un des deux ajoute une clé hors de `projects.*.trust_level`, la règle du §4 refuse de nouveau tous les runs. Ce n'est pas plus grave qu'aujourd'hui, mais il faudrait une nouvelle PR. À relever à l'étape 0a du §10, en notant les **noms de clés** seulement.
- N2. Que `exec` ne charge pas la couche projet **plus tard** dans le tour. M8 couvre le démarrage seulement, faute de modèle. Le refus du `.codex` (dépôt principal et worktree) couvre ce cas de toute façon.
- N3. La forme de la clé sous POSIX (casse, liens) n'a pas été mesurée. La CI tourne sous Ubuntu, donc les tests construisent la clé avec la normalisation du contrôle lui-même.
- N4. Qu'une entrée sur un dossier **parent** fasse confiance à ses sous-dossiers. La règle du §4 refuse toute clé autre que la racine d'un dépôt configuré, donc la question ne se pose pas.
- N5. La documentation officielle décrit une option `exec --trust` (« Trust persists with `--ephemeral` ») absente de la 0.167.1. Une version future pourrait ne plus écrire l'entrée. Il faut refaire M1 à chaque mise à jour de Codex.
- N6. Une entrée devient étrangère quand un dépôt est retiré de `NEXUS_RUN_WORKDIRS`, déplacé ou renommé après un run. C'est aussi le cas quand un dépôt configuré est lui-même un worktree lié, puisque la clé de Codex désigne le dépôt principal. Tous les runs Codex sont alors refusés, avec un message fixe qui ne dit pas pourquoi, jusqu'à ce que l'entrée soit retirée à la main. Le refus reste fermé ; c'est le prix de la règle 4 du §4.

## 4. Option retenue : accepter un `config.toml` qui ne contient que des entrées de confiance, et refuser aussi le `.codex` du dépôt principal

Règle 1 du §5.3, nouvelle forme (`codex_cli._check_home`). Les autres entrées de la liste de refus ne changent pas. Un `config.toml` est accepté seulement si **toutes** ces conditions valent ; sinon, même refus qu'aujourd'hui (« CODEX_HOME de Nexus configuré : lancement refusé », mots fixes, contenu jamais journalisé) :
1. C'est un fichier ordinaire : ni dossier, ni lien (`is_symlink`), et au plus 64 Kio.
2. Ses octets se décodent en UTF-8 strict et `tomllib.loads` les lit sans erreur. Une marque d'ordre d'octets ou une clé en double donne donc un refus.
3. Le document vaut exactement `{"projects": P}`, avec `P` non vide. Chaque valeur de `P` vaut exactement `{"trust_level": "trusted"}` ou `{"trust_level": "untrusted"}`. `untrusted` ne fait que retirer des couches (M6).
4. Chaque clé `k` de `P` vérifie `os.path.normcase(k) == os.path.normcase(str(w.resolve()))` pour un `w` de `NEXUS_RUN_WORKDIRS`. La comparaison porte sur **tous** les dépôts configurés, pas seulement celui du run : le `CODEX_HOME` est partagé. Une clé qui désigne le worktree, un parent ou un autre dossier est refusée, et `k` n'est jamais résolu sur le disque.

Le reste de la règle :
- `*.config.toml` reste refusé sans exception (`-p` ne sert pas, mais un profil est une configuration).
- **Nouveau refus**, avant la création du worktree (comme le pilote de filtre, §1.4) : une entrée `.codex` (dossier, fichier ou lien, `os.path.lexists`) à la racine du **dépôt principal** donne « lancement impossible », sans worktree ni branche. Le refus du `.codex` du worktree reste en place.
- Résultat : avec ces deux refus, le premier run (sans entrée) et les suivants (avec entrée) passent les contrôles sur la même configuration chargée. M10 l'a mesuré. Seul le mode de bac à sable par défaut décrit par `prompt-input` change, et le run fixe le sien par `--sandbox workspace-write`.
- L'argv ne change pas : pas de `-c projects…`, dont une clé de chemin casserait la règle C2 (`[A-Za-z0-9_.=-]+`).

Pourquoi cette option : l'entrée est écrite par `codex.exe` lui-même, hors du bac à sable. L'agent ne peut pas écrire dans le `CODEX_HOME` (relevé 0c : `hooks.json` y est refusé). L'entrée n'agit pas sur le run (M8, M9). Nexus lit et vérifie le fichier entier avant chaque lancement ; il ne l'accepte jamais sans l'avoir lu. Il n'écrit rien et ne nettoie rien : l'option n'ajoute aucun état à entretenir. Tout doute (fichier cassé, clé étrangère, table ajoutée comme en M4) refuse le lancement.

Options rejetées :
- (b) Nexus écrit lui-même le fichier (`untrusted`) : `exec` le réécrit en `trusted` (M3), et Nexus écrirait dans le dossier de la connexion de Loïc.
- (c) Supprimer le fichier après chaque run : un état à entretenir. Un arrêt brutal entre la fin et la suppression bloquerait les runs, et Nexus supprimerait un fichier dans le dossier de la connexion, pour rien puisque le run ne lit pas l'entrée (M8).
- (d) Une option qui empêche l'écriture : aucune en 0.167.1 (M11). `--trust` n'existe pas encore.
- (e) Passer `--ignore-user-config` aux contrôles : refusé par `mcp list` et `prompt-input` (M11).
- (f) N'accepter que la clé du dépôt du run : le deuxième dépôt configuré serait refusé après un run sur le premier.

## 5. Tests à écrire d'abord (faux Codex, jamais le vrai binaire)

Clé construite par le test comme le fait le contrôle : `os.path.normcase(str(repo.resolve()))`, écrite avec `json.dumps` (une chaîne JSON entre guillemets est une chaîne de base TOML valide).
- T1. Runs enchaînés (régression de Q12) : le faux `exec` écrit dans `$CODEX_HOME/config.toml` les octets mesurés en M1. Le deuxième `dispatch` lance bien les deux contrôles puis le run.
- T2. Les entrées `trusted` et `untrusted` d'un dépôt configuré sont acceptées. Deux dépôts configurés et deux entrées : acceptées.
- T3. Refus, sans aucun appel de contrôle (`r.kinds() == []`), pour : `config.toml` = `"x"` (cas C5 existant, gardé tel quel) ; TOML cassé ; marque d'ordre d'octets ; clé en double ; `[projects]` vide ; `trust_level = "trusted"` plus une autre clé dans la même table ; valeur inconnue (`"yes"`, `true`) ; table de premier niveau en plus (`[mcp_servers.x]`, `model = "x"`) ; clé du worktree ; clé d'un parent du dépôt ; clé d'un dossier non configuré, seule ou à côté d'une clé valide ; `config.toml` qui est un dossier ; un lien (ignoré si le système ne crée pas de lien) ; plus de 64 Kio ; octets non UTF-8.
- T4. `x.config.toml` qui ne contient qu'une entrée valide : toujours refusé.
- T5. `.codex` (dossier, fichier vide) à la racine du dépôt principal, **non suivi par git**, avec ou sans `config.toml` : refusé avant le worktree, aucune branche `nexus/*`, aucun appel de contrôle. Le test Q5 existant (`.codex` commité) reste inchangé. Désormais, c'est le contrôle du dépôt principal qui l'arrête.
- T5 bis. `.codex` commité, puis supprimé de l'arbre de travail principal (supprimé du disque seulement, toujours suivi par git) : le contrôle du dépôt passe, puis celui du **worktree** refuse. Aucun appel de contrôle, et le worktree comme la branche sont retirés. Sans ce test, la branche « `.codex` du worktree » n'est plus couverte.
- T6. L'argv du run et des contrôles est identique avec et sans `config.toml` de confiance.
- T7. Le message de refus ne contient ni le chemin ni le contenu du fichier (une chaîne témoin placée dans une clé étrangère n'apparaît ni dans l'exception ni dans `caplog`).

## 6. Fichiers, tailles, documentation

- `server/src/nexus/adapters/codex_cli.py` (213 lignes, environ 245 après) :
  - `_check_home(home, roots)` et un `_trust_only(path, roots) -> bool` ;
  - `check_isolation(..., repo_roots)` ;
  - un `check_no_project_config(path)` partagé par le dépôt et le worktree.
- `server/src/nexus/adapters/codex.py` (335 lignes, environ 340 après) : il passe `self.workdirs` et appelle `check_no_project_config(repo)` juste après `check_no_filter_driver`.
- Tests :
  - `server/tests/test_codex_isolation.py` (393 lignes, seuil 600) si l'ajout tient sous 600 ; sinon un nouveau fichier `server/tests/test_codex_home_trust.py` qui reprend `Rig`. Le déplacement de `Rig` vers `codex_support.py` se fait sans changer de test.
  - `server/tests/codex_support.py` : une action `trust_home` du faux `exec`.
- Documentation :
  - `docs/INTEGRATIONS.md` §A.2 : contrôle (1), nouveau refus, et la liste de M1 dans le relevé (ligne 81).
  - `docs/SECURITY.md` §3 (« Isolement d'un run Codex ») : l'entrée de confiance acceptée et ses limites, le `.codex` du dépôt principal refusé.
  - `DECISIONS.md` : un addendum du 2026-11-23 (choisi par l'agent sous la délégation du 2026-11-13).
  - Le cadrage du 2026-11-13 : Q12 répondue, Q5 complétée (M5 à M9), règle 1 du §5.3 renvoyée ici.
- Une PR `fix/186-codex-home-confiance` depuis `master` à jour, `Refs #186`. Le circuit de relecture habituel s'applique : la PR touche un invariant d'isolement, donc elle passe par `architect`, puis `implementer`.

## 7. Ce qui revient à Loïc

1. Infirmer le choix s'il le veut. Variante plus stricte : refuser tout `config.toml` et accepter qu'un seul run Codex soit possible par nettoyage manuel. Cette variante est inutilisable en pratique.
2. Le nouveau refus d'un `.codex` **non suivi** à la racine d'un dépôt configuré : si Loïc garde une configuration Codex locale dans l'un de ses dépôts, ce dépôt ne peut plus être confié à Codex par Nexus.
3. Si Loïc retire, déplace ou renomme un dépôt après un run Codex, il doit retirer la table `[projects.…]` correspondante de `<NEXUS_DATA_DIR>\codex-home\config.toml` (N6), et supprimer le fichier s'il ne reste aucune entrée (un `config.toml` sans entrée est refusé, règle 3 du §4). Sinon, tous les runs Codex sont refusés.
4. Au premier run connecté (étape 0a) : noter les **noms** des clés de `config.toml` après `codex login` puis après un tour réussi (N1). Si une clé autre que `projects.*.trust_level` apparaît, les runs reprennent leur arrêt et une PR ajuste la règle.
