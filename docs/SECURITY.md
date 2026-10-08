# SECURITY — Nexus

**Version :** 0.1 (draft à valider)
**Date :** 2026-09-28

---

## 1. Règle d'or des secrets

> **Aucun secret n'est jamais conservé, affiché, transmis ou journalisé.**

- Toute valeur sensible (token, mot de passe, clé, code 2FA) est remplacée par `[REDACTED]` — dans les docs, logs, bases, exports, captures et messages.
- Contrôles d'existence **uniquement** : on vérifie qu'une clé est présente, jamais sa valeur (`grep -l`, comptage de longueur, présence de fichier).
- Les credentials restent dans leurs coffres (vault local, ACL fichiers, registre de credentials) — jamais dans Nexus.
- Un secret qui apparaît quelque part est un **incident** (§7), pas une fatalité.
- **Une empreinte n'est pas un secret** (ADR-020) : Nexus ne garde des jetons d'acteur que leur SHA-256 (`actor_tokens.token_hash`). Elle ne permet ni de s'authentifier ni de retrouver le jeton (256 bits d'entropie) ; elle peut donc figurer dans la base et ses sauvegardes. Le jeton en clair, lui, n'est jamais stocké, journalisé ni renvoyé : `nxt_…` collé dans un texte est masqué comme tout secret.

## 2. Classification des données

| Niveau | Exemples | Règle |
|---|---|---|
| Public | docs projet, inspirations | libre |
| Interne | tâches, runs, quotas, planning | local uniquement |
| Sensible | mails, conversations (chats, sessions), identités, finances | local, accès restreint, minimisation, jamais exporté |
| Secret | tokens, clés, mots de passe | jamais stocké — coffre uniquement |

## 3. Matrice de permissions (cible ; la partie appliquée par #16 est détaillée plus bas)

| Acteur \ Action | Lire | Commenter | Créer tâche | Assigner | Exécuter | Publier/Envoyer | Supprimer |
|---|---|---|---|---|---|---|---|
| Loïc | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (lui-même) | ✓ |
| Helios | ✓ | ✓ | ✓ | ✓ | ✓ | sur validation | ✗ |
| Mnēma / Aether | ✓ | ✓ | ✓ | ✓ | ✓ (leur nœud) | sur validation | ✗ |
| Artémis | ✓ (son périmètre) | ✓ | ✓ | ✓ | ✓ (usine) | sur validation | ✗ |
| Claude / Codex / Orca / Hermes | ✓ | ✓ | ✓ | — | ✓ (tâches confiées) | sur validation | ✗ |

