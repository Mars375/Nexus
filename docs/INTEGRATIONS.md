# INTEGRATIONS — Nexus

**Version :** 0.2 (refonte : exécutants et sources derrière adaptateurs — ADR-011, ADR-013, ADR-016)
**Date :** 2026-09-28

---

## Principe

> **Nexus est autonome ; les systèmes externes sont branchés derrière des adaptateurs remplaçables.** Nexus possède ses tâches et événements. Les données externes restent chez leur propriétaire : Nexus les lit, les affiche, et agit dessus via l'adaptateur — avec gating et read-back pour toute action sortante.

Deux familles :

- **Exécutants** — à qui Nexus confie du travail (« confier à ») : Hermes, Claude Code, Codex, Orca.
- **Sources** — ce que Nexus lit et sur quoi il agit : chats, mail, agenda, Git, mémoire, infra, nœuds, quotas, cron.

---

## A. Exécutants

### 1. Hermes — agents de nœud (Phase 2)

**Rôle :** exécutant pour Helios, Mnēma et Aether (ADR-013).

**Vérifié le 2026-09-27/28 (lecture seule) :**

- Hermes Kanban est une file de travail **pour agents** : toute tâche assignée à un profil et `ready` est lancée par le dispatcher (60 s) ; `triage` passe par un décomposeur LLM (mode Auto, actif sur Helios) ; `review` lance un relecteur. C'est pourquoi les tâches Nexus n'y vivent pas (ADR-011).
- Machine d'états : claim atomique, heartbeat, reclaim, retry (`failure_limit=2`), stale timeout 14 400 s, circuit breaker.
- Tables : `tasks`, `task_runs`, `task_events`, `task_comments`, `task_links`, `task_attachments`, `kanban_notify_subs`.
- Surfaces : CLI `hermes kanban …`, API dashboard + WebSocket `/api/plugins/kanban/events?since=<event_id>&board=<slug>`.
- Statuts et événements relevés : [notes/2026-09-28-releve-enums-hermes-kanban.md](notes/2026-09-28-releve-enums-hermes-kanban.md), mis à jour pour la v0.23.0 dans [notes/2026-11-11-releve-hermes-0-23.md](notes/2026-11-11-releve-hermes-0-23.md) (options de `create`, `show --json`, tableaux, dispatcher).

**Adaptateur `hermes` :**

- `dispatch` : crée une tâche Hermes assignée au profil de l'agent choisi (`hermes kanban create … --assignee <profil> --idempotency-key <nx-run-id>`), sur un board dédié à Nexus (à créer, ex. `nexus`).
- `watch` : suit le run via WS/DB ; traduit `claimed`, `blocked`, `review_requested`, `completed` en événements Nexus ; reprend `metadata` de complétion comme preuves.
- Ne crée jamais de tâche Hermes sans « confier à » explicite.

**Adaptateur Hermes (ADR-023, lot G ; cadrage : `docs/superpowers/specs/2026-11-11-adaptateur-hermes-design.md`).**

