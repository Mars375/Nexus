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
  1. **D1** — une seule table pour les questions et les approbations, avec `ask_kind` (`question` ou `needs_human`) et un 5e statut stocké `answered` : `pending`, `approved`, `rejected`, `answered`.
  2. **D2** — la décision est binaire (`approved` / `rejected`) ; approuver un `needs_human` qui propose au moins 2 options exige `choice` (l'indice de l'option). Implémenté avec l'écriture des décisions (étape suivante).
  3. **D3** — `payload.consequence` est **obligatoire** pour tout **nouveau** `needs_human` (409 `consequence_required`), facultative pour une `question`, 1 000 caractères au plus. Un renvoi identique d'un ancien événement reste une relecture. Elle est **annoncée par le demandeur et non vérifiée par Nexus** (ADR-005) : l'interface dit « annoncée par <agent> ».
  4. **D4** — `payload.expires_at` facultatif, fixé par l'agent, sans valeur par défaut, de 1 minute à 30 jours après la réception ; le statut `expired` est **calculé** (`expires_at <= maintenant`, UTC) et jamais stocké.
  5. **D5** — seuls les destinataires humains décident ; un autre acteur est refusé en 409, pas 403. Contrôle de cohérence, **pas de la sécurité** : l'acteur n'est que déclaré jusqu'à #16 (SECURITY §3).
  6. **D6** — pas de rétroremplissage : les demandes antérieures à la migration 0004 n'ont pas d'approbation.
  7. **D7** — Maintenant liste les demandes en attente de tout âge et les traitées des 7 derniers jours ; la tuile compte les demandes en attente (spec Maintenant, décision 2 révisée).
  8. **D8** — un nouveau `kind` `answer`, réservé à Nexus, est refusé dans `POST /api/events` : un agent ne peut pas fabriquer une réponse de Loïc.
  9. **D9** — pas de statut « retirée » : une demande dépassée se corrige par un nouvel événement.
- **Conséquences :** migration `0004` (table `approvals`, sans rétroremplissage, réversible par `drop_table`) ; l'événement de demande consigne l'effet `approval` avec la référence ; l'agent relit `GET /api/approvals/<ref>` jusqu'à la fin de l'attente, valider ne déclenche rien chez lui (ADR-012, EVENT-PROTOCOL §6 ter) ; la création et la lecture arrivent avant l'écriture des réponses (PR en trois temps : modèle et lecture, réponses et décisions avec `/api/now`, interface). Contrepartie : une demande sans échéance attend sans limite, et une approbation « expirée » peut encore être tranchée si le produit le décide, puisque rien n'est écrit à l'échéance.
- **Statut :** accepté.

---

## Décisions ouvertes

- **Accès WhatsApp** : API officielle (numéro dédié) vs non officielle (numéro perso, risque de ban) ; exposition du webhook entrant (ex. tunnel limité à cet endpoint) — Phase 3 (ADR-018).
- **Périmètre mail** : boîtes couvertes, règles de confidentialité (INTEGRATIONS §5).
- **Cadence des rapports** : quotidien, hebdo, ou les deux (PRD §13).
- **Critère « attend Loïc »** : relance automatique vs attente passive (PRD §13).