- **Suppression** : jamais par un agent. Seul Loïc supprime — ou un script explicitement validé par lui.
- **Exécution** : chaque agent exécute dans son périmètre de nœud et ses permissions locales existantes (inchangées par Nexus).
- **Qui décide d'une approbation** (#26, ADR-019) : seul un destinataire **humain** de la demande (`needs`) peut y répondre ou la trancher ; un autre acteur est refusé en **409** `not_addressee`, et le demandeur qui tranche sa propre demande en **409** `self_decision` (règle de cohérence, pas un 403 : `POST /api/approvals/<ref>/answer` et `/decision`). **Contrôle de cohérence, pas de sécurité :** depuis ADR-020 l'acteur est authentifié par son jeton (ci-dessous), mais ce refus reste un 409 de cohérence (le contrat d'ADR-019 ne change pas). Reste vrai : un agent ne peut pas publier lui-même un événement `answer` (réservé à Nexus, `POST /api/events` le refuse), et une réponse masque les secrets comme tout événement. La `consequence` d'une demande est annoncée par le demandeur et non vérifiée (ADR-005).
- **Authentification des acteurs** (#16, ADR-020) : **le jeton est exigé** sur toute route REST, lectures comprises, sauf `GET /api/health` ; la documentation OpenAPI (`/openapi.json`, `/docs*`, `/redoc`) reste ouverte (schéma de l'API seulement, aucune donnée de Nexus ; protégés du DNS rebinding par le contrôle `Host`). Un acteur s'authentifie par un jeton porteur `Authorization: Bearer nxt_…`, émis par `nexus-token issue <acteur> --label <texte>` et révocable par `nexus-token revoke nx-tok-<n>` (effet dès la requête suivante). L'acteur est celui du jeton, jamais un en-tête déclaré : sans jeton, `X-Nexus-Actor` seul ne donne rien (401). Un `Authorization` absent ou mal formé donne 401 `auth_required` (avec `WWW-Authenticate: Bearer`), un jeton inconnu ou révoqué 401 `invalid_token` (même réponse dans les deux cas), et rien de ce qui est reçu n'est recopié dans la réponse. `X-Nexus-Actor` reste facultatif mais, s'il est présent, il doit égaler l'acteur du jeton, comme l'`actor` d'un événement : sinon 403 `actor_mismatch`. Le **WebSocket** `/api/ws` ne porte pas de jeton en Phase 1 (il n'envoie que des références et des types) : il est protégé par les contrôles `Origin` et `Host`, et `NEXUS_HOST` doit rester sur la boucle locale tant qu'un ticket WebSocket n'existe pas (#57 ; Nexus refuse de démarrer sinon). Un test parcourt toutes les routes et échoue si l'une répond sans jeton hors de cette liste (`/api/health`, `/api/ws` et la documentation OpenAPI). L'interface demande le jeton de `loic` sur l'écran « Nexus verrouillé » (VIEWS §9) ; elle le garde en clair dans le `localStorage` du navigateur, jamais affiché ni journalisé. `demo_agent` lit `NEXUS_TOKEN` ou `--token-file`.
- **Contrôle de l'en-tête `Host`** (DNS rebinding, ADR-020 D6) : HTTP comme WebSocket n'admettent que `localhost`, `127.0.0.1` et `::1` (tout port, IPv6 entre crochets compris) et les noms de `NEXUS_ALLOWED_HOSTS` (liste séparée par des virgules, noms ou adresses seuls, sans port ni joker). Tout autre `Host` reçoit `400` `invalid_host` (le WebSocket est refusé à la poignée de main, en 403), avant toute authentification, sans recopier la valeur.
- **Matrice appliquée** (`server/src/nexus/permissions.py`, fonctions pures appelées par les services de tâches et d'événements) : trois groupes d'acteurs, **humains** (`loic`), **agents de nœud** (`helios`, `mnema`, `aether`, `artemis`) et **exécutants** (`claude`, `codex`, `orca`, `hermes`). Un refus de droit est un **403** `{"detail": {"code", "message"}}` ; il ne nomme que le champ, jamais la valeur reçue.

| Action | Humain | Agent de nœud | Exécutant | Refus |
|---|---|---|---|---|
| Lire (tous les `GET /api/…` sauf health et la documentation OpenAPI), commenter, lier ou délier une dépendance, changer de statut sauf `dropped` | ✓ | ✓ | ✓ | 401 seulement |
| `POST /api/tasks` : `lead_agent`, `collaborators` | libres | libres | `lead_agent` ∈ {soi, vide}, `collaborators` ⊆ {soi} | 403 `assign_forbidden` |
| `PATCH /api/tasks/<ref>` : `lead_agent`, `collaborators` | libres | libres | seulement ce qui **change** : vers soi, vers un humain ou à personne (`lead_agent`) ; ajouter soi ou un humain (`collaborators`) | 403 `assign_forbidden` |
| `POST …/status` vers `dropped` | ✓ | ✗ | ✗ | 403 `human_only` |
| `POST /api/events` | `actor` = acteur du jeton | idem | idem | 403 `actor_mismatch` |
| effet `claimed` | l'émetteur devient agent principal | idem | idem (il ne désigne que lui-même) | — |
| effet `handoff` | appliqué vers n'importe qui | idem | appliqué vers un humain, ou si l'agent principal ne change pas (seule la prochaine action change) ; vers un autre agent : événement enregistré, effet non appliqué (`applied: false` + raison) | pas d'erreur |
| `POST /api/approvals/<ref>/answer`, `/decision` | si destinataire | 409 `not_addressee` | 409 `not_addressee` | inchangé (ADR-019) |

Un changement d'assignation n'est contrôlé que s'il **change** quelque chose : un exécutant peut renommer une tâche menée par un autre agent. Abandonner une tâche (`dropped`) est la « suppression » du produit, donc réservée aux humains : un agent propose l'abandon par un événement `needs_human`. Aucune route ne supprime une tâche, ni ne confie une exécution (ADR-012) ; la future route « confier à » sera réservée aux humains.
- **Limite assumée :** un processus qui tourne sous le compte OS de Loïc peut lire un jeton (fichier, `localStorage`) ou en émettre un avec `nexus-token`. Les jetons arrêtent les pages web, les pairs du tailnet et l'erreur d'un agent qui utilise un autre jeton que le sien ; ils n'arrêtent pas un agent local déterminé à tricher : seule une séparation des comptes OS le ferait.
- **« Confier à »** : depuis Nexus, seul Loïc déclenche l'exécution d'une tâche par un agent (ADR-012) ; un agent peut le proposer (`needs_human`), jamais le déclencher lui-même via Nexus.

## 4. Actions gated (go humain explicite, à chaque fois)

- Envoi de mail, envoi de message à un tiers humain, publication (réseaux, web), achat/dépense, suppression de données,
- Création ou modification d'un événement d'agenda partagé,
- Déploiement/service permanent, modification de config critique (routing, gateways, backups),
- Toute mutation touchant un autre nœud que le sien,
- Toute bascule de modèle/provider payant.

Format d'une demande de validation : **quoi · pourquoi · conséquence · plan de retour**. Une validation vaut pour l'action décrite — pas pour la suivante.

## 5. Frontière par nœud

- Chaque nœud applique ses changements **par son gardien local** (Helios, Mnēma/Cortex, Aether/Synapse, Artémis).
- Phase actuelle : lecture distante uniquement (Tailscale/SSH read-only) ; aucune mutation croisée.
- Une intervention croisée se demande, se justifie, se sauvegarde, se relit — jamais de modification silencieuse.

## 6. Audit & traçabilité

- L'émission et la révocation d'un jeton sont tracées dans `actor_tokens` (`created_at`, `revoked_at`, `label`) : une ligne n'est jamais supprimée, seulement révoquée.
- Les événements sont **immuables** (on corrige par un nouvel événement, jamais par réécriture).
- Chaque mutation : qui, quoi, quand, avant/après (si applicable), preuve de read-back.
- Les logs Nexus ne contiennent jamais de secret ; un contrôle automatique peut scanner les écritures (pattern tokens/clés) et bloquer.

## 7. Incidents

1. **Détecter** (scan, audit périodique, signalement d'agent).
2. **Contenir** (stopper l'écriture concernée, ne pas propager).
3. **Nettoyer** : rédaction (`[REDACTED]`), rotation si un secret a été exposé (décidée par Loïc).
4. **Rapporter** : quoi, où, impact, correction, leçon — dans le journal des décisions si durable.
5. **Vérifier** : read-back du nettoyage.

## 8. Bonnes pratiques vérifiées à conserver

- Agents finance : lecture seule, secrets sous ACL fichiers (jamais en base).
- Scopes OAuth minimaux ; toute extension de scope = validation explicite.
- Comptes de messagerie (WhatsApp, Telegram) : aucun mode d'accès qui mette en danger le compte personnel de Loïc sans décision explicite (voir INTEGRATIONS §3, risque de bannissement WhatsApp).
- Toute ouverture réseau entrante (ex. webhook WhatsApp) : limitée à un seul endpoint, signature vérifiée, décision explicite.
- Backups avant mutation (règle Nexus « réversible ») — ex. : sauvegarde config avant toute modification de routing.
- Les dashboards existants gardent leurs propres accès — Nexus ne les contourne pas.

## 9. Ce que Nexus ne fera jamais

- Stocker un secret, même « temporairement » ou « chiffré maison ».
- Envoyer/publier/dépenser sans go explicite.
- Lancer un agent sans action explicite de Loïc.
- Fermer une tâche sans preuve lisible.
- Exposer une surface d'administration hors de la machine locale.
- Prendre une décision à la place de Loïc (il propose, Loïc tranche).
