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
  2. **D2** — table `actor_tokens` (`id`, `actor`, `label`, `token_hash` SHA-256 unique, `created_at`, `revoked_at`) ; ni sel ni hachage lent (256 bits d'entropie) ; recherche par empreinte puis `hmac.compare_digest`, sans cache : une révocation vaut à la requête suivante. Une empreinte n'est pas un secret. *(Depuis #58, la colonne nullable `last_used_at` enregistre la dernière requête authentifiée (jeton valide et acteur d'en-tête concordant ; une route qui refuse ensuite la demande ne l'efface pas), au plus une fois par 5 minutes ; elle ne sert qu'au diagnostic — repérer un jeton oublié ou volé — et jamais à l'authentification.)*
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

## ADR-023 — Confier du travail : une table `runs`, un adaptateur par exécutant, un superviseur dans le serveur

- **Date :** 2026-11-05 (cadrage de la Phase 2 par `architect` ; les cinq décisions de Loïc ci-dessous sont les recommandations de l'architecte, retenues sur la consigne « suis tes recommandations » et relisibles dans la PR)
- **Contexte :** la Phase 2 doit permettre à Loïc de confier une tâche à un agent depuis Nexus et d'en suivre l'histoire sans copie manuelle. Aujourd'hui un run n'existe que dans les événements (`events/runs.py`, référence libre par acteur et par tâche) : rien ne porte la référence externe, l'annulation ni la reprise. Aucun LLM ne doit être lancé sans action explicite de Loïc (ADR-012).
- **Décision :**
  1. **D1** — une table `runs` (`nx-run-<n>`) met en œuvre l'entité Run de DATA-MODEL §2.5, à côté du journal immuable des événements, comme ADR-019 pour les approbations. Pas d'entité « dispatch » séparée. L'unicité `(dispatched_by, client_key)` rend un double clic idempotent ; un index unique partiel sur `(task_id, agent)` pour les statuts actifs traduit en base la règle « un seul run actif par agent et par tâche ».
  2. **D2** — seul un humain confie une tâche ou annule un run (`check_dispatch`, 403 `human_only`). Les événements du run sont publiés par l'adaptateur avec `run = nx-run-<n>` et `origin` = nom de l'adaptateur, par `publish()` : `RUN_CLOSERS`, l'anti-bruit et la règle de la tâche `done` (ADR-022) s'appliquent sans changement. Le préfixe `nx-run-` est réservé : une référence `nx-run-<n>` doit exister pour la même tâche et pour le même **signataire** que le run (`runs.executor` : l'acteur qui signe les événements de l'adaptateur), sinon 409 `run_unknown`. Le champ `runs.agent` est l'agent à qui le travail est confié (`helios` pour un run Hermes, `codex` pour Codex) ; la règle « un seul run actif » porte sur `(task_id, agent)`, le contrôle de signature sur `executor`. Les identifiants d'événement sont dérivés (`nx-run-<n>-<seq>`) et `at` est l'instant natif : un rejeu est une relecture.
  3. **D3** — un adaptateur (`Protocol` : `probe`, `dispatch`, `watch`, `cancel`, `recover`) par exécutant ; la traduction natif → événement est une fonction pure testée sur des fixtures. Le **watcher tourne dans le processus serveur** (superviseur `asyncio` du lifespan, comme `nodes_loop` et `backup_loop`) ; le processus enfant se lance par `subprocess.Popen` dans `asyncio.to_thread`, jamais par un shell. Au redémarrage, tout run non terminé passe en `unknown` avec un événement « suivi perdu au redémarrage » (ADR-005) ; rien n'est relancé seul.
  4. **D4** — **Qui raconte le run :** l'adaptateur seul traduit la sortie de l'exécutant ; l'enfant ne reçoit aucun jeton Nexus (écart assumé avec INTEGRATIONS §A.2). Son environnement est filtré par liste blanche (ni `NEXUS_*` ni les clés du shell de Loïc) ; le brief passe par l'entrée standard, jamais en argument, et ne reprend que les champs écrits par Loïc, pas les commentaires d'agents. Un jeton par run (émis au dispatch, révoqué à la clôture) reste possible plus tard, avec un amendement à ADR-020.
  5. **D5** — **Qui signe les événements Hermes :** `hermes`, exécutant soumis à la matrice restreinte (SECURITY §3), pas `helios` : signer `helios` donnerait aux métadonnées Hermes les droits d'un agent de nœud. Un run confié à Helios via Hermes a donc `agent = helios` et `executor = hermes` ; ses événements sont signés `hermes` et passent le contrôle de D2 par `executor`.
  6. **D6** — **Dossier de travail Codex :** une liste de dépôts configurée (`NEXUS_RUN_WORKDIRS`), un worktree et une branche `nexus/nx-run-<n>` par run, `--sandbox workspace-write`, jamais le contournement du bac à sable ni le dépôt d'où tourne le serveur. Nexus ne pousse ni ne fusionne. « DONE ≠ preuve » : à la création du worktree, l'adaptateur enregistre le commit de départ ; à la clôture il relit la preuve lui-même et exige que le commit produit existe (`git rev-parse`), descende du commit de départ (`git merge-base --is-ancestor <départ> <produit>`) et lui soit postérieur (`git rev-list --count <départ>..<produit>` > 0, car `rev-parse` réussit aussi pour le commit de départ). Sans preuve ainsi relue, le run finit en `review`.
  7. **D7** — **Garde-fous :** au plus un run actif par exécutant ; durée maximale (60 min par défaut) au-delà de laquelle le processus est tué et le run passe en `failed` ; aucune relance automatique. Pour Hermes : un board `nexus` créé par Loïc, tâches posées directement en `ready` (pas de décomposeur), politique de relecture et de nouvelles tentatives confirmée avant l'adaptateur.
  8. **D8** — Codex d'abord (un seul processus, contrôlable, testable avec un faux exécutable `NEXUS_CODEX_BIN`), Hermes ensuite, Claude Code après décision de Loïc sur l'abonnement, Orca reporté (CLI absente). Aucune CI ne lance un vrai LLM : la preuve de bout en bout est un run que Loïc déclenche lui-même.
- **Conséquences :** migration `0008_runs`, `nexus/runs/` et `nexus/adapters/` (`events/service.py` et `tasks/service.py` sont proches de 400 lignes), routes `POST /api/tasks/{ref}/runs`, `POST /api/runs/{ref}/cancel`, `GET /api/runs/{ref}`, `GET /api/tasks/{ref}/runs` (409 `executor_unavailable` sans adaptateur configuré ; 409 d'avance si `working` serait refusé : tâche `done`, sans prochaine action, autre tâche principale en cours, dépendance non traitée). Découpage en PR indépendantes, chacune depuis `master` : modèle et superviseur ; adaptateur Codex ; « Confier à » dans l'interface ; historique par carte ; relevé Hermes v0.22.5 puis adaptateur Hermes ; Claude Code ; Orca.
- **Statut :** accepté.

### Addendum (2026-11-11) — ADR-023 D7 précisé pour Hermes

Décidé par l'agent sous le feu vert du 2026-11-11, puis **confirmé par Loïc le 2026-11-11** (`--max-retries 1` et relecture Hermes intérieure au run ; cadrage : `docs/superpowers/specs/2026-11-11-adaptateur-hermes-design.md`, §6 et §11) :

- `--max-retries 1` : le premier échec ferme le run en `failed`, aucune relance automatique.
- La relecture de Hermes (`review_dispatch`) reste une étape intérieure du run (`progress`), bornée par la durée maximale ; un `review` Hermes n'est jamais un `review` Nexus.
- Les fins autres que `done` (`blocked`, `gave_up`, durée maximale) archivent la tâche Hermes, pour qu'elle ne travaille pas hors de Nexus à côté d'un nouveau run.
- La preuve d'un `done` est une pièce jointe recopiée par Hermes (`uploaded_by` `kanban_complete` ou `kanban_request_review`) et relue sur le disque ; sinon `review`.
- L'agent `helios` correspond au profil Hermes `default`.
- Le comportement de D3 au redémarrage est inchangé (le run passe `unknown`, Loïc l'annule). Reprendre le suivi serait un vrai écart à D3 : addendum distinct, hors du lot G.

### Addendum (2026-11-11) — Claude Code comme exécutant, modèle choisi à chaque run (lot H)

Décidé par Loïc le 2026-11-11 (cadrage : `docs/superpowers/specs/2026-11-11-adaptateur-claude-code-design.md`) :

- Nexus peut confier une tâche à Claude Code (`claude -p`), avec le modèle choisi à chaque run
  parmi `haiku`, `sonnet` et `opus` dans « Confier à ». Chaque run consomme l'abonnement Claude
  de Loïc.
- **Exception à la règle du 2026-10-17** (AGENTS.md, « Model routing » : les modèles Claude ne sont
  consommés que par le fil principal de Claude Code et les subagents de `.claude/agents/`) : un run
  de l'adaptateur `claude-code` consomme lui aussi l'abonnement. Les tests n'utilisent qu'un faux
  exécutable (D8) ; aucune CI ne lance de run réel. La règle reste entière pour tout autre harnais.

Choix du cadrage, pris par l'agent sous le feu vert de Loïc du 2026-11-11 et **à confirmer par lui**
(chacun se change sans migration) :

- Un run réel est confié depuis Nexus par un humain (D2) : Loïc, ou l'agent principal avec le jeton
  de navigateur de Loïc et sur sa consigne.
- L'exécutant est l'acteur existant `claude`, qui ne sert que l'agent `claude` ; l'`origin` des
  événements est `claude-code`.
- `runs.model` (migration `0009`) : exigé pour `claude` (409 `model_required`), refusé pour les
  autres exécutants (409 `model_not_for_executor`), sans défaut côté serveur ; `NULL` pour les runs
  antérieurs.
- D4, D6 et D7 s'appliquent sans changement (environnement par liste blanche, brief sur l'entrée
  standard, worktree et preuve par commit, un run actif par exécutant, durée maximale, aucune
  relance). En plus : session isolée (`--restricted`, aucun MCP, ni hooks ni réglages de Loïc,
  vérifiée sur la ligne `system/init`), Bash réduit à `git status`, `git add` et `git commit`,
  hooks git coupés par l'environnement de l'enfant. Sonnet est présélectionné dans « Confier à ».

### Addendum (2026-11-12) — Claude Code sans Bash, commit fait par Nexus (lot H2)

Cadrage : `docs/superpowers/specs/2026-11-11-adaptateur-claude-code-design.md` (§4 et §5.4 ; issue
#185 ; implémentation : #183, branche `feat/183-adaptateur-claude-code`).

**Décidé par Loïc le 2026-11-12 :**

- Un run de l'adaptateur `claude-code` n'a **aucun outil qui exécute une commande** : seulement
  `Read`, `Edit`, `Write`, `Glob` et `Grep` (`--tools`), dans le worktree du run. Cette puce remplace
  « Bash réduit à `git status`, `git add` et `git commit` » de l'addendum du 2026-11-11 : un relevé
  réel a montré que des options de ces commandes lisent un fichier hors du worktree et en renvoient
  le contenu au modèle (le fournisseur du modèle le recevrait).
- **Nexus fait le commit** à la fin d'un run réussi (ligne `result` en succès, code 0, isolement
  vérifié, processus réellement terminé), depuis le processus serveur : `git add -A` puis
  `git commit` avec un message fixe (référence du run et alias du modèle), l'identité git du dépôt
  figée avant le lancement, configuration système et globale coupées, hooks, `fsmonitor`, signature
  et maintenance automatique coupés, `GIT_DIR` imposé. Le module (`run_commit.py`) ne connaît aucun
  exécutant : Codex pourra l'appeler plus tard (spec, §14, hors de ce lot).
- Le modèle reste choisi à chaque run (décision du 2026-11-11, inchangée par ce lot).
- D6 inchangé : la preuve est un commit qui descend du commit de départ, relu depuis le dépôt ; aucun
  commit après une annulation, une durée maximale, un échec, une violation d'isolement ou un
  redémarrage.

**Lecture de l'agent, pas une décision de Loïc sur cet adaptateur :** le choix `unelevated` de Loïc
(2026-11-12) porte sur le bac à sable de Codex sous Windows (#186) ; l'adaptateur `claude-code` n'a
aucun réglage de bac à sable (pas de Bash).

**Choix du cadrage, pris par l'agent et en attente de la confirmation de Loïc** (chacun se change
sans migration) :

- **Attribution** : auteur et committer = l'identité git du dépôt ; trailers `Nexus-Run`,
  `Nexus-Executor`, `Nexus-Model` ; **pas** de `Co-Authored-By: Claude …`.
- **Un refus de Nexus (dépôt git imbriqué, lien ou point de jonction ou lien physique, fichier trop
  gros, pilote de filtre) termine le run en `failed`**, avec sa cause en mots fixes ; les fichiers
  restent dans le worktree, rien n'est commité. **Aucun changement** termine le run en `review`.
- **Plafond de 20 Mio** par fichier ajouté ou modifié ; aucun plafond total (le budget de 90 s du
  commit le borne).
- **Dépôts refusés** : pilote de filtre dans la configuration locale du dépôt (Git LFS déclaré
  localement), refusé au lancement ; dépôt qui extrait de vrais liens symboliques
  (`core.symlinks=true`), chaque commit y serait refusé.
- **Identité git exigée par dépôt** (locale ou globale), lue avant le lancement ; sans elle, le run
  est `failed` « lancement impossible » et rien n'est créé.

**Confirmés le 2026-11-25** (choisi par l'agent sous la délégation totale de Loïc du 2026-11-25,
ADR-024) : les cinq choix ci-dessus restent tels quels ; douze runs réels (#190) n'en ont mis aucun
en défaut. « Confier à » garde son comportement actuel, sans code nouveau : il présélectionne le
premier exécutant de `GET /api/executors`, qui les trie par nom ; quand l'adaptateur `claude-code` est
enregistré (`NEXUS_CLAUDE_BIN` réglé, au moins un dépôt admissible dans `NEXUS_RUN_WORKDIRS`, sonde
réussie), c'est donc `claude` (adaptateur `claude-code`), avec Sonnet comme modèle. Loïc change d'exécutant ou de modèle dans le
dialogue avant de confier ; un autre ordre se décidera s'il gêne à l'usage.

### Addendum (2026-11-13) — Codex : bac à sable `unelevated`, commit fait par Nexus, configuration de Loïc tenue à l'écart

Cadrage : `docs/superpowers/specs/2026-11-13-codex-commit-par-nexus-design.md` (issue #186).
Implémentation en cinq PR (§9 du cadrage), livrées une à une : l'état est suivi dans #186.

**Décidé par Loïc le 2026-11-12** (#186) : Nexus passe `windows.sandbox=unelevated` à **ses** runs
Codex, sous Windows seulement ; sa propre configuration (`[windows] sandbox = "elevated"`) ne change
pas.

**Choisi par l'agent sous la délégation de Loïc du 2026-11-13** (« Je te laisse gérer en vrai ce
que tu préfères niveau option », en réponse aux options laissées ouvertes, dont celle du commit) — ce n'est pas Loïc qui a choisi entre les
options ; il peut l'infirmer :

- **Nexus commite pour Codex** à la fin d'un tour réussi, par `run_commit` (comme pour
  `claude-code`) ; l'agent ne commite plus (sous le bac à sable, il ne le peut pas : `index.lock`
  refusé le 2026-11-12). **Pas de clone par run** : il laisserait l'agent choisir l'auteur des
  commits, rendrait modifiable le fichier `alternates` du clone, coûterait un nettoyage par run et
  un amendement de D6, sans régler l'arrêt de l'arbre de processus. D6 inchangé : la preuve est un
  commit qui descend du départ, relu depuis le dépôt.

**Choix du cadrage, pris par l'agent et en attente de la confirmation de Loïc** (hors de cette
délégation ; chacun se change sans migration) :

- Avant le commit de Nexus : arrêt **confirmé** de tout l'arbre par un *job object* Windows
  (`KILL_ON_JOB_CLOSE`, sans sortie autorisée), repris pour
  `claude-code` ; la branche doit être restée au départ et le fichier `.git` du worktree inchangé,
  sinon `failed` sans commit. Sous POSIX, un groupe de processus vidé ne confirme pas l'arrêt
  d'un descendant sorti du groupe : l'exécutant `codex` n'y est pas enregistré, sauf
  `NEXUS_RUN_WEAK_CONTAINMENT=1` (faux exécutable des tests, jamais un vrai run).
- **Configuration de Loïc hors des runs** : un `CODEX_HOME` propre à Nexus
  (`<NEXUS_DATA_DIR>/codex-home`, où Loïc se connecte une fois ; Nexus ne lit ni ne copie la
  connexion), `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, bloc des skills retiré de
  l'entrée du modèle, hooks, plugins, connecteurs, navigateur, mémoires et recherche de skills
  coupés ; contrôle fermé avant le lancement (`codex mcp list --json` vide, aucun bloc de skills
  dans `codex debug prompt-input`) ; un `mcp_tool_call` pendant le run le termine en `failed`.
- Dépôts et `CODEX_HOME` de Nexus refusés sous le dossier temporaire de l'enfant (`%TEMP%`, `/tmp`).
- Fins alignées sur `claude-code` : refus de Nexus → `failed`, aucun changement → `review` ;
  auteur = l'identité git du dépôt, trailers `Nexus-Run` et `Nexus-Executor: codex`.

### Addendum (2026-11-20) — Codex : un dépôt qui a une configuration de projet `.codex` est refusé

Cadrage : `docs/superpowers/specs/2026-11-13-codex-commit-par-nexus-design.md`, §11, Q5 (issue #186, PR C).

**Choisi par l'agent sous la délégation de Loïc du 2026-11-13** — ce n'est pas Loïc qui a choisi ;
il peut l'infirmer :

- **Contexte :** on ne sait pas si une configuration de projet (`.codex/` à la racine du dépôt)
  peut déclarer des serveurs MCP ou des hooks dans un run non interactif, ni si
  `codex mcp list` la voit ; le contrôle avant le lancement ne pourrait donc pas la juger.
- **Décision :** un dépôt dont le worktree a une entrée `.codex` à sa racine (dossier, fichier ou
  lien) est refusé au lancement (échec fermé) : `failed` « lancement impossible », sans modèle,
  worktree et branche retirés.
- **Conséquences :** un dépôt qui range une configuration Codex ne peut pas être confié à Codex
  par Nexus. La règle se revoit quand un run réel aura montré ce qu'une configuration de projet
  peut déclarer en non interactif (§10 du cadrage).

### Addendum (2026-11-23) — Codex : l'entrée de confiance de `codex exec` est acceptée, le `.codex` du dépôt principal est refusé

Cadrage : `docs/superpowers/specs/2026-11-23-codex-home-confiance-design.md` (issue #186), qui
répond à §11, Q12 du cadrage du 2026-11-13.

**Choisi par l'agent sous la délégation de Loïc du 2026-11-13** — ce n'est pas Loïc qui a choisi ;
il peut l'infirmer :

- **Contexte :** chaque `codex exec` (0.167.1) écrit dans son `CODEX_HOME` un `config.toml` qui ne
  contient que `[projects.'<dépôt principal>']` / `trust_level = "trusted"`, et aucune option ne
  l'en empêche. La règle 1 du §5.3 refusait tout `config.toml` : après un premier run, tous les
  suivants étaient refusés (condition d'arrêt de Q12). L'entrée ne change pas le démarrage du run (lancé
  avec `--ignore-user-config` ; plus tard dans le tour, non vérifié : les refus du `.codex` le
  couvrent), mais les contrôles chargent alors la configuration de projet `.codex`
  du worktree et lisent celle du dépôt principal pour les hooks.
- **Décision :** un `config.toml` est accepté seulement s'il ne contient que des entrées de
  confiance : fichier ordinaire d'au plus 64 Kio, UTF-8 strict, TOML lisible, exactement
  `{"projects": P}` avec `P` non vide, chaque valeur exactement `trust_level = "trusted"` ou
  `"untrusted"`, chaque clé égale (sans casse sous Windows) à la racine d'un dépôt de
  `NEXUS_RUN_WORKDIRS`. Tout le reste est refusé comme avant, avec le même message fixe ; un
  `*.config.toml` reste toujours refusé. Une entrée `.codex` à la racine du **dépôt principal**
  (suivie par git ou non) est refusée avant la création du worktree ; celle du worktree le reste.
  Nexus n'écrit ni ne nettoie rien dans ce dossier.
- **Conséquences :** les runs Codex s'enchaînent. Un dépôt où Loïc garde une configuration Codex
  locale (`.codex` non suivi) ne peut plus être confié à Codex. Un dépôt retiré, déplacé ou
  renommé après un run laisse une clé étrangère : tous les runs Codex sont refusés jusqu'à ce que
  Loïc retire la table de `<NEXUS_DATA_DIR>\codex-home\config.toml` (et supprime le fichier s'il ne
  reste aucune entrée : un fichier sans entrée est refusé aussi). Ce que `codex login` et un tour
  authentifié écrivent dans ce fichier est à relever au premier run connecté (noms de clés
  seulement) ; une autre clé y ferait de nouveau refuser les runs, et la règle s'ajusterait par une
  PR.

### Addendum (2026-11-25) — Codex : git de `codex.exe` hors du bac à sable

Cadrage : `docs/superpowers/specs/2026-11-25-codex-git-hors-bac-a-sable-design.md` (issue #186), qui
répond à §11, Q3 et à la condition d'arrêt de l'étape 0b du cadrage du 2026-11-13.

**Choisi par l'agent sous la délégation totale de Loïc du 2026-11-25** (ADR-024) — ce n'est pas
Loïc qui a choisi ; il peut l'infirmer :

- **Contexte :** au relevé 0b (run réel, codex-cli 0.167.1), `codex.exe` lance lui-même quatre git
  dans le worktree, hors du bac à sable, au début du tour et avant toute commande de l'agent
  (`rev-parse HEAD`, `remote -v`, `config --get core.fsmonitor`, `status --porcelain`), aucun à la
  fin. `git status` lance les pilotes de filtre `clean` et `process` : un `.gitattributes` suivi qui
  nomme un pilote défini dans la configuration système ou globale de Loïc (Git LFS, par exemple) le
  faisait lancer hors du bac à sable, sans aucune action de l'agent, alors que le contrôle de
  lancement ne lit que la configuration du dépôt.
- **Décision :** (A) l'enfant reçoit en plus `GIT_CONFIG_NOSYSTEM=1` et `GIT_CONFIG_GLOBAL` vers le
  périphérique nul : le git de `codex.exe` lit la même portée que `check_no_filter_driver` ; l'argv
  du run ne change pas. (B) Avant la création du worktree, `codex --version`, lancé contenu et borné
  avec l'environnement du run, doit écrire exactement une version de `MEASURED_VERSIONS`
  (`codex-cli 0.167.1`) ; sinon « lancement impossible », sans branche ni worktree. Une version
  s'ajoute seulement dans la PR qui joint un nouveau relevé 0b. Pas de `GIT_DIR` imposé : il
  casserait le git de l'agent dans tout autre dépôt et laisserait les sous-modules ouverts ; il reste
  un repli documenté (cadrage, §4.3) si un relevé montre du git de `codex.exe` après la première
  commande de l'agent.
- **Conséquences :** le git de l'agent, dans le bac à sable, n'a plus d'identité globale, de
  `credential.helper`, de `filter.lfs`, de `core.autocrlf` ni de `http.sslbackend` venus du système
  (HTTPS depuis git non vérifié). Un git de `codex.exe` lancé après la première commande de l'agent
  (fichier `.git` réécrit, sous-module) n'est pas couvert : il n'a pas été observé sur la 0.167.1, et
  chaque nouvelle version refait le relevé 0b avant d'être acceptée. Monter Codex de version sans ce
  relevé fait refuser tous les runs Codex.

### Addendum (2026-11-26) — Codex : bac à sable MXC strict, réseau sondé avant chaque run (#207)

Cadrage : `docs/superpowers/specs/2026-11-26-codex-reseau-design.md` (issue #207).

**Choisi par l'agent sous la délégation totale de Loïc du 2026-11-25** (ADR-024) — ce n'est pas
Loïc qui a choisi ; il peut l'infirmer. Ce choix amende celui de Loïc du 2026-11-12
(`windows.sandbox=unelevated`, addendum du 2026-11-13) :

- **Contexte :** sous `unelevated`, le « blocage réseau » de Codex se réduit à des variables de
  proxy vers `127.0.0.1:9` ; une commande de l'agent qui les ignore obtient une vraie réponse d'un
  hôte public (TCP brut, HTTP, HTTPS par OpenSSL, DNS), constaté le 2026-11-26 sous `codex sandbox`
  dans le job de Nexus, puis sous `exec` par un run réel. Aucun réglage `unelevated` essayé ne le
  change.
- **Décision :** sous Windows, Nexus passe `-c windows.sandbox=mxc` (MXC strict, jamais
  `prefer_mxc`, qui retombe sur l'ancien bac à sable quand MXC manque) et épingle
  `-c sandbox_workspace_write.network_access=false`, la même paire pour les contrôles et pour
  `exec`. `-c approval_policy=never` est épinglé partout : une commande escaladée tournerait hors
  du bac à sable. Avant chaque run, après les contrôles d'isolement, une sonde lancée dans le même
  bac à sable tente une connexion à `192.0.2.1:443` (TEST-NET-1) ; seule la sortie exacte
  `ERR 10013` avec le code 0 laisse partir le run, sinon « lancement impossible » en mots fixes,
  sans modèle et sans repli vers `unelevated`. La sortie n'est ni journalisée ni stockée.
- **Conséquences :** sous `codex sandbox`, MXC coupe le TCP sortant, le DNS et la boucle locale,
  sans droits d'administrateur, dans le job de Nexus, avec les mêmes refus d'écriture que
  `unelevated` (mesuré). Sous `exec`, la coupure est constatée par le run réel nx-run-19 du
  2026-11-27 (`codex-cli 0.167.1`, argv de Nexus) : la commande `TcpClient` de l'agent vers un hôte
  public sur le port 443 échoue avec le code 10013, une écriture hors du worktree et une écriture
  dans le dossier git commun sont refusées, et le run finit `done` avec un commit de Nexus. La
  sonde est passée avant ce run, et les contrôles d'isolement passent encore après lui. La règle
  « aucun run Codex sur un vrai dépôt ni sur un contenu que Loïc ne maîtrise pas » tient ; sa
  levée revient à Loïc. Une tâche qui a besoin de `localhost` (serveur local,
  Playwright) échouera sous MXC. Une mise à jour de Windows peut retirer MXC : la sonde refuse alors
  tous les runs Codex. Revenir à `unelevated` ne tient pas en une valeur de `WINDOWS_SANDBOX` :
  la sonde, qui exige `ERR 10013`, refuserait alors tous les runs (elle n'obtient qu'un délai
  dépassé sous `unelevated`) ; il faudrait aussi la retirer ou l'adapter, et ce retour rouvre le
  réseau des commandes de l'agent.

---

## ADR-024 — Délégation totale à l'agent (2026-11-25)

- **Contexte :** Loïc a demandé le 2026-11-25 que l'agent mène le projet jusqu'au bout sans avoir
  besoin de lui (« Délégation totale gère tout entièrement »). Jusque-là, il clôturait chaque phase
  (ROADMAP, règle 1), tranchait les choix produit ouverts et levait les blocages de fusion.
- **Décision :** l'agent (le fil principal de Claude Code, jamais un subagent ni un thread enfant)
  clôt les phases sur leur critère de sortie, preuves jointes dans la PR de clôture ; il tranche les
  décisions ouvertes et les choix produit, notés « choisi par l'agent sous la délégation totale de
  Loïc du 2026-11-25 », en prenant l'option la plus restreinte et la plus réversible quand le choix
  touche aux données de Loïc (lecture seule d'abord, périmètre minimal) ; il lève lui-même les cas où
  `AGENTS.md` lui faisait demander à Loïc (remarque non corrigée, relectures contradictoires, doute
  de périmètre), en notant sa raison dans la PR. Un CodeRabbit muet n'est plus un motif de demander à
  Loïc : l'agent relance la commande, et la PR attend sa relecture ou une limite explicite.
- **Ce qui reste à Loïc :** ses connexions et accès (`codex login`, OAuth Gmail, appairage WhatsApp,
  tout jeton), tout achat ou abonnement, l'usage d'un de ses vrais dépôts par un run réel (les runs
  restent sinon sur un dépôt jetable), la fusion d'une PR que ni l'agent ni un subagent ou
  thread enfant qu'il a lancé n'a ouverte dans sa conversation (règle de provenance inchangée). Le circuit de relecture et les conditions de
  fusion restent les mêmes. Aucune règle de sécurité n'est assouplie.
- **Conséquences :** Loïc reçoit un court résumé à chaque fin de phase, qu'il peut contester ; il
  découvre les choix après coup et peut les renverser. Il retire la délégation quand il veut, d'un
  message.

---

## Décisions ouvertes

- **Accès WhatsApp** : API officielle (numéro dédié) vs non officielle (numéro perso, risque de ban) ; exposition du webhook entrant (ex. tunnel limité à cet endpoint) — Phase 3 (ADR-018).
- **Périmètre mail** : boîtes couvertes, règles de confidentialité (INTEGRATIONS §5).
- **Cadence des rapports** : quotidien, hebdo, ou les deux (PRD §13).
- **Critère « attend Loïc »** : relance automatique vs attente passive (PRD §13).

## ADR-025 — Conversations, lot 1 : un index masqué des sessions locales, lu en liste blanche

- **Date :** 2026-11-26. Choisi par l'agent sous la délégation totale de Loïc du 2026-11-25 (ADR-024) ; rédigé par des subagents, relu et confirmé par le fil principal le 2026-11-26 (corrections au §16 du cadrage). Issue #204. Conception : `docs/superpowers/specs/2026-11-25-conversations-lot1-design.md`, choix C1 à C16 au §12.
- **Contexte :** la Phase 3 (ROADMAP) doit permettre à Loïc de lire ses conversations avec ses agents dans Nexus, d'y chercher et d'en tirer une tâche. Le premier lot couvre les sessions locales de trois sources. Claude Code écrit des `.jsonl` sous `~/.claude/projects`. Codex écrit des `.jsonl.zst` sous `~/.codex/sessions`, à côté des fichiers de connexion de Loïc. Hermes tient une base SQLite vivante (`state.db`, 508 Mo, en WAL), déjà réparée plusieurs fois. Ces données sont **sensibles** (SECURITY §2) : ce sont des messages privés, avec des secrets collés dans les sorties d'outils. La vérité reste à la source (ADR-016, DATA-MODEL §6), et Nexus n'en garde qu'un index reconstructible (ARCHITECTURE, « Index/cache externe »). Aucun accès de Loïc n'est requis : ni jeton, ni connexion, ni envoi. Telegram, WhatsApp, Gmail et tout envoi sont hors du lot.
- **Décision :** Nexus lit ces sessions en lecture seule, n'en garde que le texte humain et les réponses des modèles, masqué, dans des tables séparées de `nexus.db` avec une recherche FTS5, et réserve leur lecture aux humains. Quand un choix touche aux données de Loïc, l'option retenue est la plus restreinte et la plus réversible :
  1. **D1 — Rien n'est lu par défaut (C1).** Chaque source se règle explicitement (`NEXUS_CONV_CLAUDE_ROOT`, `NEXUS_CONV_CODEX_ROOT`, `NEXUS_CONV_HERMES_DB`), sans repli sur `~`. Une racine relative, mal nommée (`projects`, `sessions`, `state.db` attendus), un lien ou un point de jonction (contrôlés sur le chemin réglé, avant sa résolution), ou une base Hermes en lien physique (`st_nlink` différent de 1), font refuser la source, avec un message fixe qui ne recopie pas le chemin.
  2. **D2 — Liste blanche de chemins, aucune liste de refus (C16).** L'énumération se fait niveau par niveau, à profondeur fixe (`os.scandir`, jamais `rglob` ni `os.walk`) ; chaque dossier intermédiaire est contrôlé par `lstat` (ni lien ni point de réanalyse, sous la racine) avant d'être parcouru. Seuls les noms qui correspondent entièrement au motif du lecteur passent. Chaque candidat est ensuite contrôlé par `lstat` : fichier ordinaire, sans lien, `st_nlink == 1`, chemin sous la racine résolue. À l'ouverture, `fstat` doit redonner la même identité `(st_dev, st_ino)`. Les descripteurs sont fermés avant toute écriture. Le lecteur Codex ne remonte jamais au parent de `sessions` (`auth.json`, `config.toml`).
  3. **D3 — Ce qui est gardé (C14, C15).** Seuls le texte humain et les réponses des modèles sont gardés : ni outils, ni raisonnement, ni invites système, ni subagents, ni identifiants de compte. Plafonds : 1 Mio par ligne lue, 16 000 caractères stockés par message (`truncated`), et 8 Mio lus et 2 000 messages écrits par source et par passe.
  4. **D4 — Auteur honnête (C4).** `author = loic` seulement si la source le prouve (Claude `origin.kind = human`), sinon `unknown` (ADR-005), pour Codex et Hermes compris. Les notifications de tâches Claude sont sautées. Côté Hermes, `helios` est le profil de `NEXUS_HERMES_PROFILE` et `hermes` tout autre profil.
  5. **D5 — Masquage avant stockage.** `body`, `title`, `workspace` et `git_branch` passent par `nexus.secrets.redact`, avant toute coupe à leur longueur maximale, dans la fonction d'extraction, par une fabrique qui ne construit rien sans masquer. La FTS n'indexe que le texte masqué (C11 : FTS5 `unicode61 remove_diacritics 2` dans `nexus.db` ; `trigram` et la recherche à la demande dans les fichiers sont écartés). La syntaxe FTS de l'utilisateur n'est jamais transmise : chaque terme est cité. La mesure du débit et du sur-masquage de `redact` est une condition d'arrêt (PR 2).
  6. **D6 — Sondage, budget, fenêtre et rétention (C2, C3).** Sondage toutes les 60 s dans le lifespan (`asyncio.to_thread`, une passe à la fois), sans surveillance du système de fichiers. La fenêtre d'ingestion et la rétention valent 31 jours, réglables de 1 à 3 650 jours (sondage de 10 à 3 600 s), et la fenêtre ne peut pas dépasser la rétention ; élargir la rétention fait relire les fichiers, inchangés compris (`covered_since`, fixé au début de la lecture et avancé par la purge) ; pour Hermes, il faut élargir aussi la fenêtre (`NEXUS_CONV_SINCE_DAYS`). Les écritures se font par lots idempotents (`ON CONFLICT DO NOTHING`, curseur avancé dans la même transaction).
  7. **D7 — Codex compressé seulement (C7).** Nouvelle dépendance `zstandard` : `compression.zstd` exige Python 3.14, et le serveur exige 3.13. La décompression se fait en flux, jamais sur le disque, avec un plafond de 256 Mio décompressés par fichier. Seuls les `.jsonl.zst` sont admis, la seule forme vue (87 fichiers sur 87) ; le `.jsonl` en clair attend un relevé et une PR.
  8. **D8 — Hermes en lecture seule SQLite, livré en dernier (C5, C6, C13).** `state.db`, `-wal` et `-shm` recontrôlés par `lstat` avant chaque passe (ni lien, ni point de réanalyse, `st_nlink == 1`), URI `Path.as_uri()` + `?mode=ro`, `query_only`, colonnes nommées sur `sessions` et `messages` seulement, contrôle du schéma avant chaque passe, aucune connexion tenue entre deux passes. `hermes sessions export` est écarté : la même commande porte `--upload`, `--public` et `--delete-after-verified`. Seule la source `cli` est lue, en `dm` ou sans type ; `acp`, `telegram`, `group`, `cron`, `oneshot` et `kanban` sont exclus (`NEXUS_CONV_HERMES_SOURCES`). `acp` s'ouvrira après un relevé : rien ne dit encore qui mène une telle session, ni sous quelle source s'écrivent les runs de Nexus. Un test sur une base WAL construite à l'exécution prouve que `state.db` n'est pas modifiée ; sinon Hermes est reporté.
  9. **D9 — Disparition et purge (C8).** Une session absente de deux énumérations complètes et réussies reçoit `missing_since`. Elle est retirée de l'index après 24 h d'absence. Une source désactivée est purgée à la purge quotidienne suivante. La purge tourne avec `secure_delete=ON`, puis optimise la FTS (`'optimize'`) et force le point de contrôle du WAL (`wal_checkpoint(TRUNCATE)`). Ces deux derniers points sont un ajout de l'agent ; un test en PR 2 doit les vérifier. Les ids de `conversations` et de `conversation_messages` sont `AUTOINCREMENT` : une poignée purgée n'est jamais réattribuée.
  10. **D10 — Sauvegardes sans l'index (C9).** Chaque copie de `nexus.db` est vidée de l'index des conversations avant sa publication : `origin_message_id` à `NULL`, tables vidées, FTS reconstruite vide, `VACUUM`. Le retrait tolère une base antérieure à `0010` ou à `0011`, car le lifespan sauvegarde avant de migrer. Un échec du retrait fait échouer la sauvegarde ; une copie `*.partial` laissée par un arrêt brutal est effacée au démarrage, avant la première sauvegarde.
  11. **D11 — Lecture réservée aux humains (C10).** Les routes `/api/conversations…` et `/api/conversation-sources` renvoient 403 `human_only` à tout agent, contrôlé avant toute lecture (`permissions.check_conversations`). Cela amende la colonne « Lire » de la matrice de SECURITY §3 pour les conversations. Aucun événement WebSocket n'est émis, et aucun chemin n'est renvoyé.
  12. **D12 — Tâche née d'un message (C12).** `POST /api/conversations/messages/{nx-msg-n}/tasks` crée la tâche par la création existante (`title` et `objective` saisis par Loïc, obligatoires), sans rien recopier du message d'office. La migration `0011` ajoute `tasks.origin_message_ref`, la référence stable (`claude-session:<session>/<uuid>`, `codex-session:<session>/<ordinal>`, `hermes-session:<session>/<id>`, au format de DATA-MODEL §1), posée une fois et absente de `UPDATABLE`. Elle ajoute aussi `tasks.origin_message_id` (clé étrangère `ON DELETE SET NULL`), qui ne sert qu'à la navigation.
- **Conséquences :** migration `0010_conversations` (tables `conversations`, `conversation_messages`, `conversation_cursors`, FTS5 à contenu externe et ses trois déclencheurs, réversible). FTS5 devient exigé : une sonde au démarrage, et un échec fermé sans lui, à revoir pour le sidecar Tauri. Un filtre `include_object` écarte la FTS et ses tables d'ombre de `compare_metadata`, dans le test de `0010` comme dans les cinq tests de migration existants. Migration `0011_task_origin_message` par `add_column(…, inline_references=True)`, comme `0006`. Nouveau paquet `nexus/conversations/`, et `tasks/service.py` (397 lignes) ne grossit pas. `nx-conv-<n>` est une poignée d'index, pas l'identité de la session, renvoyée dans `external_ref` ; DATA-MODEL §2.7 est amendé. Découpage en huit PR indépendantes (PR 0 à PR 7 du cadrage, §11) : `architect` passe avant les PR 1, 2, 4, 6 et 7. Contreparties : rien de plus vieux que 31 jours n'est cherchable, et « Née de » retombe sur la référence seule après 31 jours ; une session Codex en cours n'apparaît qu'une fois compressée ; les sessions Hermes `acp` ne sont pas lues ; l'auteur des messages Codex et Hermes reste `auteur non vérifié` ; une restauration de sauvegarde relit les sources ; les limites du scanner (SECURITY §1) s'appliquent aux conversations ; Loïc découvre ces choix après coup et peut les renverser (ADR-024).
- **Statut :** accepté (confirmé par le fil principal le 2026-11-26, sous ADR-024).

## ADR-026 — Clôture de la Phase 2 : Mnēma, Aether et Orca reportés (2026-11-26)

- **Date :** 2026-11-26. Choisi par l'agent sous la délégation totale de Loïc du 2026-11-25 (ADR-024).
- **Contexte :** les livrables de la Phase 2 (ROADMAP) citent les adaptateurs `hermes` (Helios, Mnēma, Aether), `claude-code`, `codex` et `orca`. Le critère de sortie, lui, demande qu'une tâche confiée à Helios et une confiée à Codex racontent leur histoire complète dans Nexus. Il est tenu : runs réels de Hermes (Helios) le 2026-11-11 (#182), de Codex le 2026-11-26 (#203), et de Claude Code (#190). L'adaptateur `hermes` ne sert que Helios, par le tableau `nexus` (lot G, #179). Aucun cadrage n'existe pour Mnēma et Aether en exécutants, ni pour Orca.
- **Décision :** la Phase 2 est close sur son critère de sortie. Deux livrables sont reportés :
  1. les profils Mnēma et Aether de l'adaptateur `hermes`, à cadrer quand un besoin de leur confier du travail sera exprimé (la Phase 5 les montre dans la vue Système, pas comme exécutants) ;
  2. l'adaptateur `orca`, à cadrer quand un besoin d'exécution par Orca sera exprimé.
  Aucun des deux n'a de date.
  Rien n'est retiré du code : `hermes` reste limité à Helios, et confier du travail à un exécutant non enregistré reste un 409 `executor_unavailable`.
- **Raison :** le critère de sortie commande, pas la liste (ROADMAP : « les critères de sortie commandent, pas le calendrier ») ; ajouter des exécutants sans cadrage ni run réel élargirait ce qui agit sur les données de Loïc. C'est l'option la plus restreinte et la plus réversible : chaque report se lève par un cadrage puis une PR.
- **Conséquences :** la Phase 3 (Conversations) s'ouvre (lot 1, #204, ADR-025). Réserves de la Phase 2 suivies dans #200, #201 et #207.
- **Statut :** accepté.
