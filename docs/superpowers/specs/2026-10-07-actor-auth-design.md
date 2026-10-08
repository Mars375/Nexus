# Authentification des acteurs et matrice §3 — conception (#16)

**Date :** 2026-10-07 · **Statut :** validée par Loïc le 2026-10-07 (« Suis tes recommandations » : D1 à D9 et lectures du §2)
**Sources lues :** SECURITY §1, §3, §9 ; DECISIONS (ADR-005, 006, 012, 015, 017, 019) ; ARCHITECTURE §3.4, §5, §7 ; EVENT-PROTOCOL §6 ter ; `server/src/nexus/{actors,app,config,live,logs,demo_agent}.py`, `tasks/api.py`, `events/api.py`, `events/service.py` (`_apply_effects`), `approvals/{api,service}.py`, `web/src/{api,apiBase,live}.ts`, `web/playwright.config.ts`.
Il n'existe ni `CONTEXT.md` ni `docs/adr/` : les ADR sont dans `DECISIONS.md` (dernier : ADR-019).

## 0. Constat

- `tasks/api.py:get_actor` lit `X-Nexus-Actor`, `loic` par défaut (`actors.DEFAULT_ACTOR`) ; `approvals/api.py` réutilise `ActorDep`. `events/api.py:publish` prend `body.actor` et ne compare l'en-tête que s'il est présent. L'UI (`web/src/api.ts:request`) n'envoie aucun en-tête : elle est `loic` par défaut. Le WebSocket (`live.py`) ne vérifie que `Origin`.
- Aucune vérification de l'en-tête `Host` : une page web malveillante peut faire du DNS rebinding sur `127.0.0.1:8765`.
- Le serveur ne sert pas l'UI (Vite en dev, Tauri plus tard) : page et API seront d'origines différentes dans Tauri (#47).
- Les agents locaux (claude, codex, orca, hermes) tournent sous le compte Windows de Loïc sur Helios.

## 1. Décisions

**D1 — Jeton porteur par acteur.** `Authorization: Bearer nxt_<43 caractères base64url>` (32 octets de `secrets.token_bytes`). L'acteur se déduit du jeton, jamais d'un en-tête déclaratif.
*Alternatives écartées :* socket Unix/peer credentials (n'existe pas sous Windows, incompatible Tailscale) ; signature HMAC par requête (fenêtre anti-rejeu, horloges, complexité sans gain sur loopback ou tailnet déjà chiffré par WireGuard) ; mTLS (lourd).

**D2 — Nexus ne garde que l'empreinte.** Table `actor_tokens` : `id`, `actor`, `label`, `token_hash` (SHA-256 hex, unique), `created_at`, `revoked_at`. Pas de sel ni de hachage lent : 256 bits d'entropie rendent la force brute impossible. Recherche par empreinte puis `hmac.compare_digest`. Pas de cache : une révocation vaut à la requête suivante. SECURITY §1 précise que l'empreinte n'est pas un secret (elle ne permet pas de s'authentifier ni de retrouver le jeton). C'est la seule lecture compatible avec §9 (« jamais chiffré maison »).
*Alternative :* jeton en clair dans un fichier du dossier de données. Écartée : Nexus stockerait un secret.

**D3 — Provisionnement par une CLI locale.** Nouveau script `nexus-token` (`[project.scripts]`, module `nexus/auth/cli.py`) : `issue <acteur> --label <texte>` affiche le jeton une seule fois sur la sortie standard ; `list` (référence `nx-tok-<n>`, acteur, label, dates, jamais le jeton ni un fragment) ; `revoke nx-tok-<n>`. Rotation : émettre le nouveau, basculer, révoquer l'ancien. Plusieurs jetons par acteur sont permis (navigateur, CLI, Tauri). Le texte clair vit chez l'agent : variable `NEXUS_TOKEN` ou fichier sous ACL lu par `--token-file`, jamais `--token` sur la ligne de commande (visible dans la liste des processus).
*Alternative :* route HTTP d'émission. Écartée : il faudrait déjà être `loic`, et elle élargit la surface.

**D4 — L'UI s'authentifie comme `loic` avec un jeton.** Un écran « Nexus verrouillé » demande le jeton émis par `nexus-token issue loic --label navigateur`. L'UI le garde en `localStorage` et l'envoie dans `Authorization` par `request()`. Dans Tauri, le sidecar l'injectera au lancement, sans copier-coller. Un en-tête `Authorization` n'est jamais joint automatiquement par le navigateur : pas de CSRF possible, et le CORS de #47 n'aura qu'à autoriser l'en-tête `Authorization`, sans `allow_credentials`.
*Alternative :* cookie HttpOnly SameSite=Strict. Écartée : dans Tauri, page et API sont sur des sites différents (`tauri.localhost` vs `127.0.0.1`), le cookie n'y serait pas envoyé sans `SameSite=None; Secure` (HTTPS).
*Alternative :* « loopback = Loïc ». Écartée : les agents locaux sont aussi sur la boucle locale, ce qui recrée exactement le défaut de #16.

**D5 — Périmètre et limite assumée.** Un jeton est exigé sur toutes les routes REST sauf `GET /api/health`, lectures comprises : la règle est simple et le REST est prêt pour Tailscale. Le WebSocket reste sans jeton en Phase 1 : il ne transporte que des références et des types, et ses contrôles `Origin` et `Host` le protègent des pages web. `Settings` refuse un `NEXUS_HOST` hors boucle locale tant qu'un ticket WebSocket n'existe pas (issue de suivi). **Limite à écrire dans SECURITY §3, comme pour D5 d'ADR-019 :** un processus qui tourne sous le compte Windows de Loïc peut lire `localStorage`, un fichier de jeton, ou lancer `nexus-token issue loic`. Le mécanisme arrête les pages web, les pairs du tailnet et l'erreur d'un agent qui utilise son propre jeton. Il n'arrête pas un agent local décidé à tricher : seule une séparation des comptes OS le ferait.

**D6 — Contrôle de `Host` contre le DNS rebinding.** Un middleware maison (HTTP et WebSocket) n'admet que les noms d'hôte `localhost`, `127.0.0.1` et `::1`, quel que soit le port, plus les noms de `NEXUS_ALLOWED_HOSTS`. Un hôte refusé reçoit `400 invalid_host`, sans recopier la valeur. On n'utilise pas `TrustedHostMiddleware` de Starlette : il découpe `[::1]:8765` sur `:` et casse l'IPv6. Le port est ignoré pour que le proxy Vite (`Host: localhost:5173`) passe.

**D7 — Déploiement : refus par défaut, sans drapeau.** PR 1 accepte un jeton s'il est présent (sans jeton, comportement actuel). PR 2 fait envoyer le jeton par l'UI. PR 3 l'exige partout et supprime `DEFAULT_ACTOR`. Il n'y a pas de `NEXUS_AUTH=off` : tous les appelants sont dans ce dépôt (UI, `demo_agent`, tests, e2e), et un drapeau de contournement devient permanent.
*Alternative :* mode `warn` pendant une semaine. Inutile sans appelant externe.

**D8 — Codes HTTP.** `401 auth_required` (jeton absent ou mal formé, avec `WWW-Authenticate: Bearer`). `401 invalid_token` (inconnu ou révoqué, même message pour les deux). `403` pour une règle de la matrice, c'est-à-dire un droit que cet acteur n'a jamais : `actor_mismatch`, `assign_forbidden`, `human_only`. `409` pour une règle qui dépend de l'état : les codes existants, dont `not_addressee` et `self_decision`, gardés tels quels (contrat ADR-019).
*Alternative :* passer `not_addressee` en 403 pour les agents. Écartée : le contrat change sans gain.

**D9 — `X-Nexus-Actor` devient facultatif et vérifié.** S'il est présent, il doit égaler l'acteur du jeton, sinon `403 actor_mismatch`. Même règle pour `body.actor` dans `POST /api/events` : le 422 actuel entre en-tête et corps devient ce 403.

## 2. Matrice appliquée

Groupes (`nexus/actors.py`) : HUMANS = {loic} ; NODE_AGENTS = {helios, mnema, aether, artemis} ; EXECUTORS = {claude, codex, orca, **hermes**}. Hermes est absent de §3 ; lecture proposée : c'est un exécutant (ADR-013).

| Route | loic | agent de nœud | exécutant | Refus |
|---|---|---|---|---|
| tous les `GET /api/…`, sauf health | ✓ | ✓ | ✓ | 401 seulement |
| `POST /api/tasks` | ✓ | ✓ | ✓, `lead_agent` ∈ {soi, null}, `collaborators` ⊆ {soi} | 403 `assign_forbidden` |
| `PATCH /api/tasks/{ref}` | ✓ | ✓ | ✓, si `lead_agent` ou `collaborators` **changent** : seulement vers soi, ou rendre la main à un humain | 403 `assign_forbidden` |
| `POST …/status` | ✓ | ✓ sauf `dropped` | ✓ sauf `dropped` | 403 `human_only` |
| `POST …/comments` | ✓ | ✓ | ✓ | — |
| `PUT` / `DELETE …/dependencies/…` | ✓ | ✓ | ✓ | — |
| `POST /api/events` | `actor` = acteur du jeton | idem | idem ; effet `handoff` vers un autre agent : non appliqué | 403 `actor_mismatch` ; effet `applied: false` + raison |
| effet `claimed` (soi = agent principal) | ✓ | ✓ | ✓ | — |
| `POST /api/approvals/{ref}/answer`, `/decision` | si destinataire | 409 `not_addressee` | 409 `not_addressee` | inchangé |

Ambiguïtés de §3 et lecture proposée :
- **Assigner** : changer `lead_agent` ou `collaborators`, par le corps, par `PATCH` ou par les effets `claimed` et `handoff`. « — » pour les exécutants veut dire : ils ne s'assignent qu'eux-mêmes et ne peuvent que rendre la main à un humain. On ne contrôle que ce qui **change**, pour qu'un exécutant puisse éditer le titre d'une tâche menée par un autre agent. Un `handoff` interdit reste un événement enregistré, l'effet est seulement refusé, comme dans `_apply_effects`.
- **Exécuter** : c'est le « confier à » de la Phase 2 (ADR-012, réservé à Loïc), qui n'a encore aucune route. Un changement de statut n'est pas une exécution. La future route sera `human_only`.
- **Supprimer** : aucune route ne supprime une tâche. `DELETE …/dependencies` délie, c'est tracé et réversible : autorisé à tous. Lecture proposée : abandonner une tâche (`dropped`) est la suppression du produit, donc réservée aux humains. Un agent propose l'abandon par `needs_human`.
- **Publier/Envoyer sur validation** : aucune route aujourd'hui ; les approbations (ADR-019) sont déjà le mécanisme.
- **Artémis « son périmètre »** : le modèle n'a pas de notion de périmètre. Artémis lit comme les autres en Phase 1, à revoir à son intégration (v2, ADR-008).

## 3. Découpage en PR

1. **`feat/16-actor-tokens`** : migration `0005_actor_tokens` (réversible par `drop_table`), modèle `ActorToken`, `nexus/auth/tokens.py` (`generate`, `digest`, `verify`), CLI `nexus-token`, motif `nxt_` dans `nexus/secrets.py` et règle `.gitleaks.toml`. La dépendance `authenticated_actor` dans `nexus/auth/deps.py` accepte un jeton s'il est présent (401 si invalide), sinon garde le comportement actuel. Docs : ADR-020, SECURITY §1/§3. **Porte la migration, `.gitleaks.toml` et `DECISIONS.md` : fusion seulement sur « fusionne » de Loïc.**
2. **`feat/16-ui-token`** : écran de déverrouillage, `Authorization` dans `web/src/api.ts:request`, `ApiError` 401 qui renvoie à l'écran, configuration globale Playwright qui émet un jeton `loic` dans le dossier de données de test et le place dans `storageState`. `demo_agent` lit `NEXUS_TOKEN` ou `--token-file`.
3. **`feat/16-enforce-matrix`** : jeton obligatoire (dépendance au niveau des routeurs, `health` exclu), suppression de `DEFAULT_ACTOR` et de l'ancien `get_actor`, D9, middleware `Host`, refus de bind hors loopback, `nexus/permissions.py` (fonctions pures comme `tasks/rules.py`, appelées depuis `tasks/service.py` et `events/service.py:_apply_effects`), tests par acteur. Docs : SECURITY §3 (matrice appliquée et limite), EVENT-PROTOCOL (en-tête, codes), ARCHITECTURE §7 (#47 : CORS autorise `Authorization`).

## 4. Cas limites à tester d'abord

- **Secrets.** Le jeton n'apparaît ni dans le journal d'accès, ni dans les lignes WebSocket d'uvicorn, ni dans un 401/422. Le fichier `nexus.db` et ses sauvegardes ne contiennent jamais le texte clair. `nxt_…` collé dans un commentaire ou un événement est masqué. `list` n'affiche ni jeton ni fragment. Les faux jetons des tests sont construits à l'exécution (`"nxt_" + "A" * 43`).
- **Validation.** `Bearer` absent, vide, schéma `Basic`, valeur non ASCII ou de 10 000 caractères : 401, jamais 500, sans recopie. Jeton révoqué : 401 dès la requête suivante. `X-Nexus-Actor` ou `body.actor` qui diffère du jeton : 403. Après PR 3, l'en-tête seul sans jeton donne 401 : plus jamais `loic` par défaut.
- **Invariant de couverture.** Un test parcourt `app.routes` et exige l'authentification sur toute route hors liste blanche (`/api/health`, `/api/ws`), comme `test_provenance_contract.py` pour les GET. Une route ajoutée sans jeton fait échouer la CI.
- **Matrice.** Tests paramétrés sur `ACTORS`. Un exécutant qui nomme un autre agent dans `lead_agent` ou `collaborators` reçoit 403. Un `PATCH` qui ne change pas `lead_agent` passe. `claimed` par un exécutant est appliqué. `handoff` d'un exécutant vers codex : effet refusé ; vers loic : appliqué. `dropped` par un agent : 403. Un agent qui décide une approbation : 409 `not_addressee` (inchangé).
- **Host.** `evil.example` : refusé en REST et WebSocket. `[::1]:8765` et `localhost:5173` (proxy Vite) : admis. `TestClient` envoie `testserver` : le fixture fixe `base_url="http://127.0.0.1"`.
- **Concurrence.** Une révocation qui croise une requête en cours est acceptée (l'authentification précède la révocation). `nexus-token` qui écrit pendant que le serveur tourne. CLI sur une base non migrée : elle refuse et dit de lancer Nexus une fois, sans migrer elle-même.
- **Provenance.** `created_by`, `TaskHistory.actor`, `Event.actor` et `decided_by` sont l'acteur du jeton.
- **UI.** Un 401 renvoie à l'écran verrouillé, jamais à un chargement sans fin. Le jeton n'est jamais affiché. Le WebSocket reconnecte après déverrouillage.

## 5. Documents

- **ADR-020** « Authentification des acteurs par jeton porteur local » (D1 à D9). Ajouter une précision à ADR-019 D5 : « depuis ADR-020, l'acteur est authentifié ; le contrôle reste un 409 ».
- **SECURITY** : §1 (une empreinte n'est pas un secret), §3 (mécanisme, matrice appliquée, limite du même compte OS), §6 (émission et révocation tracées dans `actor_tokens`).
- **AGENTS.md** : section Development, « après `pnpm bootstrap`, émettre un jeton `loic` (`uv run --directory server nexus-token issue loic --label navigateur`) » et faux jetons construits à l'exécution.
- **EVENT-PROTOCOL** et **ARCHITECTURE §7** comme indiqué en PR 3.
- **Issues de suivi** : ticket WebSocket avant tout bind hors loopback ; `last_used_at` limité en fréquence pour repérer un jeton volé.
