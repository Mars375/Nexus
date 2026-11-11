# Adaptateur `hermes` — cadrage du lot G (ADR-023)

**Date :** 2026-11-11
**Issue :** #179 (Phase 2, lot G)
**Entrées :** relevé de Hermes Kanban 0.23.0 (`docs/notes/2026-11-11-releve-hermes-0-23.md`, PR #178), relevé des enums (`docs/notes/2026-09-28-releve-enums-hermes-kanban.md`), ADR-023 (D1–D8), INTEGRATIONS §A.1–A.2, DATA-MODEL §2.5, SECURITY §3, adaptateur Codex (`server/src/nexus/adapters/codex*.py`).
**Lecture complémentaire faite pour ce cadrage (lecture seule, aucune écriture dans Hermes) :** `hermes_cli/kanban.py`, `kanban_parser.py`, `kanban_output.py`, `kanban_db.py` (`create_task`, `archive_task`, `list_events`, artefacts de fin), `kanban_db_dispatch.py` (disjoncteur, `timed_out`, `review_dispatch`, arrêt du worker), `hermes_cli/stdio.py` ; `hermes kanban boards list --json`, `hermes kanban assignees --json`, `hermes profile list`.
**`CONTEXT.md` :** absent à la racine du dépôt ; les décisions viennent de `DECISIONS.md`.

Ce document fixe ce qu'un `implementer` écrit, tests d'abord. Il ne s'écarte d'ADR-023 sur aucun point ; une seule décision d'ADR-023 (D7) demande que Loïc confirme une politique avant l'adaptateur (§11).

---

## 0. Ce que la lecture du code de Hermes a changé par rapport au relevé

1. **Le profil de Helios s'appelle `default` pour Kanban.** `hermes profile list` affiche « Helios (default) », mais `hermes kanban assignees --json` ne connaît que `default` : c'est le profil par défaut, nommé Helios à l'affichage. `--assignee helios` assignerait la tâche à un profil inexistant : le dispatcher la classe alors en `skipped_nonspawnable` (`kanban_db_dispatch._profile_exists_fn`) et ne la lance jamais. L'agent Nexus `helios` correspond donc au profil Hermes `default` (réglable, §1).
2. **Un tableau inconnu est une erreur, jamais une création.** `hermes kanban --board <slug> …` répond `board '<slug>' does not exist` (code 1) si le tableau n'existe pas. Les sous-commandes `boards …` ignorent `--board`.
3. **Les événements de `show --json` n'ont pas d'identifiant** (`kind`, `payload`, `created_at`, `run_id`), triés par `created_at ASC, id ASC`. Aucune commande non interactive ne donne l'id (`tail` et `watch` sont des flux texte sans fin). Le curseur se fonde donc sur la **position** dans la liste (§4.2).
4. **`created_at` est un entier (secondes Unix)**, pour les tâches comme pour les événements.
5. **L'id d'une tâche est `t_` + 8 caractères hexadécimaux** (`secrets.token_hex(4)`).
6. **`--idempotency-key` ne protège que contre les tâches non archivées**, et la vérification se fait hors du verrou d'écriture (deux `create` simultanés peuvent insérer deux fois). Une tâche archivée ne bloque pas une nouvelle création avec la même clé.
7. **`list --json` ne renvoie pas `idempotency_key`.** Retrouver une tâche sans son id passe par son titre (§3.1).
8. **`review_dispatch` est un réglage global de Hermes** (pas par tableau), vrai par défaut et vrai chez Helios : une tâche passée en `review` lance un relecteur Hermes, qui la termine (`done`) ou demande des changements (retour en `ready`, nouveau worker).
9. **Le disjoncteur bloque sans événement `blocked`.** Avec `--max-retries 1`, le premier échec (`crashed`, `timed_out`, `spawn_failed` non dû à l'infrastructure) passe la tâche en `blocked` et écrit un événement `gave_up`. Le statut `blocked` couvre donc deux cas que seuls les événements distinguent : le worker demande quelque chose (`blocked`) ou Hermes abandonne (`gave_up`).
10. **`archive` arrête le worker** (TerminateProcess sous Windows, puis attente de 5 s) et écrit `archive_worker_termination` avec `terminated: true|false`. Archiver une tâche déjà archivée répond `cannot archive` (code 1). `archive` nettoie l'espace `scratch`.
11. **Les livrables déclarés à la fin sont recopiés par Hermes.** `kanban_complete` avec `metadata.artifacts` copie chaque fichier de l'espace `scratch` dans le dossier des pièces jointes de la tâche, enregistre une pièce jointe (`uploaded_by = "kanban_complete"`, `stored_path`, `size`) et réécrit `metadata.artifacts` avec les chemins recopiés. `request_review` fait de même avec `uploaded_by = "kanban_request_review"` (quand le worker passe par la relecture Hermes, ses livrables sont recopiés à ce moment-là). `hermes kanban --board nexus attachments <id> --json` les liste. C'est la seule trace que Nexus peut relire sans supposer (§4.4).
12. **Encodage :** sous Windows, l'entrée de `hermes` passe par `configure_windows_stdio()` (UTF-8 pour stdin, stdout et stderr) ; l'adaptateur force quand même `PYTHONUTF8=1` dans l'environnement de l'enfant (§7.2), et le run réel vérifie un brief accentué (§9).
13. **Coût d'un appel :** environ 2 s par commande `hermes` (démarrage de Python). Le suivi est donc espacé (§4.1).
14. **`hermes kanban gc`** efface les événements de plus de 30 jours des tâches terminées : sans effet sur un run suivi (durée maximale de 60 min par défaut), mais à garder en tête pour le curseur (§4.2).

---

## 1. Configuration et enregistrement

**Décision.** L'adaptateur `hermes` est **opt-in** : il n'est enregistré que si `NEXUS_HERMES_BIN` est défini, que la sonde réussit et que le tableau `nexus` existe avec le profil voulu.

| Réglage | Valeur | Contrôle |
|---|---|---|
| `NEXUS_HERMES_BIN` | chemin ou nom du binaire (`hermes` est résolu par `shutil.which`). **Sans valeur, aucun repli sur le `PATH`** : `hermes` est installé sur cette machine et la suite de tests (hook pre-commit) crée des applications ; elle ne doit jamais atteindre le vrai Hermes. | absent ou introuvable : rien n'est enregistré |
| `NEXUS_HERMES_PROFILE` | profil Hermes qui travaille pour l'agent `helios` ; défaut `default` (§0.1) | `[a-z0-9][a-z0-9_-]{0,63}`, sinon `ValueError` au démarrage (message sans la valeur reçue, ADR-006) |
| tableau | constante `BOARD = "nexus"` dans le code, **non réglable** (ADR-023 D7 : « un board `nexus` créé par Loïc ») | — |
| `NEXUS_RUN_MAX_MINUTES` | partagé avec Codex (60 par défaut) : durée maximale d'un run (§4.5) | déjà validé par `Settings` |

- `Settings` reçoit `hermes_bin: str | None = None` et `hermes_profile: str = "default"` ; `from_env` lit les deux variables.
- `app.py` appelle `hermes.register_configured(app.state.adapters, settings)` juste après celui de Codex.
- `register_configured` : `NEXUS_HERMES_BIN` absent → `False` ; `shutil.which` échoue → `False` ; sinon construit `HermesAdapter(found, profile, settings.data_dir, max_seconds=run_max_minutes * 60)`, appelle `probe()`, enregistre sous l'exécutant `hermes` si elle réussit. En cas d'échec, une ligne de journal **sans valeur reçue** dit quoi faire : « adaptateur hermes non enregistré : tableau `nexus` ou profil absent (voir INTEGRATIONS §A.1) ».
- **Sonde (`probe`)** : un seul appel, `hermes kanban --board nexus assignees --json` (délai 30 s). Elle réussit si le code est 0, si la sortie est une liste JSON et si une entrée a `name == profil` et `on_disk == true`. Un appel vérifie ainsi le binaire, l'existence du tableau (§0.2) et le profil, sans lancer de modèle ni écrire.

### Agents servis

- `AGENTS_OF["hermes"]` reste `{helios, mnema, aether}` (ce qui est admis en principe, DATA-MODEL §2.5).
- L'adaptateur expose `agents = frozenset({"helios"})` : seul Helios est dans le périmètre (Mnēma et Aether vivent sur d'autres nœuds, que la CLI locale n'atteint pas).
- `runs/rules.check_dispatchable` : après le contrôle `registry.get(executor)`, si l'adaptateur a un attribut `agents` et que l'agent n'y est pas → **409 `executor_unavailable`** (« aucun adaptateur n'est configuré pour cet agent : rien n'est lancé »). Confier à Mnēma via Hermes est refusé **avant** de créer le run, jamais un run `failed`.
- `GET /api/executors` renvoie pour chaque exécutant `sorted(AGENTS_OF[name] & adapter.agents)` quand l'adaptateur a `agents`, sinon `AGENTS_OF[name]` comme aujourd'hui ; `workdirs` vaut `[]` pour Hermes (§3.4).

**Rejetés :** repli sur le `PATH` comme Codex (atteindrait le vrai Hermes depuis les tests) ; tableau réglable (rien ne le demande, et D7 nomme `nexus`) ; correspondance `helios → helios` (profil inexistant, §0.1) ; restreindre `AGENTS_OF` lui-même (changerait le modèle de données pour une limite de déploiement).

---

## 2. Création du tableau `nexus`

**Décision.** Loïc crée le tableau **une fois, à la main** ; l'adaptateur ne le crée jamais, ni à la sonde ni au dispatch, et ne change jamais le tableau courant.

```text
hermes kanban boards create nexus --name Nexus
```

- Sans `--switch` ; puis `hermes kanban boards show` doit toujours répondre `default`.
- Le dispatcher intégré à la passerelle de Helios prend le nouveau tableau au tour suivant (relevé, §Tableaux).
- Chaque appel de l'adaptateur porte `--board nexus` ; aucune commande `boards switch|use|create|rm` n'est jamais construite par Nexus (test d'argv, §8).
- Sans tableau, la sonde échoue, l'adaptateur n'est pas enregistré et « Confier à Helios » reste un 409 `executor_unavailable`. Un tableau supprimé après le démarrage fait échouer le `create` (deux refus, §3.2) : le run finit `failed`, « lancement impossible ».

**Rejetés :** création idempotente dans la sonde (écrit dans Hermes sans action de Loïc, contraire à D7) ; création au premier dispatch (même raison, et une création ratée laisserait un tableau à moitié prêt).

---

## 3. `dispatch`

### 3.1 Commande

Une liste d'arguments, jamais un shell, avec le brief sur l'entrée standard (D4) :

```text
<bin> kanban --board nexus create "Nexus nx-run-<n> nx-task-<m>"
      --body-file -
      --assignee <profil>
      --idempotency-key nx-run-<n>
      --max-runtime <max_seconds>
      --max-retries 1
      --workspace scratch
      --created-by nexus
      --json
```

- **Titre** : `Nexus nx-run-<n> nx-task-<m>`, ASCII, construit uniquement à partir de `run.ref` et `run.task` (validés par `^nx-run-[0-9]{1,12}$` et `^nx-task-[0-9]{1,12}$`). Rien du brief n'entre dans l'argv : le titre est un argument positionnel, visible dans la liste des processus. Le titre sert aussi à retrouver la tâche sans son id (§3.3, §5).
- **Corps (stdin)** : le brief tel qu'enregistré (déjà masqué par le scanner à la création du run), suivi d'une consigne fixe de Nexus, sans jeton ni URL :

  ```text
  ---
  Consigne de Nexus : quand le travail est fini, termine la tâche avec kanban_complete.
  Mets un résumé dans summary et, si tu produis des fichiers, liste leurs chemins absolus
  dans metadata.artifacts : Hermes les conserve et Nexus les relit comme preuve.
  Sans livrable, Nexus demandera une relecture à Loïc.
  ```

  La consigne est un texte constant de Nexus, pas un champ d'agent : elle respecte D4 (« le brief ne reprend que les champs écrits par Loïc »). Elle rend la preuve atteignable (§4.4).
- `--max-runtime <secondes>` = `max_seconds` (entier) ; `--max-retries 1` (§6.1) ; `--workspace scratch` (§3.4) ; `--created-by nexus` (repère des tâches de Nexus sur le tableau).
- Ni `--triage`, ni `--initial-status`, ni `--goal`, ni `--skill`, ni `--model` : la tâche est créée prête (D7, « tâches posées directement en `ready` »), avec le modèle du profil.
- `cwd` du processus : `settings.data_dir` (existe toujours) ; délai `CLI_TIMEOUT = 30 s`.

### 3.2 Lecture de la réponse et rejeu idempotent

Réponse valide : code 0 et un objet JSON avec `id` conforme à `^t_[0-9a-f]{8}$`, `status` dans les statuts connus, `assignee == profil`, `title ==` titre attendu. Alors `Dispatched(external_ref=id, native_status=status)`.

**`external_ref` = l'id Hermes nu** (`t_9f3a01bc`) : le tableau est fixe, et l'id passe tel quel dans l'argv des commandes suivantes après validation. L'exemple de DATA-MODEL §2.5 (`hermes:default#t_abcd`) est mis à jour dans la PR.

Échecs possibles d'un essai : **délai dépassé** (l'arbre du processus est tué par `codex_process.kill_tree`, réutilisé), **sortie illisible** (code 0 mais JSON invalide ou champs non conformes), **refus** (code ≠ 0).

| Essai 1 | Essai 2 (même clé `nx-run-<n>`) | Résultat |
|---|---|---|
| valide | — | `Dispatched` |
| échec quelconque, arbre tué et arrêt confirmé | valide | `Dispatched` (la clé renvoie la tâche créée par l'essai 1, ou la crée) |
| refus | refus | `HermesRefused` (exception ordinaire) → le superviseur publie `failed` « lancement impossible » |
| délai ou sortie illisible (l'un des deux essais) | échec | `LaunchUncertain` (§3.3) |
| délai, arrêt **non** confirmé | — (pas de second essai) | `LaunchUncertain` |

- Le second essai n'a lieu qu'une fois l'arbre du premier tué et son arrêt confirmé : la clé est vérifiée hors du verrou d'écriture de Hermes (§0.6), deux `create` simultanés pourraient insérer deux tâches.
- Deux refus garantissent qu'aucune tâche n'est vivante : si l'essai 1 avait inséré la tâche avant d'échouer, l'essai 2 l'aurait trouvée par sa clé et renvoyée (code 0). C'est ce qui permet de lever une exception ordinaire, que le superviseur traite comme « rien n'a été lancé » (l'exécutant est libéré).
- `run.workdir` non vide → `ValueError` avant tout appel (run `failed`, « lancement impossible ») : Hermes travaille en `scratch` (§3.4). L'interface ne propose aucun dossier, puisque `workdirs` est vide.
- `run.agent != "helios"` → `ValueError` (défense en profondeur ; les règles l'ont déjà refusé en 409).

### 3.3 Lancement incertain (nouveau, dans le superviseur)

Aujourd'hui une exception de `dispatch` fait toujours `failed` et libère l'exécutant. Pour Hermes, une tâche peut exister alors que l'adaptateur n'a pas pu le confirmer. **Décision :** `adapters/base.py` définit `class LaunchUncertain(Exception)` ; `supervisor._dispatch` l'intercepte **avant** le `except Exception` générique et fait exactement ce que fait déjà le chemin « lancement incertain » de `_step` : événement `unknown` « lancement incertain » (id `nx-run-<n>-uncertain`, `last_check_at`), statut `unknown`, marqueur `native_status = "dispatching"` conservé. Le run retient l'exécutant jusqu'à ce que Loïc l'annule ; l'annulation retrouve la tâche par son titre (§5).

C'est la sémantique de D3 et de #168 (« ne jamais répéter un lancement dont l'issue est incertaine »), étendue à un dispatch qui échoue sans savoir ; pas un écart à ADR-023.

### 3.4 Espace de travail

**Décision : `scratch`.** Hermes crée un dossier jetable par tâche et le supprime à la fin ; les livrables déclarés sont recopiés avant (§0.11).

**Rejetés :** `worktree` (le nettoyage et la politique de branches sont ceux de Hermes ; une preuve git façon D6 demanderait un commit de départ relu par Nexus : un lot ultérieur si Loïc confie du code à Helios) ; `dir:<NEXUS_RUN_WORKDIRS>` (Helios écrirait directement dans les dépôts de Loïc, sans isolement ; `archive` ne nettoie jamais un `dir`).

---

## 4. `watch`

### 4.1 Lecture

- `hermes kanban --board nexus show <external_ref> --json`, délai 30 s, `external_ref` validé par `^t_[0-9a-f]{8}$` **avant** de lancer quoi que ce soit (sinon `ValueError`, rien n'est appelé).
- **Espacement :** au plus une lecture toutes les `WATCH_SECONDS = 10` s par run (dernière lecture gardée en mémoire, par `run.ref`). Entre deux, `watch` renvoie `WatchResult()` vide : le superviseur n'écrit alors ni curseur ni statut (`update_run` ignore les `None`). Après un redémarrage la mémoire est vide : une lecture a lieu tout de suite, sans effet sur la justesse.
- Code ≠ 0 avec un stderr qui commence par `no such task` → la tâche a disparu (supprimée par `archive --rm`) : fait de clôture `failed` « tâche Hermes introuvable », `seq = SEQ_MISSING` (§4.2). stderr est lu borné (4 Kio), jamais journalisé ni stocké ; seul ce préfixe fixe est comparé (à reconfirmer à chaque version de Hermes).
- Autre code ≠ 0, délai dépassé, JSON illisible ou forme inattendue (`task` qui n'est pas un objet, `events` qui n'est pas une liste) → exception `HermesUnavailable` : le superviseur journalise le type et réessaie au tour suivant, run et curseur inchangés.
- Sortie de plus de 4 Mio → traitée comme illisible.
- Toute la traduction est une **fonction pure** `translate(show: dict, after: int, *, proofs: list[str], now: datetime, max_seconds: float) -> Translation` dans `hermes_translate.py`, testée sur des fixtures JSON. Les seules lectures impures (pièces jointes et disque, §4.4 ; archivage, §4.5) sont faites par l'adaptateur et passées en argument.

### 4.2 Curseur et numérotation

- **`seq` d'un fait = position (à partir de 1) de l'événement Hermes qui le porte** dans la liste triée de `show --json`. Un événement Hermes donne au plus un fait Nexus. L'id publié est donc `nx-run-<n>-<position>` : relire le même événement est une relecture (D2).
- **Curseur = position du dernier événement Hermes consommé**, en décimal (`"0"` au départ). Un événement ignoré (type inconnu, `heartbeat`…) est consommé aussi : le curseur avance au-delà.
- Un curseur illisible (non entier, négatif) vaut 0 : tout est relu, les ids stables font de chaque fait déjà publié une relecture.
- **Une clôture scelle** : les événements qui la suivent dans la même lecture ne sont pas traduits, et le curseur s'arrête sur la position de la clôture.
- Faits sans événement Hermes, à `seq` réservés hors de la plage des positions : `SEQ_WATCHDOG = 1_000_000` (durée maximale, §4.5) et `SEQ_MISSING = 1_000_001` (tâche introuvable). Chacun clôt le run : il n'est publié qu'une fois.
- `at` = `created_at` de l'événement Hermes converti en UTC (`datetime.fromtimestamp(x, timezone.utc)`), jamais l'horloge de Nexus ; pour les faits réservés, `now()`.
- **Limite connue :** la position n'est stable que si Hermes n'insère jamais un événement avant un autre déjà lu. Le tri `created_at ASC, id ASC` sur des secondes entières le garantit tant que l'horloge ne recule pas, et `gc` ne touche qu'aux tâches terminées. Si l'ordre change malgré tout, un id déjà pris avec un autre contenu est refusé par `publish`, le superviseur ne déplace pas le curseur (`refusals`), et la durée maximale finit par clore le run en `failed` : rien n'est dupliqué ni perdu en silence. **Rejeté :** lire `kanban.db` directement pour avoir les ids (schéma interne de Hermes, verrous WAL, migrations à chaque version).

### 4.3 Table de traduction

Événements Hermes (`events[i].kind`), dans l'ordre :

| Événement Hermes | Fait Nexus | Détail |
|---|---|---|
| `claimed` (premier seulement) | `claimed` « Helios a pris la tâche (Hermes) » | les suivants sont ignorés |
| `spawned` (premier) | `working` « Helios travaille » | fait passer le run en `running` |
| `spawned` (suivants) | `progress` « nouvelle tentative de Hermes » | après un `changes_requested` |
| `review_requested` | `progress` « relecture Hermes en cours » | **pas** une clôture (§6.2) |
| `changes_requested` | `progress` « le relecteur Hermes demande des changements » | corps : raison coupée |
| `timed_out`, `crashed`, `stale`, `spawn_failed`, `reclaimed`, `worker_lost` | `progress` « tentative interrompue (<kind>) » | corps : `error` coupée ; la fin vient de `gave_up` si le disjoncteur saute |
| `completion_blocked_hallucination`, `completion_blocked_empty_result` | `progress` « Hermes a refusé la fin annoncée » | |
| `completed` | **clôture** `done` ou `review` | `complete_task` fait toujours passer la tâche en `done` (depuis `running`, `ready`, `blocked` ou `review`) ; jugée sur le run `run_id` de l'événement et sur les preuves (§4.4) |
| `blocked` | **clôture** `blocked` | `payload.cause` = raison du blocage coupée, ou « Helios a bloqué la tâche sans dire pourquoi » ; `payload.plan` = « Nexus ne suit plus cette tâche Hermes : réponds dans un nouveau brief et confie la tâche à nouveau, ou abandonne-la » |
| `gave_up` | **clôture** `failed` | `cause` = « Hermes a abandonné après un échec (<trigger_outcome>) : <error coupée> » |
| `archived` | **clôture** `failed` | `cause` = « tâche archivée dans Hermes, hors de Nexus » (une annulation de Nexus ne passe pas par `watch`, §5) |
| tout autre type (`created`, `assigned`, `promoted`, `heartbeat`, `commented`, `edited`, `linked`, `archive_worker_termination`… et tout type inconnu) | rien | consommé par le curseur ; **un type inconnu n'est jamais une erreur** |

- Un champ manquant ou d'un mauvais type dans un événement (kind non textuel, `created_at` non entier, `payload` non objet) : l'événement est consommé sans fait, jamais une exception.
- Le texte venant de Hermes (raison, `error`, `summary`) passe par `cut()` : chaîne réparée (`encode("utf-8", "replace")`), secrets masqués sur le texte entier **puis** coupé à 500 caractères ; s'il ne reste rien, le texte de repli fixe est utilisé (un `blocked` sans cause ou un `failed` sans cause serait refusé par `publish` et gèlerait le curseur). `cut()` est déplacée de `codex_translate.py` vers `adapters/text.py` (déplacement sans changement de comportement, tests Codex inchangés).
- Le sujet de chaque fait est un texte fixe de Nexus (≤ 500 caractères).

**`native_status`** = `task.status`, suivi de `/<outcome>` du dernier run s'il en a un (ex. `running`, `blocked/gave_up`, `done/completed`), coupé à 64 caractères par `update_run`.

**`Run.status`** suit les faits publiés (`STATUS_OF_EVENT`, sans changement) : `dispatched` jusqu'au premier `spawned`, puis `running`, puis la clôture (`done`, `review`, `blocked`, `failed`).

### 4.4 Preuves (DONE ≠ preuve)

À la clôture `completed` uniquement, l'adaptateur lit `hermes kanban --board nexus attachments <id> --json` et retient comme preuve chaque pièce jointe qui remplit **toutes** ces conditions :

- `uploaded_by` vaut `"kanban_complete"` ou `"kanban_request_review"` (copie faite par Hermes à la fin ou à la demande de relecture, §0.11 ; une pièce jointe ajoutée par `attach` ne compte pas) ;
- `stored_path` absolu, local (ni `\\serveur\…`, ni `\\?\…`), de 400 caractères au plus ;
- le fichier existe, est un fichier ordinaire, et sa taille égale `size` (un `stat`, jamais une lecture du contenu).

Chaque preuve devient `file:<stored_path>` (au plus 10). Si au moins une preuve est retenue : fait `done`, `evidence = [file:…, "hermes:nexus/<id>"]`. Sinon : fait `review`, `evidence = ["hermes:nexus/<id>"]`, corps « Hermes a terminé sans livrable relu : à relire » suivi du `summary` du run coupé.

- `hermes:nexus/<id>` n'est jamais une preuve suffisante à elle seule : elle dit où relire.
- `metadata.changed_files` (liste de chaînes, 20 au plus, chacune coupée) et `metadata.tests_run` (entier) vont dans `payload`, à titre d'information : en `scratch`, ces fichiers ont disparu et un nombre de tests ne se relit pas.
- Un chemin de `metadata.artifacts` qui n'a pas été recopié (hors de l'espace `scratch`) n'est pas une pièce jointe : il n'est pas retenu.
- Un `commit` déclaré n'est pas une preuve dans ce lot (rien ne le rattache à un commit de départ, D6) ; il va dans `payload` coupé à 12 caractères (un hash de 40 caractères serait masqué par le scanner).
- Le scanner a été essayé sur `t_9f3a01bc`, `hermes:nexus/t_9f3a01bc` et `file:C:\Users\…\kanban\boards\nexus\attachments\t_…\rapport.pdf` : rien n'est masqué, aucune référence n'est vide.
- Une erreur de la lecture des pièces jointes → `HermesUnavailable` : la clôture n'est pas émise, tout est relu au tour suivant (jamais un `review` faute d'avoir pu lire).

### 4.5 Durée maximale (D7)

`RunInfo` n'a pas d'horodatage : l'horloge vient de Hermes. Après la traduction, si aucune clôture n'a été trouvée et que `now - task.created_at > max_seconds + GRACE_SECONDS` (`GRACE_SECONDS = 120` : un tour du dispatcher et une marge), l'adaptateur **archive** la tâche (§5, arrêt confirmé), puis émet la clôture `failed` à `SEQ_WATCHDOG` :

- tâche encore `triage`/`todo`/`ready`/`scheduled` : cause « Hermes n'a pas pris la tâche dans le délai (passerelle arrêtée ?) » — couvre une passerelle de Helios éteinte ;
- sinon : cause « durée maximale dépassée (<N> min) : tâche Hermes archivée ».

Si l'archivage n'est pas confirmé, `watch` lève : rien n'est publié, l'essai recommence au tour suivant (l'exécutant reste retenu tant que le worker peut tourner, comme pour Codex). `--max-runtime` côté Hermes est une borne intérieure (il arrête le worker et, avec `--max-retries 1`, mène à `gave_up`) ; la borne de Nexus couvre en plus l'attente en `ready` et la boucle de relecture de Hermes.

**Limite connue :** l'horloge vient de `show` ; tant que la CLI de Hermes échoue (§4.1), le run reste `running` sans que Nexus puisse appliquer sa durée maximale (l'annulation, qui passe aussi par Hermes, attend de même). Le worker reste borné par `--max-runtime` côté Hermes. Noté dans INTEGRATIONS §A.1.

### 4.6 Fins non `done` : la tâche Hermes est archivée

Avant de rendre une clôture `blocked` ou `failed` venue de `blocked`, `gave_up` ou de la durée maximale, l'adaptateur archive la tâche Hermes (arrêt confirmé, §5) ; si l'archivage échoue, `watch` lève et rien n'est publié. Raison : le run Nexus est clos et l'exécutant libéré ; une tâche restée `blocked` que quelqu'un débloquerait dans Hermes travaillerait sans être suivie, à côté d'un nouveau run (contraire à « un run actif par exécutant », D7). Une tâche archivée reste lisible dans Hermes (`list --archived`, `show`). `done` et `review` (venue de `completed`) ne demandent rien : la tâche est déjà terminée chez Hermes.

---

## 5. `cancel`

Même contrat que Codex : **lever si l'arrêt n'est pas confirmé** ; le run reste alors ouvert et l'annulation est réessayée au tour suivant.

1. `external_ref` connu (validé par l'expression du §4.1) → étape 3 avec cet id.
2. `external_ref` absent :
   - `native_status != "dispatching"` → jamais lancé : retour immédiat, aucun appel à Hermes ;
   - sinon (lancement incertain, §3.3, ou plantage entre le `create` et l'écriture de la référence) → `hermes kanban --board nexus list --archived --assignee <profil> --json`, garder les tâches dont `title` est le titre du run et `created_by == "nexus"` ; aucune → retour (rien à arrêter) ; sinon étape 3 pour chacune.
3. `archive <id>` (le code de retour est ignoré : `cannot archive` veut aussi dire « déjà archivée »), puis `show <id> --json` :
   - `no such task` → confirmé ;
   - `task.status != "archived"` → lever ;
   - le dernier événement `archive_worker_termination`, s'il existe : `terminated == true` → confirmé ; `prev_pid` nul (tâche `running` réclamée mais worker pas encore lancé : `archive` écrit l'événement avec `terminated: false` alors qu'il n'y a rien à arrêter) → confirmé ; sinon (`terminated` faux avec un pid, `signal_refused`, `host_local` faux) → lever, **sauf** si le fichier vide `<NEXUS_DATA_DIR>/hermes/.stopped/nx-run-<n>` existe (Loïc a arrêté le worker à la main : même échappatoire que Codex, INTEGRATIONS §A.2) ;
   - sinon confirmé.

- Le chemin de #168 (référence non écrite après un `create` réussi) passe par l'étape 1 : le superviseur appelle déjà `adapter.cancel(replace(run, external_ref=sent.external_ref))`.
- Un run `unknown` après redémarrage (D3) s'annule avec une confirmation réelle, puisque Hermes garde la tâche : contrairement à Codex, il ne reste pas bloqué.
- Course résiduelle documentée : après un plantage de Nexus pendant un `create`, le processus `hermes` orphelin pourrait finir son insertion après la recherche par titre. Le redémarrage de Nexus (migrations, sauvegarde) dure plus longtemps qu'un `create` (≈ 2 s) ; le risque est accepté et noté dans INTEGRATIONS.
- `close()` (arrêt du serveur) : **ne fait rien**. Les tâches Hermes survivent à Nexus par nature ; les archiver à chaque arrêt du serveur interromprait le travail de Helios.
- `recover()` : renvoie `None` comme Codex ; ADR-023 D3 ne l'utilise pas (§6.4).

---

## 6. Questions ouvertes du relevé : décisions

### 6.1 `--max-runtime` remet en file au lieu d'échouer

`--max-retries 1` : le premier échec (dépassement, plantage, lancement raté) déclenche le disjoncteur, la tâche passe `blocked` avec `gave_up`, et Nexus la clôt `failed` (puis l'archive, §4.6). Aucune relance automatique (D7). Un `spawn_failed` marqué `infrastructure` ne déclenche pas le disjoncteur (Hermes réessaie lui-même) : la durée maximale de Nexus le borne.

### 6.2 `review_dispatch: true`

**Décision proposée (à confirmer par Loïc, D7) :** Nexus **laisse la relecture de Hermes se faire** et la traite comme une étape intérieure du run. Un `review` côté Hermes n'est **jamais** un `review` côté Nexus (qui est un état réglé, plus suivi) : il devient un `progress` « relecture Hermes en cours », et le run reste `running` jusqu'à `completed`, `blocked`, `gave_up`, `archived` ou la durée maximale. La relecture de Loïc reste celle de Nexus : un `done` sans livrable relu finit en `review` (§4.4).

**Rejetés :** désactiver `review_dispatch` (réglage global de Helios : changerait ses autres tableaux) ; traduire `review` Hermes en `review` Nexus (Nexus cesserait de suivre une tâche que Hermes continue de travailler) ; créer les tâches de façon à contourner la relecture (aucune option par tâche ne le permet en 0.23.0).

Ce que Loïc accepte en confirmant : un relecteur Hermes, puis éventuellement un nouveau worker après `changes_requested`, sont lancés sans nouveau clic, à l'intérieur du run qu'il a confié et dans sa durée maximale.

### 6.3 `done` sans `metadata`

Tranché au §4.4 : `review`, avec `hermes:nexus/<id>` pour relire et le résumé du run dans le corps.

### 6.4 Redémarrage de Nexus

**Décision pour ce lot : ADR-023 D3 s'applique sans changement.** Au démarrage, `mark_lost` passe tout run suivi en `unknown` ; Loïc l'annule (archivage confirmé, §5). L'adaptateur est néanmoins **sans état** : tout ce qu'il lit vient de `external_ref`, du curseur et de Hermes (la seule mémoire est l'espacement des lectures). Reprendre le suivi après un redémarrage ne demanderait donc qu'un changement du superviseur (`mark_lost` épargnerait les runs d'un adaptateur qui garde l'histoire, avec `recover`) : c'est le **seul écart possible à ADR-023**, hors de ce lot, à décider par Loïc (§11).

---

## 7. Concurrence, invariants, sécurité

### 7.1 Appels bornés

- Toute commande `hermes` passe par un seul exécuteur (`hermes_cli.call(argv, stdin, timeout)`) : `codex_process.spawn` (liste d'arguments, sans shell, groupe de processus à part), `communicate(timeout=…)`, et `kill_tree` au délai dépassé. stdout plafonné à 4 Mio, stderr à 4 Kio, ni l'un ni l'autre jamais journalisé.
- Délais : `PROBE_TIMEOUT = 30`, `CLI_TIMEOUT = 30` s. Pire cas d'un tour pour un run : `show` + `attachments` + `archive` + `show` ≈ 2 min, sous le verrou du tour comme aujourd'hui ; l'arrêt du serveur l'attend (borné).
- Le superviseur reste séquentiel (un tour à la fois, `tick_lock`) ; l'adaptateur protège son seul état partagé (dernières lectures) par un verrou.

### 7.2 Environnement de l'enfant

- `codex_process.child_env` reçoit un paramètre `allow` (liste blanche) ; Codex garde la sienne. Hermes utilise `HERMES_ENV_ALLOW` = la liste de base **sans** `CODEX_HOME`, **avec** `HERMES_HOME` (si Loïc l'a défini) ; puis l'adaptateur **ajoute** `PYTHONUTF8=1` et `PYTHONIOENCODING=utf-8`.
- Jamais transmis : `NEXUS_*` (filtre existant), `HERMES_KANBAN_BOARD` (changerait le tableau visé si `--board` manquait), `HERMES_PROFILE`, aucune clé du shell de Loïc, aucun jeton Nexus (D4).
- Le brief ne passe que par stdin ; l'argv ne contient que des valeurs construites par Nexus et validées (titre, clé, id, profil, nombres) : sûr même si `NEXUS_HERMES_BIN` désigne un `.cmd` (tests avec un lanceur `.cmd`, comme Codex).

### 7.3 Invariants

- **Un run actif par exécutant** (D7, index unique partiel) : un run Hermes `dispatched`, `running` ou `unknown` refuse tout autre run Hermes (409 `executor_busy`), quel que soit l'agent.
- **Signature** : `executor = hermes`, `agent = helios`, `origin = "hermes"` (D5) ; aucun événement n'est signé `helios`.
- **Aucune écriture dans Hermes hors de** : `create` (au dispatch), `archive` (annulation, durée maximale, fins non `done`). Jamais `boards …` en écriture, `assign`, `complete`, `block`, `unblock`, `comment`, `promote`.
- **Rien n'est relancé seul** : le superviseur n'appelle `dispatch` qu'une fois par run (marqueur `dispatching`) ; le second essai du §3.2 est la même création, identifiée par la même clé.
- Une clôture refusée par `publish` gèle le curseur (comportement existant) : chaque clôture est donc testée **à travers `publish`** (`blocked` : cause et plan ; `review` : preuve ; `failed` : cause ; `done` sans `working` préalable : accepté).

---

## 8. Plan de tests (écrits avant le code)

Aucun vrai Hermes en CI. `tests/hermes_support.py` fournit un faux `hermes` (script Python et lanceur `.cmd`/shell, comme `codex_support.py`) qui :

- lit `scenario.json` : pour chaque sous-commande (`assignees`, `create`, `show`, `archive`, `list`, `attachments`), une liste de réponses consommées dans l'ordre (la dernière se répète) ; une réponse = `stdout` (texte ou objet JSON), `exit`, `stderr`, `hang` ;
- ajoute à `calls.jsonl` chaque appel : argv, noms des variables d'environnement, valeurs de `PYTHONUTF8`, stdin (décodé en UTF-8) ;
- refuse (code 2) toute commande sans `--board nexus` placé avant la sous-commande, et toute sous-commande `boards`.

Des constructeurs de fixtures (`show_payload(status, events=[…], runs=[…], created_at=…)`, `attachment(path, size)`) écrivent des formes copiées de `kanban_output.py` (0.23.0).

### Traduction pure — `test_hermes_translate.py`

1. Histoire complète (`created`, `claimed`, `spawned`, `heartbeat`, `completed`) avec une preuve → `claimed`, `working`, `done` aux positions 2, 3, 5 ; curseur `"5"`.
2. `completed` sans preuve → `review` avec `hermes:nexus/<id>` et le résumé coupé dans le corps.
3. Curseur : `after=3` ne rend que les positions 4 et suivantes ; relire avec `after = curseur` ne rend rien.
4. Types inconnus et `heartbeat` : aucun fait, curseur au-delà.
5. `timed_out` puis `gave_up` → `progress` puis `failed` dont la cause cite `timed_out`.
6. `blocked` avec raison → `blocked` avec `cause` et `plan` ; raison vide ou réduite à un secret masqué → cause de repli.
7. `review_requested`, `changes_requested`, second `spawned` → `progress`, aucune clôture.
8. `archived` sans annulation de Nexus → `failed` « archivée hors de Nexus ».
9. Clôture suivie d'autres événements dans la même lecture → seule la clôture, curseur sur elle.
10. Événement malformé (kind non textuel, `created_at` absent, `payload` non objet) → consommé sans fait, sans exception.
11. Secrets dans `summary`, `error`, raison → masqués ; texte coupé à 500 après masquage (un secret à cheval sur la coupe reste masqué).
12. `at` = `created_at` Hermes en UTC, avec fuseau.
13. Durée maximale : tâche `ready` trop vieille → `failed` « pas pris la tâche » à `SEQ_WATCHDOG` ; tâche `running` → « durée maximale dépassée » ; dans le délai → rien ; clôture présente → pas de faits de durée.
14. `native_status` : `blocked/gave_up`, `done/completed`, `ready`.

### Preuves — `test_hermes_proof.py`

15. Pièce jointe `kanban_complete`, fichier présent, bonne taille → `file:<chemin>`.
16. Refusées : fichier absent, taille différente, `uploaded_by` autre, chemin relatif, UNC, `\\?\`, chemin de plus de 400 caractères ; plus de 10 pièces → 10 retenues.
17. `metadata.artifacts` hors pièces jointes → non retenu ; `commit` de 40 caractères → `payload` à 12 caractères, pas de preuve.

### Dispatch — `test_hermes_dispatch.py`

18. argv exact (§3.1), `--board nexus` avant `create`, aucun fragment du brief dans l'argv ; stdin = brief + consigne ; brief accentué (`Tâche à réécrire : « été »`) relu à l'identique ; brief contenant `--json` ou une ligne `-x` sans effet sur l'argv.
19. Délai au premier essai → arbre tué, second essai avec la même clé → `Dispatched` ; le second appel n'a lieu qu'après l'arrêt du premier.
20. Sortie illisible puis valide → `Dispatched`.
21. Deux refus → exception ordinaire (pas `LaunchUncertain`).
22. Délai puis délai, ou illisible puis refus → `LaunchUncertain`.
23. `id` non conforme (`t_../x`, `t_ABC`, espaces), `assignee` ou `title` différents → traité comme illisible.
24. `workdir` non vide, ou agent autre que `helios` → `ValueError` sans aucun appel.

### Suivi et annulation — `test_hermes_watch.py`, `test_hermes_cancel.py`

25. Deux `watch` à moins de 10 s → un seul `show`.
26. `show` en échec (code 1 sans `no such task`, délai, JSON illisible) → `HermesUnavailable` ; curseur et run inchangés après le tour.
27. `no such task` → `failed` à `SEQ_MISSING`.
28. Durée maximale : `archive` appelé avant la clôture ; archivage non confirmé → exception, aucun fait.
29. Clôture `blocked` ou `gave_up` → `archive` appelé avant ; archivage non confirmé → exception, aucun fait.
30. `completed` : `attachments` en échec → exception, pas de `review`.
31. `external_ref` invalide (`t_x & calc`) → `ValueError`, aucun processus lancé.
32. Annulation avec id : `archive` code 0 puis `show` archivé → confirmé ; `archive` code 1 (déjà archivée) puis `show` archivé → confirmé.
33. `archive_worker_termination` avec `terminated: false` et un `prev_pid` → lève ; avec le fichier `.stopped/nx-run-<n>` → confirmé ; `terminated: false` et `prev_pid: null` (réclamée, worker pas encore lancé) → confirmé ; `signal_refused: true` → lève.
34. `show` après `archive` toujours `running` → lève ; `no such task` → confirmé.
35. Sans id, `native_status` autre que `dispatching` → aucun appel ; avec `dispatching` → `list` filtré par titre et `created_by` ; aucune tâche → confirmé ; deux tâches → deux `archive`.

### Superviseur et API — `test_hermes_supervisor.py`, `test_hermes_registration.py`

36. Run complet par le superviseur, à travers `publish` : `claimed`, `working`, `done` ; `Run.status` `done` ; événements signés `hermes`, `origin = hermes`, ids `nx-run-<n>-<position>` ; un second tour sur la même sortie ne publie rien de nouveau.
37. Chaque clôture acceptée par `publish` (un refus gèlerait le curseur et ferait tourner le run en boucle) : `review` (preuve `hermes:`), `blocked` (cause + plan), `failed` après `spawn_failed`/`gave_up` sans `working` préalable, `failed` de durée maximale « pas pris la tâche » sans `working` préalable, `failed` « tâche introuvable ».
38. `LaunchUncertain` → événement `unknown` « lancement incertain », statut `unknown`, marqueur `dispatching` conservé ; puis annulation → `cancelled`.
39. #168 : l'écriture de la référence échoue après un `create` réussi → `archive` reçoit l'id renvoyé.
40. Redémarrage : `mark_lost` → `unknown` (D3 inchangé) ; annulation → archivage → `cancelled`.
41. Second run Hermes pendant qu'un premier est actif → 409 `executor_busy`.
42. Une fixture `autouse` de `conftest.py` retire `NEXUS_HERMES_BIN` et `NEXUS_HERMES_PROFILE` de l'environnement (Loïc les exporte pour le run réel et peut commiter depuis ce shell : le hook lance toute la suite) ; un test le vérifie avec `Settings.from_env()`. Enregistrement : `NEXUS_HERMES_BIN` absent → non enregistré **même si** `shutil.which("hermes")` trouve un binaire ; tableau absent (code 1) ou profil absent de `assignees` → non enregistré, `POST /api/tasks/<ref>/runs` → 409 `executor_unavailable` ; `NEXUS_HERMES_PROFILE` invalide → `ValueError` sans la valeur.
43. Enregistré : `GET /api/executors` → `hermes` avec `agents == ["helios"]` et `workdirs == []` ; confier à `mnema` via `hermes` → 409 `executor_unavailable` sans run créé ; confier `codex` via `hermes` → 409 `agent_not_for_executor` (inchangé).

### Sécurité — `test_hermes_security.py`

44. Environnement de l'enfant : aucun `NEXUS_*`, aucun jeton, ni `HERMES_KANBAN_BOARD` ni `HERMES_PROFILE` même présents chez le parent ; `PYTHONUTF8=1` présent ; `HERMES_HOME` transmis s'il est défini ; `CODEX_HOME` absent.
45. Aucune commande construite par l'adaptateur ne contient `boards`, `switch`, `use`, `assign`, `complete`, `block`, `unblock`, `comment`, `promote` (parcours de tous les argv de la suite).
46. Un secret dans `summary`, `metadata`, une raison de blocage ou un chemin → masqué dans l'événement publié ; un `stderr` contenant un secret n'apparaît dans aucun journal (`caplog`).
47. Curseur illisible (`"abc"`, `"-3"`, 600 caractères) → relu depuis 0, aucun doublon publié.

### Run réel (Loïc, jamais en CI)

Prérequis : passerelle de Helios en marche (`hermes profile list` : Gateway `running`).

1. Créer le tableau : `hermes kanban boards create nexus --name Nexus` ; vérifier `hermes kanban boards list` (deux tableaux) et `hermes kanban boards show` (toujours `default`).
2. Vérifier le profil : `hermes kanban --board nexus assignees --json` contient `default`.
3. Lancer Nexus avec `NEXUS_HERMES_BIN=hermes`, `NEXUS_HERMES_PROFILE=default`, `NEXUS_RUN_MAX_MINUTES=30` ; `GET /api/executors` liste `hermes` pour `helios`.
4. **Scénario A — `done` avec preuve :** une tâche avec une prochaine action, confiée à Helios avec le brief « Écris un fichier `synthese.md` de cinq lignes sur <sujet>, puis déclare-le comme livrable (metadata.artifacts). Accents : é è à ç « » ». Attendu : `claimed` → `working` → `done` avec `file:…\attachments\t_…\synthese.md` et `hermes:nexus/t_…`. Dans Hermes, `show <id> --json` : titre `Nexus nx-run-<n> nx-task-<m>`, corps accentué intact, `created_by` `nexus`, `max_runtime_seconds` 1800, `max_retries` 1, `workspace_kind` `scratch`.
5. **Scénario B — `review` :** brief sans livrable (« Réponds en une phrase : … »). Attendu : `review` avec `hermes:nexus/t_…` et le résumé.
6. **Scénario C — annulation :** brief long ; annuler après `working`. Attendu : tâche `archived`, `archive_worker_termination` avec `terminated: true`, run `cancelled`, plus aucun processus worker.
7. **Scénario D — redémarrage :** relancer Nexus pendant un run → `unknown` ; annuler → archivé, `cancelled`.
8. Vérifier que `default` n'a reçu aucune tâche (`hermes kanban list`) et que le tableau courant n'a pas changé.
9. Noter dans la PR : types d'événements vus, forme de `metadata` et des pièces jointes, comportement de la relecture Hermes si Helios l'a demandée, durée d'un tour.

---

## 9. Fichiers touchés et découpage (seuils 400 / 600 lignes)

| Fichier | Contenu | Taille visée |
|---|---|---|
| `server/src/nexus/adapters/hermes.py` (nouveau) | `HermesAdapter` (`probe`, `dispatch`, `watch`, `cancel`, `recover`, `close`), `register_configured` | ≤ 260 |
| `server/src/nexus/adapters/hermes_cli.py` (nouveau) | constantes (`BOARD`, délais, plafonds), construction et validation des argv (titre, clé, id), `call()` borné, environnement, lecture JSON, `HermesUnavailable`, `HermesRefused` | ≤ 170 |
| `server/src/nexus/adapters/hermes_translate.py` (nouveau) | traduction pure, table du §4.3, faits réservés, `native_status` | ≤ 230 |
| `server/src/nexus/adapters/hermes_proof.py` (nouveau) | pièces jointes → preuves (§4.4) | ≤ 80 |
| `server/src/nexus/adapters/text.py` (nouveau) | `cut()` et `TEXT_MAX`, déplacés de `codex_translate.py` | ≤ 40 |
| `server/src/nexus/adapters/codex_translate.py` | importe `cut` | −15 |
| `server/src/nexus/adapters/codex_process.py` | `child_env(environ, allow=ENV_ALLOW)` | +3 |
| `server/src/nexus/adapters/base.py` | `LaunchUncertain` ; attribut facultatif `agents` documenté | +10 |
| `server/src/nexus/runs/supervisor.py` (353) | `except LaunchUncertain` dans `_dispatch` | ≤ 370 |
| `server/src/nexus/runs/rules.py`, `runs/api.py` | agents servis par l'adaptateur | +8 |
| `server/src/nexus/config.py` (190), `app.py` (251) | réglages, enregistrement | +20, +2 |
| `server/tests/hermes_support.py` (nouveau) | faux `hermes`, fixtures | ≤ 200 |
| `server/tests/test_hermes_translate.py`, `test_hermes_proof.py`, `test_hermes_dispatch.py`, `test_hermes_watch.py`, `test_hermes_cancel.py`, `test_hermes_supervisor.py`, `test_hermes_registration.py`, `test_hermes_security.py` (nouveaux) | §8 | chacun ≤ 350 |
| `docs/INTEGRATIONS.md` §A.1 | réglages, commande de création du tableau, preuves, limites (curseur, course après plantage, `.stopped`) | |
| `docs/SECURITY.md` §3 | adaptateurs enregistrés : Codex **et** Hermes (opt-in), liste blanche Hermes, écritures autorisées dans Hermes | |
| `docs/DATA-MODEL.md` §2.5 | exemple `external_ref` = `t_9f3a01bc` ; Hermes ne sert que `helios` tant que l'adaptateur le dit | |
| `docs/ROADMAP.md` | lot G | |
| `DECISIONS.md` | addendum D7 (§10), une fois la politique confirmée | |

Aucun fichier existant ne franchit son seuil ; aucune entrée de `file-size-baseline.json` n'est ajoutée.

Ordre d'implémentation conseillé : (1) `text.py` et `child_env(allow)` (refactor sans changement, suite verte) ; (2) traduction et preuves (tests 1–17) ; (3) `hermes_cli` et dispatch (18–24) ; (4) watch et cancel (25–35) ; (5) `LaunchUncertain`, règles, API, enregistrement (36–43) ; (6) sécurité (44–47) ; (7) docs. Le lot touche la concurrence et un invariant du superviseur : `architect` relit ce cadrage avant `implementer` (AGENTS.md, Model routing).

---

## 10. Faut-il un addendum à ADR-023 ?

**Aucun écart** dans ce lot : D3 (redémarrage → `unknown`), D4 (stdin, liste blanche, aucun jeton), D5 (signature `hermes`), D7 (tableau créé par Loïc, tâches en `ready`, un run par exécutant, durée maximale, aucune relance automatique) et la sémantique de #168 sont respectés ; `LaunchUncertain` réutilise le chemin « lancement incertain » existant.

En revanche **D7 exige que la politique de relecture et de nouvelles tentatives soit confirmée avant l'adaptateur**. Une fois Loïc d'accord avec le §6, la PR ajoute à ADR-023 un addendum daté (« D7 précisé pour Hermes ») : `--max-retries 1`, relecture Hermes laissée intérieure au run, fins non `done` archivées, preuve = pièce jointe recopiée par Hermes et relue sur le disque, profil `default` pour Helios. La reprise du suivi après redémarrage (§6.4) serait, elle, un vrai écart à D3 : addendum distinct, hors de ce lot.

---

## 11. Ce qui revient à Loïc

1. **Reprise après redémarrage** (§6.4) : ce cadrage garde ADR-023 D3 (au redémarrage, le run passe `unknown` et Loïc l'annule), alors que Hermes continue d'exécuter la tâche. Reprendre le suivi est possible sans toucher l'adaptateur (il est sans état), mais c'est un écart à D3 : addendum et PR distincts, si Loïc le veut.
2. **Politique de relecture (D7)** : laisser `review_dispatch` lancer le relecteur Hermes (et un nouveau worker après `changes_requested`) à l'intérieur du run, borné par la durée maximale (§6.2) — recommandé ; sinon il faut désactiver `review_dispatch` globalement chez Helios.
3. **Règle de preuve** : seule une pièce jointe recopiée par Hermes (fin ou demande de relecture) et présente sur le disque fait `done` ; tout le reste finit en `review` (§4.4). Conséquence : la plupart des runs sans fichier livré finiront en `review`.
4. **Profil** : l'agent `helios` correspond au profil Hermes `default` sur cette machine (§0.1).
5. **Archivage des fins non `done`** (§4.6) : une tâche Hermes bloquée ou abandonnée est archivée quand Nexus clôt le run.
6. **Création du tableau** : la commande du §2, une fois, avant le run réel.
