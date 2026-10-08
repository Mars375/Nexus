# EVENT-PROTOCOL — Nexus

**Version :** 0.2 (transport via l'API Nexus — ADR-011, ADR-015)
**Date :** 2026-09-28

---

## 1. But

Un langage commun, structuré et visible par tous (Loïc + agents), pour que chacun puisse déclarer :

```text
ce qu'il prend        → claimed
ce qu'il fait         → working / progress
ce qui le bloque      → blocked
ce qu'il demande      → question / needs_human
ce qu'il transfère    → handoff
ce qui est vérifiable → review / done
ce qui a échoué       → failed
ce qu'il ignore       → unknown
```

Règles générales :

- Un événement = un fait daté, **immuable**, attribué à son acteur.
- **Silence autorisé** : pas de nouveau → pas d'événement (pas de bruit).
- **Read-back obligatoire** : l'émetteur vérifie que l'événement est visible de tous avant de le considérer publié.
- Aucun secret dans un événement ; `[REDACTED]` sinon.
- Les événements ne déclenchent **aucun agent** : ils informent.

## 2. Enveloppe

```json
{
  "v": 1,
  "id": "evt_20260928_helios_0007",
  "at": "2026-09-28T07:46:00+02:00",
  "task": "nx-task-142",
  "run": "nx-run-31",
  "actor": "helios",
  "kind": "progress",
  "subject": "Adaptateur Hermes : lecture des runs OK",
  "body": "Runs du board default lus ; structure validée sur les tables tasks et task_runs.",
  "payload": { "percent": 40 },
  "evidence": ["commit:a1b2c3d", "file:F:/Projet/Nexus/docs/ARCHITECTURE.md"],
  "needs": []
}
```

| Champ | Requis | Notes |
|---|---|---|
| `v` | ✓ | version du protocole |
| `id` | ✓ | unique, local à l'acteur |
| `at` | ✓ | ISO-8601 avec fuseau |
| `task` | opt | réf tâche Nexus (`nx-task-…`) ; `null` pour un événement de coordination |
| `run` | opt | réf run Nexus (`nx-run-…`) quand l'événement concerne un travail confié |
| `actor` | ✓ | `loic`, `helios`, `mnema`, `aether`, `artemis`, `claude`, `codex`, `orca`, `hermes` |
| `kind` | ✓ | voir §3 |
| `subject` | ✓ | une ligne lisible |
| `body` | opt | détail court |
| `payload` | opt | données du kind |
| `evidence` | opt* | *requis pour `done` |
| `needs` | opt* | *requis pour `question`, `needs_human`, `handoff` |

## 3. Kinds

| Kind | Sens | Requis en plus | Exemple |
|---|---|---|---|
| `claimed` | « je prends cette tâche » | — | `^ claimed #142 par helios` |
| `working` | début d'exécution (run) | `payload.run_ref` | `^ working #142, session tmux …` |
| `progress` | avancement notable | `payload.percent` ou description | `^ 40 % : parse OK` |
| `question` | question à un acteur | `needs` + question explicite ; `payload.consequence` et `payload.expires_at` facultatifs | `^ question → mnema : quel scope ?` |
| `blocked` | bloqué | cause + `payload.follow_up_at` ou plan | `^ bloqué : SSH artemis timeout` |
| `needs_human` | décision de Loïc requise | décision attendue + options + `payload.consequence` ; `payload.expires_at` facultatif | `^ validation : publier l'épisode ?` |
| `handoff` | transfert de responsabilité | receveur + prochaine action | `^ handoff → aether : reste à poser la clé` |
| `review` | prêt pour revue | quoi vérifier + où | `^ review : PR #12, diff court` |
| `done` | terminé | `evidence` non vide | `^ done : commit a1b2c3d + tests verts` |
| `failed` | échec | cause + effet | `^ failed : 429 Go, run non exécuté` |
| `unknown` | état non vérifiable | dernière vérification | `^ unknown : run non confirmé depuis 2 h` |
| `answer` | **réservé à Nexus** : la réponse ou la décision de Loïc à une demande | — (écrit par `POST /api/approvals/…`) | `^ validé : nx-appr-3` |

Les identifiants `answer-…` sont réservés de la même façon (refus `reserved_id`, 409) : un événement qui prendrait `answer-nx-appr-<n>` rendrait cette approbation impossible à traiter. `answer` n'est **jamais publié par un agent** : `POST /api/events` le refuse (422), comme tout appel direct au service qui ne vient pas de Nexus. Sinon un agent pourrait fabriquer une réponse de Loïc (ADR-019, D8). Il se lit et se filtre comme les autres (`GET /api/events?kind=answer`).

## 4. Règles par kind

- **claimed** — avant de commencer à travailler ; un claim remplace le précédent (dernier claim gagne, il est daté).
- **working** — ouvre un run ; un seul run actif par agent et par tâche.
- **progress** — pas plus d'un par étape significative ; pas de spam.
- **question / needs_human** — doit nommer le destinataire (`needs`) et être actionnable : pas de « ça avance ? ». Adressé à un humain, il ouvre une **approbation** (§6 bis, DATA-MODEL §2.10). Deux champs du `payload` :
  - `consequence` (texte, 1 000 caractères au plus) : ce qui se passera si Loïc approuve. **Obligatoire pour un nouveau `needs_human`** (refus `consequence_required`), facultative pour une `question`. C'est une déclaration du demandeur que Nexus ne vérifie pas (ADR-005) ; elle passe par le masquage des secrets comme le reste du payload, et un texte réduit à `[REDACTED]` compte comme absent.
  - `expires_at` (texte ISO-8601 **avec fuseau**) : échéance fixée par l'agent, sans valeur par défaut. Au moins 1 minute et au plus 30 jours après la réception (refus `invalid_expires_at`, `expires_at_too_soon`, `expires_at_too_far`). Passé cet instant, l'approbation est lue `expired` (calcul à la lecture, rien n'est écrit). Ces contrôles de `consequence` et `expires_at` (type, longueur, format, fenêtre) ne jugent que les **nouveaux** événements : un renvoi identique d'un événement déjà reçu reste une relecture, même après l'échéance ou si le payload ne respecte plus les règles actuelles.
- **blocked** — doit dire : cause, impact, ce qui débloquerait, relance prévue. Sinon c'est `unknown`.
- **handoff** — doit dire : receveur, état exact, prochaine action, ce qui est déjà fait. Un handoff sans prochaine action est refusé.
- **review** — doit pointer la preuve à examiner.
- **done** — sans `evidence` → transformé en `review` automatiquement (règle « preuve ou review »).
- **failed** — cause exacte quand connue ; effets de bord constatés.
- **unknown** — honnête : ce qu'on ne peut pas vérifier, avec la dernière date de contrôle.

## 5. Exemples réels (cible)

Prise en charge :

```json
{ "v": 1, "id": "evt_0001", "at": "2026-09-28T09:05:00+02:00",
  "task": "nx-task-7", "actor": "helios", "kind": "claimed",
  "subject": "Je prends l'API d'événements", "needs": [] }
```

Blocage :

```json
{ "v": 1, "id": "evt_0002", "at": "2026-09-28T11:22:00+02:00",
  "task": "nx-task-7", "actor": "helios", "kind": "blocked",
  "subject": "SSH Artémis injoignable",
  "body": "Timeout Tailscale. Impact : pas de lecture de l'usine. Déblocage : nœud rallumé par Loïc.",
  "payload": { "follow_up_at": "2026-09-29T09:00:00+02:00" }, "needs": ["loic"] }
```

Terminé avec preuve :

```json
{ "v": 1, "id": "evt_0003", "at": "2026-09-28T17:40:00+02:00",
  "task": "nx-task-7", "actor": "helios", "kind": "done",
  "subject": "API d'événements livrée",
  "evidence": ["commit:f00db4r", "log:artifacts/smoke-read-20260928.txt"] }
```

## 6. Transport

- **Authentification (ADR-020) :** toute requête REST, `POST /api/events` comme les lectures, porte `Authorization: Bearer nxt_…`, le jeton **de l'acteur qui parle** (`nexus-token issue <acteur>`). Sans lui ou avec un jeton mal formé : `401 auth_required` ; jeton inconnu ou révoqué : `401 invalid_token`. L'`actor` de l'enveloppe doit être l'acteur du jeton, et `X-Nexus-Actor`, s'il est envoyé, aussi : sinon `403 actor_mismatch` (rien n'est enregistré). Un 4xx ne recopie jamais la valeur reçue. Le WebSocket `/api/ws` ne demande pas de jeton (ticket prévu : #57). Seuls `GET /api/health` et la documentation OpenAPI (`/openapi.json`, `/docs`, `/redoc`) restent ouverts (schéma de l'API seulement ; protégés du DNS rebinding par le contrôle `Host`).
- **API locale Nexus (Phase 1) :** un agent publie par `POST /api/events` ; Nexus valide (champs requis, anti-patterns §7, scan de secrets) puis écrit dans `nexus.db`. C'est le chemin des agents lancés ailleurs (ADR-015 b).
- **Adaptateurs d'exécution (Phase 2) :** pour un travail confié, l'adaptateur traduit les événements natifs en événements Nexus (`origin` = nom de l'adaptateur). Ex. Hermes : `claimed` → `claimed`, `blocked` → `blocked`, `review_requested` → `review`, `completed` → `done` (preuves reprises du `metadata` de complétion).
- **Read-back :** l'émetteur relit l'événement (`GET /api/events/<id>`) et confirme sa visibilité ; tant que ce n'est pas confirmé, il reste `unknown` côté émetteur.
- **Diffusion :** l'interface écoute `/api/ws` (WebSocket) : messages minces (`hello`, `task_changed`, `event`, `resync`, `ping`) qui ne portent que des références et un curseur ; l'interface relit ensuite par l'API REST. Rattrapage après coupure par le curseur `{history, events}`, accompagné de l'`instance` du serveur annoncée dans `hello` : si elle a changé (redémarrage, base restaurée), le serveur répond `reset: true` et le client relit tout. Format et règles : `docs/superpowers/specs/2026-09-30-temps-reel-design.md`. Les alertes urgentes (`needs_human`, `blocked` critique) partiront aussi sur Telegram (hors Phase 1).

## 6 bis. Effets sur la tâche (implémentés en Phase 1)

Un événement valide est **toujours enregistré** (c'est un fait déclaré). Ses effets sur la tâche passent par les règles des tâches ; un effet refusé est consigné dans `effects` avec sa raison, sans faire échouer la publication.

Un effet qui ne change rien est consigné comme **non appliqué**, avec sa raison, et n'ajoute aucune ligne à l'historique de la tâche ni ne change sa date de modification. C'est le cas d'un `handoff` vers l'agent déjà principal avec la même prochaine action (espaces autour exclus). Un `claimed` de l'agent déjà principal, lui, n'a aucun effet à consigner : `effects` reste vide.

| Kind | Effet sur la tâche |
|---|---|
| `claimed` | l'émetteur devient agent principal (appliqué aussi pour un exécutant : il se désigne lui-même) |
| `working` | passage en `in_progress` (ouvre le run) |
| `blocked` | passage en `blocked` avec cause, plan, relance |
| `review` | passage en `review`, avec les preuves jointes (Loïc peut ensuite clore sans les redemander) |
| `done` | passage en `done` avec les preuves (sans preuve : l'événement est stocké en `review`) |
| `handoff` | le destinataire devient agent principal ; la prochaine action est mise à jour. **Un exécutant (`claude`, `codex`, `orca`, `hermes`) ne peut confier la tâche qu'à lui-même ou à un humain** : vers un autre agent qui n'est pas déjà l'agent principal, l'événement est enregistré mais l'effet n'est pas appliqué (`applied: false`, raison « lead_agent : un exécutant ne peut désigner que lui-même, un humain ou personne »), la tâche garde son agent principal et sa prochaine action (SECURITY §3, `assign_forbidden`) |
| `progress`, `failed`, `unknown` | aucun changement d'état : visibles dans l'historique et les vues |
| `question`, `needs_human` | aucun changement d'état de la tâche ; adressés à un humain, ils ouvrent une approbation (effet `approval`, ci-dessous) |
| `answer` | **aucun effet** sur la tâche et **ne ferme aucun run** : elle ne consigne que la décision (elle n'est pas dans `RUN_CLOSERS`) ; la tâche du demandeur y reste attachée pour l'historique |

L'effet `approval` est consigné **en plus** des effets sur la tâche, et même sans tâche :

```json
{ "action": "approval", "applied": true, "approval": "nx-appr-3" }
```

L'approbation est créée dans la même transaction que l'événement ; un `needs` qui répète le même humain n'en ouvre qu'une, un destinataire non humain (`needs: ["mnema"]`) aucune. Il faut au moins un destinataire humain **autre que l'auteur** : `loic` qui demande à `loic` (ou à `loic` et `helios`) n'ouvre rien, car personne ne pourrait la traiter (le demandeur ne tranche pas sa propre demande). Un renvoi identique ne crée rien de plus et renvoie la même référence (c'est l'événement relu qui la porte).

Une clôture (`done`, `review`, `blocked`, `handoff`, `failed`) doit nommer son run (`run` ou `payload.run_ref`). Si elle vise un autre run que le run actif de l'agent (ex. `done(r1)` arrivé après `working(r2)`) ou n'en nomme aucun alors qu'un run est actif, elle est enregistrée mais ne modifie pas la tâche et ne ferme pas le run actif. Une référence de run close l'est pour de bon : un `working` tardif ou rejoué de ce run est enregistré sans rouvrir la tâche, et une seconde clôture de ce run (`done(r1)` après `handoff(r1)`) est enregistrée sans effet ; pour reprendre, on ouvre un nouveau run. Un seul run actif par agent et par tâche ; un `handoff` nomme **un seul** destinataire.

Autres garanties : un renvoi du même `id` par le même acteur est une relecture (pas de doublon) ; un même `id` réutilisé pour un autre contenu est refusé ; le même fait republié dans les 10 minutes est refusé comme bruit ; les secrets sont masqués avant écriture ; un identifiant d'événement ou une référence de run qui contient un secret est refusé (masqué, il ne serait plus unique).

L'événement `answer` écrit par Nexus pour une réponse ou une décision a pour `actor` celui qui décide (`loic`), `origin` `api`, la tâche de la demande, `needs` = [le demandeur], et pour `id` `answer-nx-appr-<n>` : un seul événement possible par approbation (un second contenu est refusé par la contrainte d'unicité). Son `subject` ne porte que des références (`réponse : nx-appr-3`, `validé : nx-appr-3`, `refusé : nx-appr-3`), jamais un texte reçu ; son `body` est la réponse ou la note (secrets masqués) ; son `payload` est `{approval, in_reply_to, decision, choice}` (`decision` : `answered`, `approved` ou `rejected` ; `choice` : l'indice de l'option, sinon `null`). L'événement et la mise à jour de l'approbation sont écrits dans **une seule transaction** : les deux existent ou aucun.

Exemples exécutables (`server/src/nexus/demo_agent.py`) : `uv run python -m nexus.demo_agent --task nx-task-1 --actor helios --evidence commit:…` joue claimed → working → progress → done ; `uv run python -m nexus.demo_agent --task nx-task-1 --ask "Publier ?" --wait 120` demande une validation à Loïc et relit l'approbation jusqu'à sa décision (§6 ter). Avec un jeton d'acteur (ADR-020), l'exemple l'envoie dans `Authorization: Bearer …` : `NEXUS_TOKEN=nxt_… uv run python -m nexus.demo_agent …` ou `--token-file <chemin>` (le fichier l'emporte sur la variable ; il ne contient que le jeton, une ligne). Il n'existe pas d'option `--token` : un argument est visible dans la liste des processus. Un fichier introuvable, illisible ou qui ne contient pas un jeton `nxt_…` est une erreur d'usage (code 2) qui ne recopie ni le fichier ni le jeton. Le jeton ne part qu'en HTTPS, ou en HTTP vers cette machine (`localhost`, `127.0.0.0/8`, `::1`) ou vers un pair Tailscale donné par son adresse `100.64.0.0/10` (chiffré par WireGuard quand Tailscale est actif ; cette plage est aussi celle du CGNAT des FAI). Avec un jeton, tout autre `--base` HTTP est refusé avant tout envoi (code 2), y compris un nom `*.ts.net`, dont la résolution n'est pas vérifiée : utiliser l'adresse du pair ou HTTPS. L'exemple ne suit aucune redirection, puisque urllib y recopierait `Authorization`, et ignore `http_proxy` : une requête HTTP part toujours en direct, sans passer en clair par un proxy (`https_proxy` reste utilisé en HTTPS, son tunnel est chiffré). Sans jeton, le serveur répond 401 et l'exemple dit où le fournir. Codes de sortie de `--ask --wait` : 0 validée ou répondue, 3 refusée, 1 échéance passée, délai écoulé ou Nexus injoignable, 2 arguments invalides. Un agent qui lit 0 comme « feu vert » ne publie donc jamais après un refus (sans `--wait`, 0 veut seulement dire « demande envoyée »).

## 6 ter. Retour vers l'agent

Nexus **ne lance et ne réveille aucun agent** (ADR-012) : valider ou répondre ne déclenche rien chez lui. C'est l'agent qui vient lire.

1. À la publication de sa demande, l'agent garde la référence `nx-appr-<n>` de l'effet `approval` dans la réponse (ou la relit dans l'événement : `GET /api/events/<id>`, champ `effects`).
2. Il interroge `GET /api/approvals/<nx-appr-n>` à son rythme, jusqu'à ce que `status` ne soit plus `pending`. `expired` veut dire que l'échéance qu'il a fixée est passée sans décision.
3. Il lit alors la décision et reprend son travail en publiant ses propres événements :

```json
{ "id": "nx-appr-3", "status": "approved", "decided_by": "loic", "decided_at": "2026-10-07T14:05:00+02:00",
  "response": { "event": "nx-evt-12", "text": "Go, sans la vidéo", "choice": 1, "redacted": [] } }
```

   - `status` : `approved` / `rejected` (un `needs_human`) ou `answered` (une `question`) ; `decided_by` et `decided_at` (instant de réception) viennent de l'événement `answer` (§3).
   - `response.text` : la réponse, ou la note de la décision (`null` sans note) ; secrets masqués, `response.redacted` en liste les types.
   - `response.choice` : l'**indice** (à partir de 0) de l'option dans `payload.options` de la demande, qui fait foi ; `null` sans choix. `options` dans `GET /api/approvals` garde les mêmes positions (un élément non textuel y devient une chaîne vide).

**Écrire la décision** (Loïc, depuis l'interface ; l'acteur est celui du jeton porteur, exigé (ADR-020) : `X-Nexus-Actor`, facultatif, doit lui être égal) :

| Route | Corps | Effet |
|---|---|---|
| `POST /api/approvals/<ref>/answer` | `{"text": "…"}` (texte requis, 2 000 caractères au plus) | une `question` passe de `pending` à `answered` |
| `POST /api/approvals/<ref>/decision` | `{"decision": "approved" \| "rejected", "choice": 1, "note": "…"}` (`choice` et `note` facultatifs, `note` 2 000 caractères au plus) | un `needs_human` passe de `pending` à `approved` ou `rejected` |

Les corps refusent tout champ inconnu (422) ; `choice` est un entier (un booléen est refusé en 422). Sur un refus, `choice` est facultatif, mais **validé s'il est fourni** (409 `choice_unknown`) et conservé. Une note faite d'espaces équivaut à pas de note (`response.text` nul). Approuver une demande qui propose **au moins 2 options** exige `choice` ; refuser ne l'exige pas. Réponse : **200** avec la même vue que `GET /api/approvals/<ref>`. Refus (409, `detail.code`), sans jamais recopier une valeur reçue :

| Code | Cas |
|---|---|
| `wrong_kind` | une décision sur une `question`, ou une réponse sur un `needs_human` |
| `self_decision` | le demandeur tranche sa propre demande |
| `not_addressee` | l'acteur n'est pas un destinataire **humain** de la demande (contrôle de cohérence, pas de sécurité : SECURITY §3) |
| `approval_expired` | `maintenant >= expires_at` : l'agent n'attend plus de réponse |
| `approval_already_decided` | déjà traitée, avec un autre contenu : « déjà validée par loic le 07/10/2026 à 14:05 » |
| `answer_required` | texte vide, ou réduit à des secrets masqués (`[REDACTED]`) |
| `choice_required`, `choice_unknown` | `choice` manquant (2 options ou plus, pour approuver) ou qui ne désigne aucune option |
| `approval_concurrent_update` | la demande change sans cesse en parallèle (vraie course, trois relectures épuisées) : relire et réessayer |
| `approval_id_taken` | un événement étranger occupe déjà l'identifiant `answer-nx-appr-<n>` : réessayer ne sert à rien, il faut le signaler |

**Renvoi et concurrence.** Le même décideur qui renvoie le même contenu (décision, `choice`, texte ou note **après masquage**) sur une approbation déjà traitée reçoit **200** avec l'état existant, sans nouvel événement ; un autre contenu est un 409 `approval_already_decided`. Deux décisions simultanées : une seule l'emporte, l'autre est relue puis comparée (identique : 200, différente : 409) ; un seul événement `answer` existe. Une demande déjà traitée ne devient jamais `expired`. La comparaison se fait sur ce qui est **stocké**, après masquage : deux textes ou notes qui ne diffèrent que par un secret masqué sont le même contenu (200). L'échéance est jugée à la réception de la décision par le serveur ; `decided_at` est l'instant d'enregistrement et peut la dépasser de quelques secondes (attente du verrou SQLite).

## 7. Anti-patterns (refusés)

- « done » sans preuve.
- « handoff » sans receveur ni prochaine action.
- Question sans destinataire.
- Événement-bruit (je répète la même chose toutes les 5 min).
- Modifier un événement passé au lieu d'en publier un rectificatif.
- Publier un secret, même partiellement.
