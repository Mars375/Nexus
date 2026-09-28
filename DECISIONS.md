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
- **Statut :** accepté.

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
- **Statut :** accepté.

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
- **Statut :** accepté.

## ADR-010 — Frontière par nœud : chaque gardien chez lui

- **Date :** 2026-09-28
- **Contexte :** règle établie du Nexus (« action autonome par nœud, gardien local, frontières explicites »).
- **Décision :** un changement sur un nœud est appliqué par son gardien (Helios, Mnēma, Aether, Artémis) ; Nexus et les autres nœuds restent en lecture jusqu'à demande explicite. Lecture distante : Tailscale/SSH read-only.
- **Conséquences :** pas de mutation croisée silencieuse ; toute intervention croisée se demande et se trace.
- **Statut :** accepté.

---

## Décisions ouvertes (à trancher — Phase 0)

- **Stack UI/serveur** : serveur Python + UI web vs extension du dashboard Hermes (ARCHITECTURE §7).
- **Événements de coordination** : surfaces natives Hermes vs `nexus.db` (DATA-MODEL §6).
- **Périmètre mail** : boîtes couvertes, règles de confidentialité (INTEGRATIONS §5).
- **Cadence des rapports** : quotidien, hebdo, ou les deux (PRD §13).
- **Critère « attend Loïc »** : relance automatique vs attente passive (PRD §13).
