# Codex : couper le réseau des commandes de l'agent sous Windows (#207)

**Date :** 2026-11-26
**Issue :** #207 (refs #186, ADR-023 et ses addenda, ADR-024).
**Statut :** proposition d'un subagent, à trancher par le fil principal sous la délégation totale de Loïc du 2026-11-25 (ADR-024). Elle amende une décision de Loïc (`windows.sandbox=unelevated`, 2026-11-12) : le changement est réversible par une seule valeur de l'argv, et Loïc peut le renverser.
**Entrées :** `DECISIONS.md` (addendum du 2026-11-13 à ADR-023, ADR-024), `docs/superpowers/specs/2026-11-13-codex-commit-par-nexus-design.md` (§3, §11 Q2, 0c), `docs/SECURITY.md` (isolement d'un run Codex), `docs/INTEGRATIONS.md` (Codex, F), `server/src/nexus/adapters/codex_cli.py`, `codex_process.py`, `process_job_win.py`, et les sources de codex-cli au tag `rust-v0.167.1` (`codex-rs/windows-sandbox-rs/src/{env.rs,lib.rs,spawn_prep.rs,setup.rs,wfp.rs,elevated/runner_client.rs}`, `codex-rs/mxc-sandbox/README.md`, `codex-rs/exec/src/lib.rs`). `CONTEXT.md` est absent à la racine du dépôt : les décisions viennent de `DECISIONS.md`.
**Expériences :** banc jetable `C:\Users\Orion\nexus-realrun-codex` (worktree `data\worktrees\banc-E4-nc`, `CODEX_HOME` `data\codex-home`), codex-cli 0.167.1, Windows 11 Famille build 26300. Chaque sonde réseau, de fichiers ou de job passe par `codex sandbox -P <profil> -C <worktree> -- <commande>`, lancé par `codex_process.spawn(contain=True)` (le job de Nexus) avec l'environnement de `codex_cli.child_env`. Les appels de contrôle (`codex mcp list`, `codex debug prompt-input`, `codex features list`) et la mesure de durée de la sonde (§3) ont été lancés directement depuis un shell, avec `CODEX_HOME` du banc et l'environnement hérité, hors du job. Aucun modèle n'a été appelé, ni `codex exec`. Les seuls hôtes contactés sont `pypi.org` (GET sans données du disque) et `1.1.1.1:53` (une requête DNS pour `pypi.org`). Aucun fichier d'authentification n'a été lu. Les scripts sont hors du dépôt.

Niveau de preuve, noté entre crochets : **[mesuré]** sur ce poste ; **[source]** lu dans les sources de la 0.167.1 ou dans une documentation officielle ; **[raisonné]** déduit, non mesuré.

---

## 0. En bref

1. **Constat définitif [mesuré].** Sous `unelevated`, une commande de l'agent obtient une vraie réponse HTTPS d'un hôte public sans passer par le proxy : Python (OpenSSL) affiche `HTTP 200` pour `https://pypi.org/simple/`, dans le job de Nexus. Le bac à sable ne fait qu'écrire des variables de proxy vers `127.0.0.1:9` [source : `env.rs`, `apply_no_network_to_env`]. Aucun réglage `unelevated` essayé ne change ce résultat.
2. **Piège de mesure.** Sous `unelevated`, `curl.exe --noproxy '*'` et `[Net.HttpWebRequest]` (`Proxy = $null`) **échouent** en HTTPS. Le réseau n'y est pour rien : c'est schannel qui refuse le jeton restreint (`SEC_E_NO_CREDENTIALS`). Le HTTP en clair, le TCP brut, le DNS et l'OpenSSL de Python passent [mesuré]. Les autres clients TLS sans schannel (git, Node) passent sans doute aussi [raisonné].
3. **Réglage qui coupe [mesuré].** `windows.sandbox=mxc` (Microsoft MXC, `BaseContainer`), une valeur reconnue par la 0.167.1. Il fonctionne **sans droits d'administrateur** sur ce poste et **reste dans le job de Nexus**. Il coupe le TCP sortant (`WSAEACCES` 10013, immédiat), le DNS (résolveur système et UDP direct) et la boucle locale. Il garde l'écriture limitée au worktree et au dossier temporaire, refuse le dossier git, et git y fonctionne.
4. **Recommandation.** Nexus passe `-c windows.sandbox=mxc` (strict, jamais `prefer_mxc`) et épingle `-c sandbox_workspace_write.network_access=false`. Avant chaque run, une sonde fermée exige `10013` sur une connexion à `192.0.2.1:443` (TEST-NET, aucun hôte réel) ; toute autre issue donne « lancement impossible ». Un run réel avec le brief `TcpClient` de #207 confirme ensuite sous `exec`. La règle « pas de vrai dépôt » reste en place jusqu'à cette confirmation, et sa levée revient à Loïc (ADR-024).

---

## 1. La preuve de sortie (sous `unelevated`, dans le job)

Commande : `codex sandbox -C <worktree> -P :workspace -c windows.sandbox=unelevated -- <sonde>`, lancée par `codex_process.spawn(contain=True)`. Témoin : la même sonde hors du bac à sable.

| Sonde | Témoin | `unelevated` (A) |
|---|---|---|
| Python OpenSSL, `urllib` avec `ProxyHandler({})`, contexte TLS non vérifié, `https://pypi.org/simple/` | `HTTP 200` | **`HTTP 200`** (code 0) |
| `curl.exe --noproxy '*' http://pypi.org/simple/` (HTTP en clair) | `HTTP 403` | **`HTTP 403`** (code 0 : la réponse de Fastly prouve l'échange) |
| idem, `--resolve pypi.org:80:151.101.0.223` (IP directe, sans DNS) | `HTTP 403` | **`HTTP 403`** |
| `TcpClient` PowerShell vers `151.101.0.223:443` | — | `CONNECTE` |
| `socket.create_connection` Python vers `151.101.0.223:443` | — | `CONNECTE` |
| requête DNS UDP brute vers `1.1.1.1:53` | — | `REPONSE 90 octets` |
| `[Net.Dns]::GetHostAddresses('pypi.org')` | `RESOLU 2a04:4e42::223` | `RESOLU 2a04:4e42::223` |
| `curl.exe` sans option (proxy de l'environnement) | `HTTP 200` | `curl: (7) Failed to connect to pypi.org:443 over proxy 127.0.0.1 after 0 ms` |
| `curl.exe --noproxy '*' https://pypi.org/simple/` (schannel) | `HTTP 200` | `curl: (35) schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS (0x8009030e)` |
| `[Net.HttpWebRequest]`, `.Proxy = $null`, HTTPS (schannel) | `HTTP 200` | `ECHEC : La connexion sous-jacente a été fermée : Une erreur inattendue s'est produite lors de la réception.` |
| connexion à `127.0.0.1:<port d'écoute local>` | `CONNECTE` | `CONNECTE` |

Le `HTTP 200` utilise un contexte TLS non vérifié, mais seul l'échange compte ici : un attaquant n'a pas besoin de vérifier le certificat de son propre serveur. Une commande de l'agent peut donc envoyer hors du poste tout ce qu'elle lit (le bac à sable laisse lire tout le disque, mesuré à nouveau : `C:\Windows\win.ini` lu sous A et sous MXC), par HTTP, HTTPS sans schannel, TCP brut ou requêtes DNS. La boucle locale est ouverte aussi : l'API de Nexus est joignable (le jeton reste exigé, ADR-020).

---

## 2. Réglages de la 0.167.1 essayés

Toutes les lignes sont sous `codex sandbox`, dans le job de Nexus, sauf indication contraire. « Sort » veut dire que Python OpenSSL obtient `HTTP 200` et que le TCP brut affiche `CONNECTE`.

| Réglage | Résultat | Preuve |
|---|---|---|
| A. `-P :workspace -c windows.sandbox=unelevated` (argv actuel de Nexus) | **sort** ; DNS résolu ; boucle locale ouverte | [mesuré] |
| B. A + `-c sandbox_workspace_write.network_access=false` | **sort** (identique à A : c'est déjà la valeur par défaut) | [mesuré] |
| C. `-P :read-only -c windows.sandbox=unelevated` | **sort** ; PowerShell y tourne en ConstrainedLanguage, mais Python et curl ne sont pas touchés | [mesuré] |
| D. A + `--enable network_proxy` (fonctionnalité expérimentale) | **sort** (le proxy géré n'est qu'un proxy : un client qui l'ignore passe) | [mesuré] |
| E. `-P :workspace -c windows.sandbox=mxc` | **ne sort pas** : TCP `WinError 10013` immédiat, `getaddrinfo failed`, DNS UDP sans réponse (timeout), `curl (6) Could not resolve host` et `curl (7) Failed to connect … after 0 ms` par IP ; boucle locale refusée (10013) | [mesuré] |
| F. A + `--enable prefer_mxc` | ne sort pas (MXC choisi) ; **mais** `prefer_mxc` retombe sur l'ancien bac à sable quand MXC n'est pas disponible [source : README MXC] : un échec ouvert, donc exclu | [mesuré] + [source] |
| G. `windows.sandbox=elevated` | non relancé, pour ne pas ouvrir d'invite UAC chez Loïc. Vu deux fois : le 2026-11-12 (run réel, #186) et le 2026-11-26 par erreur (un `codex sandbox windows --help` lancé avec la configuration de Loïc) : `orchestrator_helper_launch_canceled: ShellExecuteExW failed to launch setup helper: 1223`. L'installation exige une élévation ; elle crée les comptes machine `CodexSandboxOffline` et `CodexSandboxOnline`, des filtres WFP persistants sur le SID du compte hors ligne et des règles de pare-feu (`codex sandbox uninstall` les retire). Les commandes tournent sous ce compte, par `CreateProcessWithLogonW` (`codex-command-runner.exe`), donc par le service d'ouverture de session secondaire : leur appartenance au job de Nexus n'est **pas vérifiée** (la page de Microsoft n'en dit rien) | [mesuré : 1223] + [source] |
| H. `--sandbox-state-disable-network` | non sondé : l'option ne vaut qu'avec `--sandbox-state-json`, un état opaque produit par l'app-server, que `exec` ne prend pas | [source : `codex sandbox --help`] |
| I. `[permissions.<profil>.network]` (`enabled`, `domains`, `mode`, `allow_local_binding`) | non sondé : ces clés règlent le proxy géré (D), pas la couche système. Sous `unelevated`, elles ne peuvent pas arrêter un client qui ignore le proxy | [source : README `network-proxy`] + [raisonné] |
| `system_proxy_fallback` (stable, actif), `respect_system_proxy` (expérimental) | non sondés : ils règlent le proxy amont de Codex lui-même | [source : `codex features list`] |

Ce que dit le source [source] : sous `unelevated`, le « blocage réseau » (`should_apply_network_block`) se réduit à `apply_no_network_to_env` : `HTTP(S)_PROXY`/`ALL_PROXY`/`GIT_HTTP(S)_PROXY` vers `127.0.0.1:9`, `PIP_NO_INDEX`, `NPM_CONFIG_OFFLINE`, `CARGO_NET_OFFLINE`. C'est un conseil donné aux outils, pas une barrière. Le vrai blocage n'existe qu'en `elevated` (WFP sur un compte dédié) et en `mxc` (politique réseau native du conteneur).

---

## 3. MXC dans les conditions de Nexus [mesuré]

| Propriété exigée par Nexus | `unelevated` (A) | `mxc` (E) |
|---|---|---|
| Lancé dans le job, sans droits d'administrateur | oui | oui (aucune invite, aucune installation) |
| Le processus de la commande est dans le job de Nexus (`IsProcessInJob`) | oui | **oui** |
| `kill_tree` arrête tout (aucun survivant) | oui | **oui** |
| Écrire dans le worktree | oui | oui |
| Écrire hors du worktree (`…\nexus-realrun-codex\probe207-outside.txt`) | refusé | refusé |
| Écrire dans le `TEMP` de l'enfant | oui | oui (peut-être virtualisé : MXC peut rediriger `LOCALAPPDATA` [source], non vérifié) |
| Écrire dans le dossier git du worktree (`…\.git\worktrees\<nom>`) | refusé | refusé |
| Ouvrir le fichier `.git` du worktree en écriture | refusé | refusé |
| `git status` dans le worktree | fonctionne | fonctionne |
| Lire hors du worktree | oui | oui (MXC exclut seulement les partages réseau étrangers à la politique [source]) |
| TCP sortant, DNS, boucle locale | ouverts | **refusés** |
| Durée d'un appel `codex sandbox … -- python -c …` | — | 260 à 325 ms (3 essais) |
| `-c windows.sandbox=mxc` accepté par les contrôles (`codex mcp list --json` → `[]`) | — | oui |
| `codex debug prompt-input` : texte des permissions | « Network access is restricted. » | identique |

---

## 4. Options

### Retenue : `windows.sandbox=mxc` strict, sonde fermée avant chaque run, confirmation par un run réel

Quatre changements, dans une seule PR :

1. **Argv.** `WINDOWS_SANDBOX = ("-c", "windows.sandbox=mxc", "-c", "sandbox_workspace_write.network_access=false")`. La seconde paire est déjà la valeur par défaut. Elle est épinglée pour qu'une couche de configuration future ne puisse pas rouvrir le réseau. La valeur reste sans guillemets et ne contient aucun caractère de `CMD_SPECIAL`. Les contrôles (`mcp list`, `prompt-input`) la reçoivent par `overrides()`, comme aujourd'hui.
2. **Sonde réseau fermée (`check_network_cut`)**, après `check_version` et avant le modèle, sous Windows seulement :
   - argv : `[binary, "sandbox", "-C", <worktree>, "-P", ":workspace", *WINDOWS_SANDBOX, "--", sys.executable, "-I", "-c", PROBE]`, avec le même `child_env` et `contain=True` ;
   - `PROBE` tente `socket.create_connection(("192.0.2.1", 443), 3)` et imprime l'erreur Windows ;
   - la sonde passe seulement si la sortie vaut exactement `ERR 10013` et le code 0 ;
   - `CONNECTE`, un timeout (signature de `unelevated` : 3,0 s mesurés), une autre erreur, un code non nul, une absence de MXC (`windows.sandbox = "mxc"` échoue alors avant le lancement [source]) ou un dépassement de `CONTROL_TIMEOUT` donnent « lancement impossible : le réseau du bac à sable n'est pas coupé », en mots fixes ;
   - la sortie n'est ni journalisée ni stockée, comme pour les autres contrôles.

   `192.0.2.1` (TEST-NET-1, RFC 5737) n'est routé nulle part : la sonde ne contacte aucun hôte réel, même quand elle échoue.
3. **`approval_policy` épinglé à `never`** (`-c approval_policy=never`, une valeur vérifiée par Codex : une valeur inconnue est refusée), par précaution. `exec` le pose déjà par défaut [source : `exec/src/lib.rs`, `AskForApproval::Never`]. Il ne le retire (`build_without_headless_approval_policy`) que si le relecteur d'approbations résolu est `AutoReview` (`--approve-for-me` ou configuration), ce que Nexus n'emploie pas. Il y a deux raisons d'épingler quand même :
   - une commande `require_escalated` tourne hors du bac à sable et contournerait toute couche réseau ;
   - les contrôles ne voient pas aujourd'hui la politique d'`exec`. Sans la clé, `prompt-input` décrit les demandes d'escalade sans politique ; avec elle, il dit « Approval policy is currently never » [mesuré]. Les contrôles jugent alors le texte que le modèle reçoit sous `exec`.
4. **Confirmation sous `exec`**, après la fusion et sur le banc jetable : un run réel avec l'argv de Nexus et le brief de #207 (connexion `TcpClient` vers `151.101.0.223:443`, puis Python OpenSSL vers PyPI). Il doit afficher un refus (`10013`) et finir sans erreur de Nexus. Le relevé 0b (les quatre git de `codex.exe`, hors bac à sable) est refait dans le même run (spec 2026-11-25, §6). `MEASURED_VERSIONS` ne change pas : la version est la même, seul le moteur du bac à sable change.

Pourquoi : c'est l'option la plus restrictive qui tienne sur Windows 11 Famille sans droits d'administrateur au moment du run. Elle coupe aussi le DNS et la boucle locale, ce que ne fait aucune règle de pare-feu par programme. Elle garde le job. Elle se défait en remettant une valeur dans `WINDOWS_SANDBOX` et en retirant la sonde (qui refuserait sinon tous les runs sous `unelevated`), ce qui rouvre le réseau. Elle échoue fermée deux fois : MXC strict n'a pas de repli, et la sonde refuse tout ce qui n'est pas `10013`.

### Écartées

- **Rester sur `unelevated`, avec un avertissement dans « Confier à Codex »** : la sortie reste ouverte (§1) ; un avertissement ne coupe rien.
- **Réglages `unelevated` (`network_access=false`, `:read-only`, `network_proxy`, `permissions.*.network`)** : mesurés sans effet (B, C, D) ou limités au proxy (I).
- **`features.prefer_mxc`** : retombe sur l'ancien bac à sable quand MXC manque, donc échec ouvert.
- **`windows.sandbox=elevated`** : exige une installation élevée par Loïc (UAC) qui crée des comptes et des filtres à l'échelle de la machine. Il échoue en non interactif (1223). Son appartenance au job n'est pas vérifiée (`CreateProcessWithLogonW`). L'installation reviendrait à Loïc, et rien ne la justifie tant que MXC suffit.
- **Règle sortante du Pare-feu Windows par programme** [raisonné] : sa création exige les droits d'administrateur (Loïc, une fois). Une règle vise un chemin d'exécutable, pas un arbre de processus ni un job : l'agent lance `python.exe`, `powershell.exe`, `curl.exe`, git ou une copie de n'importe quel binaire. Bloquer ces programmes partout casserait l'usage de Loïc. Le DNS passe par le service Client DNS (`svchost`), qu'une règle sur les programmes du run ne couvre pas.
- **Filtres WFP propres à Nexus** [raisonné] : ils exigent aussi les droits d'administrateur. WFP filtre par application ou par SID d'utilisateur, pas par job ; sans compte dédié, c'est refaire `elevated`.
- **AppContainer lancé par Nexus** [raisonné] : Nexus ne lance pas les commandes de l'agent, c'est `codex.exe` qui les lance. Envelopper tout `codex.exe` lui couperait l'API d'OpenAI, ou l'ouvrirait à tout l'arbre (`internetClient`), et demanderait des ACL sur le worktree, Python et git. MXC est la version de ce mécanisme que Codex intègre.
- **Refuser tout vrai dépôt, sans autre changement** : c'est l'état actuel (ADR-024). Il reste en vigueur jusqu'à la confirmation sous `exec`, mais ne ferme pas la fuite des contenus du disque pendant un run sur le banc.

---

## 5. Cas limites à tester d'abord (tests écrits avant le code)

Avec le faux `codex` (`codex_support.make_fake_codex`, jamais de modèle en CI), il faut une action `sandbox` qui imprime une sortie choisie :

1. Sortie `ERR 10013`, code 0 → le run démarre ; l'argv de la sonde égale exactement la liste attendue (`-P :workspace`, `windows.sandbox=mxc`, `network_access=false`, `sys.executable -I -c`).
2. `CONNECTE` → « lancement impossible », aucun `exec`, aucun worktree laissé en vie (même nettoyage que les autres refus).
3. Timeout de la sonde (sortie `ERR None` au bout de 3 s), code non nul, sortie vide, `ERR 10013` suivi d'une autre ligne, `ERR 10061` → refus.
4. Sonde qui dépasse `CONTROL_TIMEOUT` → refus, et l'arbre est arrêté par le job (même chemin que les contrôles actuels, `STOP_ATTEMPTS`).
5. MXC indisponible (le faux sort en erreur avant le lancement) → refus avec le même message fixe ; aucune bascule vers `unelevated`.
6. `windows=False` (POSIX) → ni sonde ni `WINDOWS_SANDBOX` ; l'argv POSIX ne change pas.
7. Les contrôles et `exec` reçoivent la même paire `windows.sandbox=mxc` (`overrides()`), et un lanceur `.cmd` la transmet intacte (C3 de la spec du 2026-11-13).
8. `approval_policy=never` figure dans l'argv d'`exec` et dans celui des contrôles.
9. La sortie de la sonde n'apparaît dans aucun journal (même garde que `check_isolation`).

Sur le banc, sans modèle, avant la PR (cas qui ne se testent pas avec un faux) :

10. Les descendants d'une commande meurent avec elle sous MXC [source : « the upstream runner terminates remaining descendants when the foreground process exits »]. C'est conforme à la consigne de Nexus (aucun processus en arrière-plan), mais un serveur de test lancé en tâche de fond par l'agent disparaît.
11. Boucle locale coupée : une tâche qui démarre un serveur local ou un test qui appelle `localhost` (Vite, pytest avec un serveur réel, Playwright) échoue sous MXC. C'est à écrire dans INTEGRATIONS comme limite des runs Codex.
12. Le `TEMP` de l'enfant reste-t-il la racine inscriptible que suppose `check_locations`, ou MXC le virtualise-t-il ? La règle de chevauchement de §2.2 reste juste dans les deux cas, mais la note de SECURITY doit dire lequel.
13. L'écriture dans le dossier git **commun** (`<dépôt>/.git/config`, `hooks/`, `refs/`) sous MXC : non tentée ici, comme sous `unelevated` (spec du 2026-11-13, §2.2).
14. Les chemins `pwsh.exe` et `powershell.exe` sous MXC (le README demande de les tester, pas seulement `cmd.exe`) ; seul `powershell.exe -Command` a tourné ici.

---

## 6. Ce que Nexus vérifie avant chaque run (échec fermé)

Dans l'ordre actuel de `codex.py`, la sonde s'insère après `check_version` et les contrôles d'emplacement, au même rang que `check_isolation`, sous Windows :

1. `codex --version` est une version relevée (inchangé) ;
2. **la sonde réseau rend exactement `ERR 10013`** (nouveau) ;
3. `codex mcp list --json` vaut `[]`, et `prompt-input` n'a pas de bloc de skills (inchangé, avec l'argv MXC).

Si un seul de ces points fait douter, le lancement est impossible, sans modèle. Coût mesuré de la sonde : environ 0,3 s.

---

## 7. Limites qui restent

- **Le disque reste lisible.** MXC coupe les tiers, pas OpenAI : ce que le modèle lit part au fournisseur du modèle, comme aujourd'hui.
- **Un seul build mesuré** (Windows 11 Famille 26300). La disponibilité de MXC dépend de l'environnement de sécurité des processus (PSEC) de Windows [source]. Une mise à jour peut l'enlever ou le changer, d'où la sonde à chaque run plutôt qu'un relevé unique.
- **Le passage par `exec` n'est pas mesuré.** Le README de MXC dit que `codex sandbox` suit le même chemin de préparation que l'exécution [source], mais seul le run réel de l'étape 4 le prouve. Jusque-là, la règle « pas de vrai dépôt » tient.
- **Les git de `codex.exe`** tournent hors du bac à sable (addendum du 2026-11-25) : MXC n'y change rien, ni en bien ni en mal. Ils n'ouvrent pas de réseau sur un dépôt sans `remote` atteignable, mais un `git fetch` de Codex lui-même n'a pas été observé.
- **MXC est en déploiement progressif dans la 0.167.1** : `prefer_mxc` y est « under development ». Toute nouvelle entrée de `MEASURED_VERSIONS` refait les mesures du §3 (réseau, job, fichiers) en plus du relevé 0b.
- **La sonde confirme la coupure, elle ne la prouve pas seule.** `10013` est aussi ce que rendrait un pare-feu ou un antivirus qui bloque le binaire de la sonde. Une coupure par un tiers pour Python seulement laisserait passer les autres binaires ; seule la combinaison de MXC strict, de la sonde et du run réel de l'étape 4 ferme le doute.
- **`sys.executable`** : le lanceur du venv de Nexus (`server\.venv\Scripts\python.exe`) rend lui aussi `ERR 10013` sous MXC, code 0 [mesuré, une fois, hors job]. Un autre interpréteur (paquet Tauri, ADR-017) devra être revérifié.
- **La recherche web** reste coupée par `-c web_search=disabled` (#202) : elle passe par le serveur d'OpenAI, pas par le poste, et MXC ne la couvre pas.

---

## 8. Ce qui revient à Loïc

- La levée de la règle « aucun run Codex sur un vrai dépôt » après la confirmation sous `exec` : c'est l'usage d'un de ses vrais dépôts (ADR-024).
- Toute installation `elevated` (UAC, comptes machine, WFP), si un jour MXC ne suffit plus. Elle n'est pas proposée ici.
- Le choix `mxc` amende sa décision du 2026-11-12 (`unelevated`) : il le découvre après coup et peut le renverser (ADR-024).

---

## 9. Fichiers touchés par la PR du correctif (aucun n'est modifié ici)

- `server/src/nexus/adapters/codex_cli.py` : `WINDOWS_SANDBOX`, `approval_policy=never` dans `ISOLATION_FLAGS`. La sonde va dans un module à part (`server/src/nexus/adapters/codex_network.py`) pour laisser `codex_cli.py` (273 lignes) sous le seuil.
- `server/src/nexus/adapters/codex.py` : l'appel de la sonde dans la séquence des contrôles.
- `server/tests/codex_support.py` (action `sandbox` du faux), `server/tests/test_codex_cli.py` (C1, C3), `server/tests/test_codex_isolation.py`, nouveau `server/tests/test_codex_network.py` ; `web/e2e/fake-codex.mjs` s'il doit répondre à la sonde.
- `docs/SECURITY.md` (la « Limite connue (#207) » devient la description de MXC et de la sonde), `docs/INTEGRATIONS.md` (Codex, F, et matrice : réserve #207 levée après l'étape 4), `DECISIONS.md` (addendum à ADR-023 : `mxc` remplace `unelevated`, choisi par l'agent sous ADR-024).
