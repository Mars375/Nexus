# DECISIONS — Journal des décisions (ADR)

Format : chaque décision = contexte · décision · conséquences · statut.
Toute décision structurante s'ajoute ici.

---

## ADR-001 — Nom du système : Nexus

- **Date :** 2026-09-27 (confirmé par Loïc)
- **Contexte :** un nom avait déjà été donné à l'ensemble des agents et composants ; « Orion Cockpit » était proposé mais rejeté (« ce ne sera pas Orion cockpit »).
- **Décision :** le système s'appelle **Nexus**. Il englobe Helios, Mnēma/Cortex, Aether/Synapse, Artémis (même éteint), ainsi que les exécutants Claude, Codex, Orca, Hermes.
- **Conséquences :** ce dépôt (`F:/Projet/Nexus`), ses docs et son futur code portent ce nom ; « Orion Cockpit » est abandonné partout.
- **Statut :** accepté.

## ADR-002 — Nexus est une surcouche ; Hermes Kanban reste le moteur

- **Date :** 2026-09-28
- **Contexte :** audit lecture seule du 27/09 : Hermes Kanban est une machine d'états complète (SQLite multi-boards, dispatcher 60 s, runs, workers, reclaim/retry, review auto) ; le board `default` est vide.
- **Décision :** les tâches exécutables vivent dans Hermes ; Nexus lit, corrèle, affiche, et n'écrit que via les surfaces natives (outils Kanban, events/comments) avec read-back. Pas de file parallèle, pas de seconde base de vérité.
- **Conséquences :** le MVP est read-only ; toute duplication de données est interdite ; la base locale de Nexus (si créée) est un index reconstructible.
- **Statut :** **remplacé par ADR-011 et ADR-013** (2026-09-28) — Hermes Kanban exécute automatiquement ses tâches par des agents ; il ne peut pas porter les tâches de Loïc sans violer ADR-003.

## ADR-003 — Aucun LLM requis pour l'usage de base

- **Date :** 2026-09-28
- **Contexte :** besoin explicite : « le kanban n'a pas besoin de lancer un appel LLM » ; les quotas/coûts doivent rester maîtrisés (zéro paiement par défaut).
- **Décision :** consulter, créer, déplacer, commenter, valider ne consomme aucun appel LLM. L'exécution LLM est une capacité **optionnelle** des tâches, portée par Hermes.
- **Conséquences :** les vues doivent être utiles à 100 % même sans aucun modèle disponible.
- **Statut :** accepté.

## ADR-004 — Une seule opération principale, portée par Nexus

- **Date :** 2026-09-28
- **Contexte :** `max_in_progress` n'est pas configuré côté Hermes (vérifié : `None`) ; la politique « une tâche en cours » doit vivre quelque part.
- **Décision :** Nexus affiche et applique la règle : au plus **une** tâche `main` par humain ; les autres tâches actives sont marquées `auxiliary`.
- **Conséquences :** les vues Maintenant/Travail distinguent explicitement main vs auxiliary ; aucune limite n'est imposée au dispatcher Hermes pour l'instant.
- **Statut :** accepté.

## ADR-005 — `unknown` reste `unknown`

- **Date :** 2026-09-28
- **Contexte :** des états non vérifiables existent en permanence (nœud éteint, run non confirmé, quota non mesuré).
- **Décision :** tout état non vérifié s'affiche `unknown` avec sa dernière date de contrôle. Jamais de valeur par défaut qui masque l'incertitude ; jamais de « OK » supposé.
- **Conséquences :** les vues acceptent et montrent l'incertitude comme une information de premier ordre ; un nœud éteint volontairement (Artémis) est `offline-by-design`, pas `unknown` ni « en panne ».
- **Statut :** accepté.

## ADR-006 — Aucun secret stocké, jamais

