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

## 3. Matrice de permissions (cible)

| Acteur \ Action | Lire | Commenter | Créer tâche | Assigner | Exécuter | Publier/Envoyer | Supprimer |
|---|---|---|---|---|---|---|---|
| Loïc | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (lui-même) | ✓ |
| Helios | ✓ | ✓ | ✓ | ✓ | ✓ | sur validation | ✗ |
| Mnēma / Aether | ✓ | ✓ | ✓ | ✓ | ✓ (leur nœud) | sur validation | ✗ |
| Artémis | ✓ (son périmètre) | ✓ | ✓ | ✓ | ✓ (usine) | sur validation | ✗ |
| Claude / Codex / Orca | ✓ | ✓ | ✓ | — | ✓ (tâches confiées) | sur validation | ✗ |

- **Suppression** : jamais par un agent. Seul Loïc supprime — ou un script explicitement validé par lui.
- **Exécution** : chaque agent exécute dans son périmètre de nœud et ses permissions locales existantes (inchangées par Nexus).
- **Qui décide d'une approbation** (#26, ADR-019) : seul un destinataire **humain** de la demande (`needs`) peut y répondre ou la trancher ; un autre acteur est refusé en **409** `not_addressee`, et le demandeur qui tranche sa propre demande en **409** `self_decision` (règle de cohérence, pas un 403 : `POST /api/approvals/<ref>/answer` et `/decision`). **Limite assumée : c'est un contrôle de cohérence, pas de la sécurité.** Tant que le jeton n'est pas exigé (#16, ADR-020 D7), l'acteur peut n'être que **déclaré** (en-tête `X-Nexus-Actor`, `loic` par défaut) : quiconque joint l'API locale peut se déclarer `loic`. Le contrôle évite les erreurs (un agent qui « valide » sa propre demande par accident), il n'arrête pas un acteur malveillant : celui qui joint l'API peut aussi écrire `X-Nexus-Actor: loic` et valider. Ce qui reste vrai sans authentification : un agent ne peut pas publier lui-même un événement `answer` (réservé à Nexus, `POST /api/events` le refuse), et une réponse masque les secrets comme tout événement. La `consequence` d'une demande est annoncée par le demandeur et non vérifiée (ADR-005).
- **Authentification des acteurs** (#16, ADR-020) : un acteur s'authentifie par un jeton porteur `Authorization: Bearer nxt_…`, émis par `nexus-token issue <acteur> --label <texte>` et révocable par `nexus-token revoke nx-tok-<n>` (effet dès la requête suivante). Sur les routes qui écrivent et consignent un acteur (`POST`, `PATCH`, `PUT` et `DELETE` sous `/api/tasks`, `POST /api/events`, `POST /api/approvals/<ref>/answer` et `/decision`), un en-tête `Authorization` mal formé donne 401 `auth_required`, un jeton inconnu ou révoqué 401 `invalid_token`, et un `X-Nexus-Actor` (ou l'`actor` d'un événement) qui diffère de l'acteur du jeton 403 `actor_mismatch`. **État actuel (PR 1 et 2 de #16) : le jeton est accepté mais pas exigé** ; les lectures (`GET`) et le WebSocket ignorent encore l'en-tête `Authorization`, et sans cet en-tête l'acteur reste déclaré : la limite ci-dessus s'applique entièrement. L'interface envoie déjà le jeton qu'on lui donne (prévu : celui de `loic`, émis par `nexus-token issue loic` ; l'interface ne vérifie pas son acteur) ; il est gardé en clair dans le `localStorage` du navigateur, jamais affiché ni journalisé, et `demo_agent` lit `NEXUS_TOKEN` ou `--token-file`. L'exigence arrive avec la troisième PR de #16 (ADR-020, D7). **Limite assumée, même après :** un processus qui tourne sous le compte OS de Loïc peut lire un jeton (fichier, `localStorage`) ou en émettre un avec `nexus-token`. Les jetons arrêtent les pages web, les pairs du tailnet et l'erreur d'un agent qui se trompe d'identité, pas un agent local déterminé : seule une séparation des comptes OS le ferait.
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