- **Réglages.** `NEXUS_HERMES_BIN` (binaire ; **sans valeur, rien n'est enregistré**, aucun repli sur le `PATH`) et `NEXUS_HERMES_PROFILE` (profil Hermes qui travaille pour l'agent `helios` ; `default` par défaut : Helios est le profil `default` de Hermes pour Kanban). `NEXUS_RUN_MAX_MINUTES` est partagé avec Codex. Le tableau est la constante `nexus`.
- **Création du tableau, une fois, par Loïc** (Nexus ne crée ni ne change jamais de tableau) : `hermes kanban boards create nexus --name Nexus`, sans `--switch` ; `hermes kanban boards show` doit répondre `default`. Sans tableau ou sans profil, la sonde échoue, l'adaptateur n'est pas enregistré et « Confier à Helios » reste un 409 `executor_unavailable`. Mnēma et Aether sont refusés (409 `executor_unavailable`, rien n'est créé).
- **Dispatch.** `hermes kanban --board nexus create "Nexus nx-run-<n> nx-task-<m>" --body-file - --assignee <profil> --idempotency-key nx-run-<n> --max-runtime <s> --max-retries 1 --workspace scratch --created-by nexus --json` ; le brief passe par l'entrée standard, suivi d'une consigne fixe de Nexus (terminer avec `kanban_complete`, lister les livrables dans `metadata.artifacts`). Un essai raté est rejoué une fois avec la même clé, une fois le premier arrêté ; une issue incertaine (délai, sortie illisible) met le run en `unknown` (« lancement incertain ») jusqu'à l'annulation, qui retrouve la tâche par son titre.
- **Suivi.** `show --json` au plus toutes les 10 s par run ; le curseur est la **position** du dernier événement Hermes consommé (les événements n'ont pas d'id), l'id publié est `nx-run-<n>-<position>`. Un type d'événement inconnu est ignoré. `review_dispatch` : la relecture de Hermes est une étape intérieure du run (`progress`), jamais un `review` Nexus.
- **Preuves.** Seule une pièce jointe recopiée par Hermes (`kanban_complete` ou `kanban_request_review`, `hermes kanban --board nexus attachments <id> --json`) et présente sur le disque avec la bonne taille fait `done` (`file:<chemin>` plus `hermes:nexus/<id>`) ; sinon `review`. Un commit déclaré va dans le `payload`, jamais dans la preuve.
- **Fins.** `blocked` et `gave_up` (disjoncteur `--max-retries 1`) ferment le run et la tâche Hermes est archivée ; la durée maximale de Nexus archive aussi. Annulation : `archive`, puis `show` doit la voir `archived` et `archive_worker_termination` avec `terminated: true` ; sinon l'annulation est réessayée, sauf si Loïc a arrêté le worker à la main et créé le fichier vide `<NEXUS_DATA_DIR>/hermes/.stopped/nx-run-<n>`.
- **Limites connues.** Au redémarrage de Nexus le run passe `unknown` (ADR-023 D3) alors que Hermes continue : Loïc l'annule. Si la CLI de Hermes échoue, la durée maximale de Nexus ne s'applique pas (le worker reste borné par `--max-runtime`). Après un plantage de Nexus pendant un `create`, un processus `hermes` orphelin pourrait finir son insertion après la recherche par titre (risque accepté). La position d'un événement n'est stable que si Hermes n'en insère jamais avant un événement déjà lu ; sinon un id refusé gèle le curseur et la durée maximale clôt le run.
- **Constaté aux premiers runs réels (2026-11-11, Hermes v0.23.0, profil `default` de Helios, modèle deepseek-v4.1-flash) :** quatre scénarios, tous conformes.
  - *Fichier livrable* (nx-run-3, environ 3 min) : `claimed` → `working` → `done`, preuve `file:…\kanban\boards\nexus\attachments\t_…\synthese.md` (pièce jointe `uploaded_by: kanban_complete`, taille relue) plus `hermes:nexus/t_…` ; la tâche Hermes porte `created_by: nexus`, `max_runtime_seconds: 1800`, `max_retries: 1`, `workspace_kind: scratch`, corps accentué intact.
  - *Sans livrable* (nx-run-6) : `review` avec le résumé de Helios, jamais `done`.
  - *Annulation pendant le travail* (nx-run-4) : `archive` puis `archive_worker_termination` (`terminated: true`, `host_local: true`), worker absent de la liste des processus ; run Nexus `cancelled` en un tour.
  - *Redémarrage de Nexus pendant un run* (nx-run-5) : `unknown`, puis l'annulation archive la tâche et arrête le worker (`terminated: true`) ; run `cancelled`.
  - Événements Hermes vus : `created`, `claimed`, `tip_scratch_workspace`, `spawned`, `owner_admitted`, `worker_bound`, `heartbeat`, `attached`, `completed`, `worker_result`, `archived`, `archive_worker_termination` (les inconnus de l'adaptateur sont ignorés, comme prévu). `metadata` d'une fin avec fichier : `artifacts`, `changed_files`, `decisions`, `verification`, `worker_session_id` ; sans fichier : `worker_session_id` seul. Une annulation laisse le run Hermes `reclaimed` avec `ended_at` renseigné. Délai observé entre le dispatch et la prise : 40 à 70 s (un tour du dispatcher). Aucun refus de publication dans le journal du serveur ; le tableau `default` n'a reçu aucune tâche et le tableau courant est resté `default`.
  - Non encore vus en réel : `blocked`, `gave_up`, `review_requested` / `changes_requested` (relecture Hermes) et la durée maximale ; leurs clés de `payload` restent celles lues dans le code.

### 2. Claude Code, Codex, Orca (Phase 2)

- Claude Code : sessions locales (`~/.claude`) ; Codex : `codex exec -p <profil>`, `~/.codex` ; Orca : CLI `orca`, worktrees/devcontainers.
- `dispatch` : lance une session non interactive sur la tâche (brief = objectif + contexte + preuves attendues) ; l'adaptateur traduit la sortie de l'agent en événements Nexus (l'agent ne reçoit aucun jeton, ADR-023).
- `watch` : suit le processus/la session ; relie `run ↔ session ↔ artefacts`.
- **DONE ≠ preuve** : la preuve est relue, pas supposée.

**Adaptateur Codex (ADR-023, lot C).** Réglages : `NEXUS_CODEX_BIN` (binaire ; à défaut `codex` du `PATH`), `NEXUS_RUN_WORKDIRS` (dépôts git où un run peut travailler, séparés par `;` sous Windows et `:` ailleurs) et `NEXUS_RUN_MAX_MINUTES` (60 par défaut). L'adaptateur n'est enregistré que si le binaire répond à `--version` et si au moins un dépôt est configuré ; sinon « confier à Codex » reste un 409 `executor_unavailable`. Un run reçoit un worktree dans `<NEXUS_DATA_DIR>/worktrees/nx-run-<n>` et une branche `nexus/nx-run-<n>` (jamais le dépôt d'où tourne le serveur, jamais un dépôt hors de la liste ; si plusieurs dépôts sont configurés, le `workdir` du run en désigne un). La commande est `codex exec --json --sandbox workspace-write --cd <worktree> -` : une liste d'arguments, sans shell ; le brief (ce que Loïc a écrit, ni commentaires ni notes d'agents) passe par l'entrée standard, jamais en argument ; l'environnement de l'enfant vient d'une liste blanche (ni `NEXUS_*`, ni clé du shell) ; le contournement du bac à sable n'est jamais demandé. La sortie brute n'est jamais écrite : un fil de lecture traduit chaque ligne JSONL en fait (message, commande, fichiers modifiés), en mémoire, et le superviseur le publie (masquage des secrets). Nexus ne pousse ni ne fusionne.
- **Preuve** : à la création du worktree, l'adaptateur note le commit de départ. À la fin du tour il exige que le commit produit existe, descende du départ (`git merge-base --is-ancestor`) et lui soit postérieur (`git rev-list --count` > 0) ; alors `done` avec `commit:<12 premiers caractères>` (un hash complet de 40 caractères est masqué par le scanner et ne prouverait rien). Sinon `review`, avec `branch:nexus/nx-run-<n>`.
- **Garde-fous** : au-delà de la durée maximale, le processus est tué (arbre entier : `taskkill /T /F` sous Windows, groupe de processus ailleurs) et le run passe en `failed` ; l'annulation tue de même l'arbre et exige que l'arrêt soit confirmé. À l'arrêt propre du serveur, les processus Codex encore actifs sont arrêtés et notés ; si le serveur redémarre, le run passe en `unknown` (l'histoire en mémoire est perdue) : Loïc relit la branche, et l'annulation ne réussit que si l'arrêt est confirmé (arrêt propre noté) ; après un plantage, elle reste en attente et retient l'exécutant tant que Loïc n'a pas arrêté le processus à la main puis créé le fichier vide `<NEXUS_DATA_DIR>/worktrees/.stopped/nx-run-<n>` (limite connue, à améliorer).
- **Git sous contrôle** : toutes les commandes git de l'adaptateur partent du dépôt (jamais du worktree, que l'agent peut modifier), avec l'environnement filtré, sans hooks ni fsmonitor ; la preuve se lit sur `refs/heads/nexus/nx-run-<n>`, pas sur la `HEAD` du worktree. Le dépôt du serveur est exclu par son répertoire git commun (worktrees compris). Limite Windows : `taskkill /T` ne retrouve pas un petit-enfant dont le père est déjà mort.
- **À confirmer au premier vrai run de Loïc** : la forme exacte des lignes JSONL de `codex exec --json` (types `thread.started`, `turn.started`, `item.completed`, `turn.completed`, `turn.failed`, `error`), isolée dans `adapters/codex_translate.py` ; l'instant `at` des événements (l'heure de lecture, faute d'horodatage connu) ; la liste blanche d'environnement (Codex retrouve sa connexion par `CODEX_HOME` ou le profil utilisateur) ; le comportement des approbations en mode non interactif ; **la création du commit sous `--sandbox workspace-write`** (sur macOS, ce profil protégerait le répertoire git du worktree en écriture : l'agent ne pourrait alors pas commiter et le run finirait en `review`) — rien n'est affaibli en attendant : si c'est le cas, Loïc décidera comment permettre le commit (risque pour la configuration git et les hooks du dépôt à documenter dans SECURITY alors). Aucune CI ne lance un vrai Codex : les tests utilisent un faux exécutable.
- **Constaté aux premiers runs réels (2026-11-10/11, codex-cli 0.166)** : les types `thread.started`, `turn.started`, `item.completed` (`agent_message`), `turn.completed` et `turn.failed` ont bien la forme attendue. Une ligne `error` n'est pas un échec : Codex en écrit une par tentative de reconnexion (« Reconnecting... 1/5 ») puis peut terminer son tour ; seul `turn.failed` (ou une sortie en erreur) fait échouer le run, et son message en est la cause, par exemple un quota épuisé avec l'heure de reprise (#176).

**Adaptateur Claude Code (ADR-023, lot H).** Cadrage : `docs/superpowers/specs/2026-11-11-adaptateur-claude-code-design.md`. Chaque run consomme l'abonnement Claude de Loïc ; aucune CI ne lance un vrai `claude` (les tests utilisent un faux exécutable).
- **Réglages** : `NEXUS_CLAUDE_BIN` (obligatoire, **aucun repli sur le `PATH`**), `NEXUS_RUN_WORKDIRS` et `NEXUS_RUN_MAX_MINUTES` (communs avec Codex). L'adaptateur n'est enregistré, sous l'exécutant `claude`, que si le binaire est trouvé, si un dépôt valide est configuré et si `claude --version` répond en 10 s (la sonde ne lance aucun modèle et ne lit aucun compte). L'exécutant et l'agent sont l'acteur existant `claude` ; `claude-code` n'est que l'`origin` des événements. Le modèle (`haiku`, `sonnet` ou `opus`) est choisi à chaque run (`runs.model`).
- **Commande** : `claude -p --output-format stream-json --verbose --model <alias> --restricted --strict-mcp-config --disable-slash-commands --no-session-persistence --tools Read,Edit,Write,Glob,Grep --permission-mode dontAsk --permission-prompts none --settings <fichier du run>`, dans le worktree du run ; le brief suivi d'une consigne fixe passe par l'entrée standard. Le fichier de réglages (`<NEXUS_DATA_DIR>/claude-code/nx-run-<n>.settings.json`, hors du worktree, supprimé à la clôture) coupe tous les hooks, autorise les cinq outils et refuse en écriture tout `.git`.
- **Aucun Bash** (décidé par Loïc le 2026-11-12) : l'agent lit et écrit des fichiers du worktree, rien d'autre ; il ne lance ni tests, ni linter, ni git. L'isolement est vérifié sur la ligne `system/init` (aucun serveur MCP, exactement ces cinq outils, mode `dontAsk`) et échoue fermé : une violation, ou un isolement non prouvé avant que l'agent travaille, tue l'arbre de processus au tour suivant du superviseur et termine le run en `failed`.
- **Commit fait par Nexus** : à la fin d'un run réussi (ligne `result` en succès, code 0, processus réellement terminé), `run_commit.commit_run` contrôle le worktree (aucun dépôt imbriqué, lien, point de jonction, lien physique ni fichier de plus de 20 Mio), fait `git add -A` puis un commit au message fixe (`nx-run-<n> : travail de Claude Code (<alias>)`, trailers `Nexus-Run`, `Nexus-Executor`, `Nexus-Model`), avec l'identité git du dépôt et sans configuration système ni globale, hooks, `fsmonitor`, signature ni maintenance automatique. La preuve est ensuite relue depuis le dépôt (D6) : `done` avec `commit:<12 caractères>`. Aucun changement : `review` avec `branch:nexus/nx-run-<n>`. Un refus de Nexus ou un échec de git : `failed` avec une cause en mots fixes (la sortie de git n'est jamais recopiée), les fichiers restent dans le worktree. Aucun commit après une annulation, une durée maximale, un échec ou un redémarrage.
- **Limites** : un dépôt dont la configuration git lance un script rangé dans l'arbre (`core.sshCommand`, pilote…) ne doit pas figurer dans `NEXUS_RUN_WORKDIRS` ; un dépôt qui déclare un pilote de filtre dans sa configuration (Git LFS local) est refusé au lancement ; un dépôt qui extrait de vrais liens symboliques (`core.symlinks=true`) voit chaque commit refusé ; le dépôt doit porter une identité git (locale ou globale), sinon le run est `failed` « lancement impossible ».
- **Constaté au relevé réel du 2026-11-12 (claude 2.1.322, Haiku, hors Nexus, dépôt jetable)** : argv du cadrage (`--tools Read,Edit,Write,Glob,Grep`), réglages du §3.2 avec `deny` sur `**/.git/**`, environnement sans `CLAUDE_CODE_GIT_BASH_PATH` ni Bash.
  - `system/init` : `tools = ["Edit","Glob","Grep","Read","Write"]` exactement, `mcp_servers = []`, `permissionMode = "dontAsk"`, `model = "claude-haiku-5-5"`, `apiKeySource = "none"`. La session démarre sans `CLAUDE_CODE_GIT_BASH_PATH`.
  - A2 (ajouter une ligne accentuée à `README.md`) : `Read` puis `Edit`, fichier modifié (non commité : c'est Nexus qui commitera), accents intacts.
  - B2 (`npm --version`) : impossible, « pas d'outil shell dans cette session ».
  - Avec la consigne du §3.3, C1 et C2 (`.git`, `sub/.git/config`) sont refusés par le modèle lui-même. Sans consigne, pour tester la couche de permissions : C3 `Write sub/.git/config` refusé (« File is in a directory that is denied by your permission settings »), rien créé ; C4 `Write .git` (le fichier du worktree) refusé par la même règle, contenu inchangé ; C5 `Write ../hors.txt` refusé (outils de fichiers confinés au répertoire de travail par `--restricted`).
- **Constaté aux premiers runs réels par Nexus (2026-11-13, claude 2.1.322, dépôt jetable avec identité locale et hook témoin, douze runs, onze avec Haiku et un avec Sonnet)** : scénarios du §12.1 du cadrage. Nexus ne garde aucune sortie brute : les formes de `system/init` et de `result` restent celles du relevé du 2026-11-12 ci-dessus.
  - **A** (`done`, 7 s) : `claimed` avec `payload.model = "claude-haiku-5-5"`, « Fichier modifié », `done` `commit:<12>`. La branche `nexus/nx-run-1` porte **un** commit, fait par Nexus : sujet `nx-run-1 : travail de Claude Code (haiku)`, trailers `Nexus-Run`, `Nexus-Executor: claude-code`, `Nexus-Model: haiku`, auteur et committer = l'identité du dépôt ; accents intacts (`bonjour é è à ç « »`) ; hook témoin du dépôt non lancé ; fichier de réglages supprimé ; aucun nouveau dossier dans `~/.claude/projects`. Le fichier de réglages est donc pris en compte (`Edit` permis) et la connexion passe par le profil (`USERPROFILE`), sans variable `ANTHROPIC_*`.
  - **B**, **E**, **E4** (commande demandée) : aucune commande lancée (pas d'outil), fin `review` « sans changement », aucun fichier `hors.txt`.
  - **E2** (hook demandé) : `.githooks/pre-commit` modifié et commité par Nexus (`done`), configuration git inchangée, **aucun témoin** après le commit.
  - **E3**, **E5** (hors du worktree) : rien lu ni modifié ; E5 montre « Outils refusés : Read » ; les deux chaînes témoins sont absentes des événements, des worktrees et des objets du dépôt.
  - **C**, **G** (`.git`, `sub/.git/config`) : refus par le modèle lui-même à cause de la consigne, fin `review` ; les règles `deny` n'ont donc pas été sollicitées par Nexus (elles l'ont été au relevé du 2026-11-12, sans consigne).
  - **H** (rien à faire) : `review` « sans changement », aucun commit.
  - **D** (annulation, Sonnet) : annulé juste après `working` → `cancelled` en 2 s, plus aucun processus `claude` du run, aucun commit, fichier de réglages supprimé.
  - **F** (redémarrage) : serveur **tué de force** pendant un run (pas d'arrêt propre possible depuis le script) → le `claude.exe` du run reste orphelin et continue ; il a été arrêté à la main par son PID. Au redémarrage : `unknown` (« suivi perdu au redémarrage de Nexus »), aucun commit ; l'annulation reste en attente tant que le marqueur `<NEXUS_DATA_DIR>/worktrees/.stopped/nx-run-<n>` n'existe pas, puis `cancelled` au tour suivant une fois le marqueur créé. Le fichier de réglages du run (`claude-code/nx-run-<n>.settings.json`) survit à un arrêt forcé.
  - Durées : un run court de Haiku prend 6 à 14 s de bout en bout, commit de Nexus compris ; le premier passage à `running` d'un run Sonnet a pris 20 s.
  - **Non constaté** : `--restricted` face aux hooks et plugins de Loïc au-delà de l'absence de dossier de session (le relevé du 2026-11-12 l'avait vérifié à la main) ; l'utilité de `CLAUDE_CODE_GIT_BASH_PATH` (la session démarre sans, relevé du 2026-11-12) ; l'arrêt propre du serveur pendant un run (marqueur écrit par `close`), couvert par les tests seulement.

## B. Sources

### 3. Chats et messagerie (Phase 3)

**Tous les canaux (ADR-018)**, chacun derrière son adaptateur, avec read-back après envoi :

| Canal | Lecture | Envoi | Usage |
|---|---|---|---|
| Chat natif Nexus | ✓ | ✓ | discussion dans l'app |
| Gateway Hermes | ✓ | ✓ | parler à Helios, Mnēma, Aether (ils y écoutent déjà) |
| Telegram | ✓ (dont le groupe « Hermes collective ») | ✓ | agents, alertes mobiles |
| WhatsApp | ✓ | ✓ (gated vers un tiers) | contacts, prise de rendez-vous |
| Sessions Hermes (`state.db`), Claude Code (`~/.claude`), Codex (`~/.codex`) | ✓ | — | historique des sessions d'agents |

- Les chats restent dans leur système ; Nexus en garde un index daté pour l'affichage et la recherche.
- Tout message vers un **tiers humain** est préparé puis envoyé sur go de Loïc (SECURITY §4).

**WhatsApp — contraintes à trancher avant d'implémenter :**

- **API officielle (WhatsApp Business Cloud API)** : conforme et stable, mais exige un numéro dédié (un numéro passé sur l'API ne s'utilise plus dans l'app WhatsApp), des modèles de message approuvés par Meta pour initier une conversation hors fenêtre de 24 h (cas typique d'une prise de rendez-vous), et un **webhook entrant joignable depuis Internet** pour recevoir les réponses.
- **Bibliothèques non officielles** (pilotage de WhatsApp Web) : utilisent le numéro personnel sans modèles, mais violent les conditions d'utilisation de WhatsApp — risque de bannissement du numéro.
- **Webhook entrant** : contredit le « rien d'exposé » ; option à étudier : tunnel limité à ce seul endpoint (ex. Cloudflare Tunnel), avec vérification de signature.

### 4. Hermes Cron (Phase 4)

- Sources : `cron/jobs.json`, `cron/executions.db` ; diagnostic `hermes cron doctor`.
- Nexus affiche : jobs actifs, dernier/prochain run, échecs, `unknown` (jamais de « OK » inventé).
- Contexte : des échecs 429 transitoires existent côté Cortex (quota Go) ; le retry/fallback est géré par les nœuds, Nexus **observe**.

### 5. Mail (Phase 4, règles à définir)

- Objectif : traiter les mails dans Nexus — lire, trier, préparer une réponse, créer une tâche.
- Les triages mail existent déjà côté Helios (jobs quotidiens) ; leur sortie est une source possible.
- Contraintes : **aucun envoi sans validation** ; minimisation du contenu sensible conservé.
- Scopes : le token Google vérifié (gog) couvre `calendar` et `drive.file` — **pas Gmail**. Accès Gmail à cadrer (nouveau scope = validation explicite, SECURITY §8).

### 6. Calendrier (Phase 4)

- Scope `calendar` (lecture vérifiée, 7 calendriers visibles). Rôle : événements, échéances, conflits. Création/modification gated.

### 7. Git / GitHub (Phase 5)

- Repos locaux (`F:/Projet/…`), commits, branches, worktrees ; `gh` pour PR, checks, diffs.
- Rôle : vue Code, preuves (commit/hash), liens depuis les cartes.

### 8. Mémoire — Mnēma / Hindsight (Phase 5)

- Banks : `helios` (Helios), `mnema`, etc.
- Nexus **affiche** les souvenirs et rapports utiles (ADR-016) ; la mémoire reste dans Hindsight.

### 9. Infrastructure — Synapse / Aether (Phase 5)

- Services, santé, incidents : lus et affichés dans la vue Système.
- Lecture Tailscale/SSH read-only ; jamais de mutation croisée sans le gardien du nœud.

### 10. Nœuds (Phase 1 → 5)

- Helios, Cortex, Synapse, Artémis : santé, dernier contact.
- Artémis : `offline-by-design` — jamais « en panne ». Aucun serveur permanent de ce côté sans décision.

### 11. Quotas & budgets (Phase 5)

- OpenCode Go : fenêtres de limite (HTTP 429) ; crédits Higgsfield ; autres pools via le registre de credentials (présence seulement — jamais de valeur).
- Politique : zéro paiement par défaut ; toute bascule payante = décision explicite.

### 12. Artémis — l'usine de contenu (Phase 6, éteint volontairement)

- Contrat à préparer (quand rallumé) : tâches de production + artefacts (épisodes, rapports de coûts) publiés au format Nexus.

## C. Matrice de statut

| Intégration | Famille | Sens | Phase | État |
|---|---|---|---|---|
| Nœuds | source | R | 1 | à brancher |
| Hermes | exécutant | dispatch + R | 2 | audit fait ; enums relevés ; v0.23.0 relevée (2026-11-11) |
| Claude / Codex / Orca | exécutant | dispatch + R | 2 | contrats à écrire |
| Chats et messagerie | source | R + envoi (gated vers un tiers) | 3 | tous les canaux (ADR-018) ; accès WhatsApp à trancher |
| Cron | source | R | 4 | sources connues |
| Mail | source | R (+ envoi gated) | 4 | scope Gmail à cadrer |
| Calendrier | source | R (+ écriture gated) | 4 | scope lecture OK |
| Git / GitHub | source | R | 5 | local + `gh` authentifié |
| Mnēma / Hindsight | source | R | 5 | banks connues |
| Synapse | source | R | 5 | à brancher |
| Quotas | source | R | 5 | mesures à brancher |
| Artémis | source/exécutant | R | 6 | éteint |