- **Date :** 2026-09-28
- **Contexte :** règle historique du Nexus (finance en lecture seule, « jamais de mot de passe dans le chat »).
- **Décision :** aucun token/mot de passe/clé n'est conservé, journalisé, affiché ou transmis ; `[REDACTED]` partout ; contrôles de présence uniquement. Les coffres existants (vault, ACL) restent seuls dépositaires.
- **Conséquences :** les intégrations Nexus ne manipulent jamais de valeurs sensibles ; un secret exposé = incident (voir SECURITY §7).
- **Exception (2026-10-13, #57) :** le corps du refus 400 que websockets renvoie à une poignée de main mal formée recopie l'en-tête `Sec-WebSocket-Protocol`, ticket WebSocket compris, vers son seul expéditeur ; accepté, voir ADR-021.
- **Statut :** accepté.

## ADR-007 — Agréger sans dupliquer ; références vers Synapse et Mnēma

- **Date :** 2026-09-28
- **Contexte :** Mnēma et Synapse ont déjà leurs dashboards ; Loïc ne veut pas de duplication (« pas besoin de dashboard de synapse et Mnema vu qu'on a déjà un dashboard… une ref dedans »).
- **Décision :** Nexus fournit des **références contextuelles** (liens, états, fraîcheur) vers ces dashboards ; il ne recopie ni leurs données ni leurs vues.
- **Conséquences :** chaque source garde sa surface ; Nexus reste la couche de corrélation.
- **Statut :** **remplacé par ADR-016** (2026-09-28) — Nexus doit être la seule application ouverte ; les informations utiles de Mnēma et Synapse s'affichent dans Nexus.

## ADR-008 — Artémis inclus dans le modèle, éteint dans les faits

- **Date :** 2026-09-28
- **Contexte :** « Faut ajouter aussi Artémis » ; « Artemis est éteint c'est normal ».
- **Décision :** Artémis fait partie du périmètre conceptuel de Nexus (état, productions à terme) ; son extinction actuelle est volontaire et n'est pas un incident à résoudre. Aucun démarrage sans décision explicite.
- **Conséquences :** les vues affichent son état `offline-by-design` ; l'intégration produit est planifiée en v2.
- **Statut :** accepté.

## ADR-009 — Documentation en français, identifiants techniques en anglais

- **Date :** 2026-09-28
- **Décision :** tous les documents Nexus sont en français (lecture Loïc) ; les identifiants de code, champs, enums et noms de fichiers techniques restent en anglais.
- **Conséquences :** cohérence avec l'existant (Phases Hexapod/LHY, etc.).
- **Précision (2026-10-03) :** les commentaires et docstrings du code sont aussi en anglais, sur demande de Loïc ; on traduit ceux qu'un changement touche, sans traduction en masse.
- **Statut :** accepté.

## ADR-010 — Frontière par nœud : chaque gardien chez lui

- **Date :** 2026-09-28
- **Contexte :** règle établie du Nexus (« action autonome par nœud, gardien local, frontières explicites »).
- **Décision :** un changement sur un nœud est appliqué par son gardien (Helios, Mnēma, Aether, Artémis) ; Nexus et les autres nœuds restent en lecture jusqu'à demande explicite. Lecture distante : Tailscale/SSH read-only.
- **Conséquences :** pas de mutation croisée silencieuse ; toute intervention croisée se demande et se trace.
- **Statut :** accepté.

## ADR-011 — Nexus est une application autonome, le centre de contrôle unique

- **Date :** 2026-09-28 (décidé par Loïc)
- **Contexte :** relecture de la documentation de Hermes Kanban (`website/docs/user-guide/features/kanban.md`) : c'est une file de travail **pour agents**. Chaque tâche a un `assignee` qui est un profil d'agent ; en `ready`, le dispatcher lance un worker (appel LLM) ; en `triage`, le décomposeur automatique (actif sur Helios) appelle un LLM ; en `review`, un agent relecteur est lancé. Y placer les tâches de Loïc contredit ADR-003. Loïc : « je ne veux pas que Nexus soit une copie d'un truc […] je veux que Nexus devienne quelque chose d'indépendant, mais que ce soit notre centre de contrôle, la seule app que l'on veut utiliser ».
- **Décision :** Nexus est une application autonome, avec son propre modèle et ses propres données (`nexus.db`). Il n'est ni une surcouche ni une copie d'un outil existant. Les outils existants sont branchés derrière des adaptateurs remplaçables.
- **Conséquences :** ADR-002 et ADR-007 sont remplacées ; le MVP n'est plus un « pont lecture Hermes » mais le noyau de Nexus (tableau, vue Maintenant, API d'événements).
- **Statut :** accepté.

## ADR-012 — Les tâches vivent dans Nexus ; aucune exécution automatique

- **Date :** 2026-09-28
- **Décision :** `nexus.db` est la source de vérité des tâches de coordination (celles de Loïc comme celles des agents), de leurs événements, approbations et décisions. Une tâche Nexus n'est **jamais** exécutée automatiquement : « confier à » un agent est une action explicite, qui crée un run chez l'exécutant choisi.
- **Conséquences :** les statuts de tâche sont propres à Nexus (DATA-MODEL §3) ; les statuts des exécutants sont lus au niveau du run.
- **Statut :** accepté.

## ADR-013 — Hermes est un exécutant parmi d'autres

- **Date :** 2026-09-28
- **Contexte :** Helios, Mnēma et Aether tournent sur Hermes ; son dispatcher gère claim, heartbeat, reprise et retries. Le remplacer coûterait cher sans gain.
- **Décision :** Hermes est branché derrière un adaptateur d'exécution, au même rang que Claude Code, Codex et Orca. Confier une tâche à Helios, Mnēma ou Aether crée une tâche côté Hermes ; Nexus suit le run et relit le résultat.
- **Conséquences :** Nexus ne dépend pas de Hermes pour fonctionner ; si Hermes change, seul l'adaptateur change.
- **Statut :** accepté.

## ADR-014 — Stack : FastAPI + SQLite + UI web locale

- **Date :** 2026-09-28 (décidé par Loïc)
- **Décision :** serveur Python (FastAPI), base SQLite (`nexus.db`), UI web servie en local. Patterns API + WebSocket repris du dashboard Hermes quand ils servent.
- **Conséquences :** framework front et application desktop : ADR-017.
- **Statut :** accepté.

## ADR-015 — Deux façons pour un agent de travailler avec Nexus

- **Date :** 2026-09-28 (décidé par Loïc)
- **Décision :** (a) Nexus lance un agent sur action explicite de Loïc (« confier à ») et suit son run ; (b) un agent lancé ailleurs (terminal, Telegram, Hermes) se déclare dans Nexus via l'API d'événements.
- **Conséquences :** l'API d'événements est publique en local dès la Phase 1 ; les adaptateurs d'exécution arrivent en Phase 2.
- **Statut :** accepté.

## ADR-016 — La seule application : Nexus absorbe les surfaces utiles

- **Date :** 2026-09-28 (décidé par Loïc)
- **Décision :** Nexus affiche et permet d'agir sur : les chats (lecture des conversations existantes et discussion avec les agents), les mails et l'agenda, Git et le code, la mémoire (Mnēma/Hindsight) et l'infrastructure (Synapse, nœuds, quotas). Les données externes restent chez leur propriétaire : Nexus les lit, les indexe si besoin, et agit via l'adaptateur — il n'en devient pas la source.
- **Conséquences :** toute action sortante (envoi de mail, message, publication) reste gated (SECURITY §4).
- **Statut :** accepté.

## ADR-017 — Front : React + TypeScript + Vite ; application Windows via Tauri

- **Date :** 2026-09-28 (Loïc : « on va prendre le meilleur, sachant qu'on va sûrement basculer sur une app Windows complète »)
- **Contexte :** Nexus commence en UI web locale mais doit pouvoir devenir une vraie application Windows sans réécriture.
- **Décision :** UI en **React + TypeScript + Vite** (écosystème le plus large : composants, drag-and-drop pour le tableau, gestion d'état serveur, tests). Cible desktop : **Tauri 2**, qui embarque la même UI dans WebView2 (natif sur Windows 11) et lance le serveur FastAPI comme processus « sidecar ».
- **Conséquences :** l'UI ne dépend d'aucune API propre au navigateur qui empêcherait l'encapsulation ; tout passe par l'API FastAPI. La bascule desktop apporte icône de barre des tâches, notifications Windows et démarrage automatique, sans réécrire l'UI. Alternative de repli si Tauri bloque : Electron (même UI, binaire plus lourd).
- **Statut :** accepté.

## ADR-018 — Canaux de messagerie : tous, WhatsApp compris

- **Date :** 2026-09-28 (Loïc : « on va tout faire, y compris WhatsApp, ça peut aider pour booker des rendez-vous »)
- **Décision :** Nexus lit et envoie sur plusieurs canaux, chacun derrière son adaptateur : chat natif Nexus, gateway Hermes (agents de nœud), Telegram, WhatsApp, mail. Usages : parler aux agents, et contacter des tiers (ex. prise de rendez-vous).
- **Conséquences :** tout message vers un tiers humain est gated (SECURITY §4). WhatsApp impose des contraintes à trancher en Phase 3 (INTEGRATIONS §3) : l'API officielle (WhatsApp Business Cloud API) exige un numéro dédié, des modèles de message approuvés pour initier une conversation hors fenêtre de 24 h, et un webhook entrant joignable depuis Internet ; les bibliothèques non officielles utilisent le numéro personnel mais violent les conditions de WhatsApp (risque de bannissement).
- **Statut :** accepté.

## ADR-019 — Approbations : une table d'état légère, un journal immuable, une échéance calculée

- **Date :** 2026-10-07 (décidé par Loïc, issue #26 « Approbations et réponses depuis Maintenant »)
- **Contexte :** DATA-MODEL §2.10 prévoyait un objet `Approval`, mais Maintenant (#6) ne montrait que les `question` et `needs_human` reçus, « jamais étiquetés en attente : on ne sait pas encore si elles sont traitées ». Pour répondre et valider depuis Nexus, il faut savoir si une demande est traitée, sans réécrire un événement (immuable, DATA-MODEL §5 règle 3) ni créer une seconde source de vérité du contenu (ADR-012). Nexus ne réveille aucun agent : l'agent doit pouvoir venir lire la décision.
- **Décision :** une **table d'état légère** `approvals` (`nx-appr-<n>`) à côté du **journal immuable** des événements. L'approbation ne porte que l'état de décision (`status`, `expires_at`, lien vers l'événement de demande et, plus tard, de réponse, `version`) ; le contenu (sujet, détail, demandeur, tâche, options, `consequence`) se lit dans l'événement de demande. La décision est un événement (journal), son effet sur l'état est la table. L'échéance est **calculée à la lecture** avec l'horloge du serveur, jamais écrite. Neuf choix, pris par Loïc sur recommandation de l'architecte :
  1. **D1** — une seule table pour les questions et les approbations, avec `ask_kind` (`question` ou `needs_human`). Quatre statuts stockés : `pending`, `approved`, `rejected`, `answered` ; `expired` s'y ajoute à la lecture, calculé, jamais stocké (D4).
  2. **D2** — la décision est binaire (`approved` / `rejected`) ; approuver un `needs_human` qui propose au moins 2 options exige `choice` (l'indice de l'option). Implémenté avec l'écriture des décisions (étape suivante).
  3. **D3** — `payload.consequence` est **obligatoire** pour tout **nouveau** `needs_human` (409 `consequence_required`), facultative pour une `question`, 1 000 caractères au plus. Un renvoi identique d'un ancien événement reste une relecture. Elle est **annoncée par le demandeur et non vérifiée par Nexus** (ADR-005) : l'interface dit « annoncée par <agent> ».
  4. **D4** — `payload.expires_at` facultatif, fixé par l'agent, sans valeur par défaut, de 1 minute à 30 jours après la réception ; le statut `expired` est **calculé** (`expires_at <= maintenant`, UTC) et jamais stocké.
  5. **D5** — seuls les destinataires humains décident ; un autre acteur est refusé en 409, pas 403. Contrôle de cohérence, **pas de la sécurité** : l'acteur n'est que déclaré jusqu'à #16 (SECURITY §3). *Depuis ADR-020 (PR 3, #60), l'acteur est authentifié par son jeton sur les routes de réponse et de décision ; le refus reste un 409 de cohérence.*
  6. **D6** — pas de rétroremplissage : les demandes antérieures à la migration 0004 n'ont pas d'approbation.
  7. **D7** — Maintenant liste les demandes en attente de tout âge et les traitées des 7 derniers jours ; la tuile compte les demandes en attente (spec Maintenant, décision 2 révisée).
  8. **D8** — un nouveau `kind` `answer`, réservé à Nexus, est refusé dans `POST /api/events` : un agent ne peut pas fabriquer une réponse de Loïc.
  9. **D9** — pas de statut « retirée » : une demande dépassée se corrige par un nouvel événement.
- **Conséquences :** migration `0004` (table `approvals`, sans rétroremplissage, réversible par `drop_table`) ; l'événement de demande consigne l'effet `approval` avec la référence ; l'agent relit `GET /api/approvals/<ref>` jusqu'à la fin de l'attente, valider ne déclenche rien chez lui (ADR-012, EVENT-PROTOCOL §6 ter) ; la création et la lecture arrivent avant l'écriture des réponses (PR en trois temps : modèle et lecture, réponses et décisions avec `/api/now`, interface). Contrepartie : une demande sans échéance attend sans limite, et une approbation « expirée » peut encore être tranchée si le produit le décide, puisque rien n'est écrit à l'échéance.
- **Statut :** accepté.

## ADR-020 — Authentification des acteurs par jeton porteur local

- **Date :** 2026-10-07 (décidé par Loïc, issue #16 ; conception : `docs/superpowers/specs/2026-10-07-actor-auth-design.md`)
- **Contexte :** l'acteur d'une requête n'est que déclaré (`X-Nexus-Actor`, `loic` par défaut) : une page web, un pair du tailnet ou un agent peut se faire passer pour Loïc. Les agents locaux tournent sous le même compte Windows que lui.
- **Décision :** un jeton porteur par acteur, dont Nexus ne garde que l'empreinte. Neuf choix, pris par Loïc sur recommandation :
  1. **D1** — `Authorization: Bearer nxt_<43 caractères base64url>` (32 octets de `secrets.token_bytes`) ; l'acteur se déduit du jeton, jamais d'un en-tête déclaratif.
  2. **D2** — table `actor_tokens` (`id`, `actor`, `label`, `token_hash` SHA-256 unique, `created_at`, `revoked_at`) ; ni sel ni hachage lent (256 bits d'entropie) ; recherche par empreinte puis `hmac.compare_digest`, sans cache : une révocation vaut à la requête suivante. Une empreinte n'est pas un secret.
  3. **D3** — provisionnement par la CLI locale `nexus-token` (`issue`, `list`, `revoke nx-tok-<n>`) ; le jeton n'est affiché qu'une fois ; plusieurs jetons par acteur ; la CLI ne migre jamais la base.
  4. **D4** — l'interface s'authentifie comme `loic` avec un jeton envoyé dans `Authorization` (pas de cookie : pas de CSRF, compatible Tauri).
  5. **D5** — jeton exigé sur toute route REST sauf `GET /api/health` ; la documentation OpenAPI (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) reste ouverte (schéma de l'API seulement, aucune donnée de Nexus). WebSocket sans jeton en Phase 1 (références et types seulement, contrôles `Origin` et `Host`) ; tant qu'un ticket WebSocket n'existe pas (#57), `NEXUS_HOST` doit rester sur la boucle locale et Nexus refuse de démarrer sinon. **Limite assumée :** un processus sous le compte OS de Loïc peut lire un jeton ou en émettre un ; le mécanisme arrête les pages web, les pairs du tailnet et l'erreur d'un agent, pas un agent local décidé à tricher. *Depuis #57 (PR A, #72), le WebSocket exige un ticket à usage unique, obtenu avec un jeton porteur (voir ADR-021) ; depuis ADR-021, le bind hors boucle locale est permis dans ses limites.*
  6. **D6** — contrôle de `Host` contre le DNS rebinding (middleware maison, le plus externe, `400 invalid_host` avant toute authentification) : seuls `localhost`, `127.0.0.1`, `::1` et les noms ou adresses de `NEXUS_ALLOWED_HOSTS` passent ; plusieurs en-têtes `Host` sont refusés ; le WebSocket est refusé à la poignée de main (fermeture 1008, vue par le client comme un HTTP 403). *(Depuis ADR-021 D11, les adresses IP de `NEXUS_HOST` passent aussi.)*
  7. **D7** — déploiement en trois PR sans drapeau de contournement : jeton accepté s'il est présent, puis envoyé par l'interface, puis exigé partout.
  8. **D8** — `401 auth_required` (absent ou mal formé), `401 invalid_token` (inconnu ou révoqué, même message), `403` pour un droit que l'acteur n'a jamais (`actor_mismatch`, `assign_forbidden`, `human_only`), `409` pour une règle d'état (codes existants, dont `not_addressee`).
  9. **D9** — `X-Nexus-Actor` devient facultatif et vérifié : s'il diffère de l'acteur du jeton, `403 actor_mismatch` ; de même pour `body.actor` dans `POST /api/events`.
- **Conséquences :** trois PR. PR 1 (migration `0005`, réversible par `drop_table`, modèle `ActorToken`, `nexus/auth/{tokens,deps,cli}.py`, motif `nxt_` dans `nexus/secrets.py` et règle gitleaks) accepte un jeton s'il est présent. PR 2 : écran « Nexus verrouillé » et jeton dans `request()` côté interface, `demo_agent` qui lit `NEXUS_TOKEN` ou `--token-file`. PR 3 (#60) exige le jeton, contrôle `Host` et applique la matrice de SECURITY §3 (`nexus/permissions.py`, fonctions pures). Contrepartie : le jeton vit en clair chez l'agent, la contrainte sur `actor` dans la base impose une migration pour ajouter un acteur, et le premier démarrage demande d'émettre le jeton de `loic` (README).
- **Règles d'application de la matrice** (PR 3) : les trois premières précisent la conception du 2026-10-07 ; seule l'ouverture de la documentation OpenAPI s'en écarte (la conception n'ouvrait que `/api/health` et `/api/ws`), ce que Loïc a validé le 2026-10-08 sur recommandation de l'agent :
  - `PATCH /api/tasks/<ref>` ne contrôle que les champs d'assignation qui **changent** : un exécutant peut renommer une tâche menée par un autre agent ;
  - abandonner une tâche (`dropped`) est réservé aux humains (403 `human_only`) : c'est la « suppression » du produit ;
  - un `handoff` d'un exécutant vers un autre agent qui n'est pas déjà l'agent principal est enregistré sans effet (`applied: false` et sa raison), pas refusé ; vers un humain, ou vers l'agent principal actuel (un autre acteur que l'émetteur) avec une nouvelle prochaine action, il s'applique (s'il ne change rien, l'effet est noté non appliqué, `applied: false` ; un handoff vers soi-même est refusé en 409 `handoff_to_self`, comme avant) ;
  - la documentation OpenAPI reste ouverte (D5).
- **Statut :** accepté.

## ADR-021 — Ticket WebSocket et écoute sur le tailnet

- **Date :** 2026-10-08 (décidé par Loïc, issue #57 ; compléments du 2026-10-13 ; conception : `docs/superpowers/specs/2026-10-08-ws-ticket-design.md`)
- **Contexte :** les agents des autres nœuds doivent pouvoir écrire dans Nexus par l'API (ADR-015), qui n'écoutait que la boucle locale (ADR-020 D5). Le REST est fermé par jeton (ADR-020), mais `/api/ws` ne contrôlait que `Origin` et `Host` : sur le tailnet, son flux (références, types, curseurs) aurait été lisible sans authentification. Une adresse de `100.64.0.0/10` peut aussi appartenir à un opérateur (CGNAT) plutôt qu'à Tailscale, et sous Linux une socket liée à l'adresse du tailnet accepte un paquet arrivé par une autre interface (modèle d'hôte faible).
- **Décision :** douze choix, pris par Loïc sur recommandation le 2026-10-08 et complétés le 2026-10-13 :
  1. **D1** — Nexus peut écouter sur le tailnet de Loïc, jamais sur un réseau local ni sur Internet (`tailscale funnel` interdit, `tailscale serve` déconseillé).
  2. **D2** — le ticket voyage dans `Sec-WebSocket-Protocol`, jamais dans l'URL : le client offre `['nexus.live.v1', ticket]`, le serveur accepte `nexus.live.v1` et ne renvoie jamais le ticket.
  3. **D3** — `nxw_` + 43 caractères base64url (32 octets aléatoires), à usage unique, valable 30 s sur l'horloge monotone et sur l'horloge murale en UTC : il expire dès que l'une des deux dit 30 s.
  4. **D4** — tickets en mémoire, dans le processus, indexés par leur empreinte SHA-256 ; au plus 16 en attente par jeton, le plus ancien évincé ; pas de migration ; un seul processus serveur.
  5. **D5** — le ticket est lié au jeton qui l'a demandé : un jeton révoqué, ou une ligne `actor_tokens` absente, le fait refuser. Le flux n'est pas filtré par acteur.
  6. **D6** — un WebSocket ouvert revérifie son jeton à chaque tour de lecture et se ferme en 4401 « jeton révoqué ».
  7. **D7** — tout refus avant l'acceptation est une fermeture 1008 sans raison (HTTP 403 pour le client), sans distinguer les cas.
  8. **D8** — un client hors navigateur passe aussi par le ticket ; aucun `Authorization` à la poignée de main.
  9. **D9** — `NEXUS_HOST` n'admet que la boucle locale (`127.0.0.1`, `localhost`, `::1`) et des adresses IP littérales du tailnet (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) : ni joker, ni nom DNS, ni port, crochets ou zone, ni IPv4 dans IPv6 ; le refus ne recopie pas la valeur. Complément du 2026-10-13 : avant chaque bind de l'adresse du tailnet, puis à chaque tour tant qu'elle est servie, Nexus vérifie auprès de Tailscale (`tailscale status --json --peers=false`) que l'état est `Running` et que l'adresse est l'une de celles du nœud. Sinon, pas de bind, ou fermeture de l'écoute : le contrôle échoue fermé.
  10. **D10** — `NEXUS_HOST` est une liste d'au plus une entrée de boucle locale (`127.0.0.1` ajouté d'office) et une adresse du tailnet, servies par un seul `uvicorn.Server`. La boucle locale démarre sans attendre Tailscale ; l'écoute du tailnet s'ouvre au premier tour d'une tâche de surveillance, qui la retente toutes les 30 s tant qu'elle manque, sans redémarrage. Complément du 2026-10-13 : la même tâche reprend une écoute perdue en service, boucle locale comprise ; au démarrage, un échec de bind de la boucle locale reste fatal. Chaque échec s'écrit en WARNING une fois par changement d'état, sans l'adresse. `nexus-dev` reste limité à la boucle locale.
  11. **D11** — les adresses IP de `NEXUS_HOST` sont admises d'office dans le contrôle de `Host` ; un nom MagicDNS reste à déclarer dans `NEXUS_ALLOWED_HOSTS`.
  12. **D12** — deux PR : le ticket exigé et son envoi par l'interface (PR A), puis l'écoute sur le tailnet (PR B).
- **Conséquences :** PR A (#72) : `POST /api/ws-ticket`, `nexus/auth/tickets.py`, poignée de main et revérification dans `live.py`, filtre des journaux DEBUG et TRACE, motif `nxw_` ; elle inscrit sous ADR-006 l'exception de l'écho du refus 400 de websockets (l'écho ne va qu'à l'expéditeur, qui détient déjà le ticket ; ni un navigateur ni le client websockets ne peuvent produire l'en-tête mal formé ; le ticket est à usage unique et vit 30 s au plus). PR B (#74) : `NEXUS_HOST` en liste, `nexus/serving.py` (un seul serveur, surveillance et reprise des écoutes), contrôle auprès de Tailscale (`nodes.run_tailscale_self`), D11 dans `app.py`. SECURITY §3, §5 et §9 sont révisés (D1). Une règle de pare-feu qui n'accepte le port que sur l'interface Tailscale et la boucle locale est **recommandée, non imposée par le code** (décision du 2026-10-13) : le contrôle auprès de Tailscale dit à qui appartient l'adresse, pas par quelle interface arrive un paquet. Limites assumées : le contrôle fait confiance au binaire `tailscale` local (ADR-020 D5) ; une adresse qui change de main reste écoutée 42 s au plus, et les connexions acceptées avant une fermeture continuent (jeton et ticket restent exigés) ; un seul processus serveur ; la surveillance s'appuie sur des attributs non documentés d'uvicorn, gardés par des tests de vrai serveur à relancer à chaque montée de version ; la reprise sous Windows, le modèle d'hôte fort et les règles de l'invite « python.exe » restent à vérifier sur Helios.
- **Statut :** accepté.

## ADR-022 — Une tâche terminée ne se modifie plus ; on corrige dans une tâche de suite

- **Date :** 2026-10-13 (décidé par Loïc, issue #65 ; conception : `docs/superpowers/specs/2026-10-13-done-task-readonly-design.md`)
- **Contexte :** `done → in_progress` permettait de rouvrir une tâche close, donc de réécrire ce qui a été livré et prouvé ; l'interface invitait à rouvrir pour joindre une preuve, et un agent qui ouvrait un run sur une tâche close la rouvrait.
- **Décision :** `done` est final. Aucune transition n'en sort ; ni champ, ni dépendance de la tâche, ni agent principal, collaborateurs ou prochaine action ne change (409 `task_done`, contrôlé seulement si la requête change quelque chose). Restent possibles : commenter, et compléter les preuves (ajout seul, `POST /api/tasks/<ref>/evidence`, ou `done` d'un agent avec preuve). Un problème trouvé ensuite se règle dans une nouvelle tâche, qui peut porter le lien facultatif `follows` (« suite de nx-task-N ») vers une tâche `done` seulement ; ce lien n'est pas une dépendance. `dropped → backlog` reste permis. Les tâches déjà closes passent en lecture seule sans réécriture, et les dépendances sur elles restent résolues. Les événements d'agents sur une tâche close restent enregistrés ; leurs effets sont consignés non appliqués avec la raison.
- **Conséquences :** migration `0006` (colonne `tasks.follows_id`, clé étrangère `ON DELETE SET NULL`, index ; ajoutée par `add_column(…, inline_references=True)` et réversible par `drop_column`, sans mode batch, qui, clés étrangères actives, viderait les tables liées ; le modèle déclare la clé sans `ondelete`, que SQLAlchemy ne relit pas sur une référence de colonne) ; `reopen_with_advanced_dependents` ne concerne plus que `dropped → backlog` ; une erreur sur une tâche close ne se corrige plus en place ; `demo_agent` relancé sur une tâche close sort avec le code 4 sans rien publier.
- **Statut :** accepté.

---

## Décisions ouvertes

- **Accès WhatsApp** : API officielle (numéro dédié) vs non officielle (numéro perso, risque de ban) ; exposition du webhook entrant (ex. tunnel limité à cet endpoint) — Phase 3 (ADR-018).
- **Périmètre mail** : boîtes couvertes, règles de confidentialité (INTEGRATIONS §5).
- **Cadence des rapports** : quotidien, hebdo, ou les deux (PRD §13).
- **Critère « attend Loïc »** : relance automatique vs attente passive (PRD §13).
