# Vue Maintenant — conception (#6)

**Date :** 2026-10-01 · **Issue :** #6 · **Références :** VIEWS §1, PRD FR-3 et NFR-7, ADR-005 (honnêteté), ADR-006 (secrets), ADR-017 (UI ↔ API seulement), spec #5 (temps réel), spec #8 (provenance)
**Maquette validée :** Claude Design, « Nexus — Maintenant » : https://claude.ai/artifact/CDYbnTCWL6VoE66YkaYvkW

## But

La page d'accueil répond en 5 secondes à « qu'est-ce qui se passe en ce moment ? » : qui travaille sur quoi, ce qui t'attend, ce qui bloque, ce qui vient d'être fini, dans quel état sont les machines. Tout vient de mesures réelles ; rien n'est décoratif.

## Décisions (validées avec Loïc le 2026-09-30 et le 2026-10-01)

1. **Deux étapes.** #6 = la vue avec les données qui existent déjà. Les approbations (`Approval`, DATA-MODEL §2.10) et les actions « répondre / valider / refuser » font une issue suivante.
2. **Demandes reçues** *(révisée le 2026-10-07, ADR-019 / issue #26, D7)*. Dans #6, ce sont les événements `question` et `needs_human` dont `needs` contient `loic`, des 7 derniers jours, jamais étiquetés « en attente » faute de savoir s'ils sont traités. Avec les approbations (`GET /api/approvals`, DATA-MODEL §2.10), la vue liste les demandes **en attente de tout âge** (une demande sans réponse ne disparaît pas au bout de 7 jours) **plus les demandes traitées des 7 derniers jours** (approuvée, refusée, répondue, expirée), les plus récentes d'abord ; la tuile « demandes » compte celles **en attente**. Le statut `expired` est calculé à la lecture. Les demandes antérieures à la migration 0004 n'ont pas d'approbation (pas de rétroremplissage) : elles restent lues par la règle de #6 (reçues dans les 7 jours) jusqu'à sortir de la fenêtre. Le changement de `/api/now` (`asks` enrichi, voir la forme ci-dessous) est livré avec l'écriture des réponses ; celui de l'interface (liste, tuile, formulaire de réponse) arrive dans l'étape suivante de #26 : en attendant, l'interface existante affiche encore toutes les demandes listées et compte `asks.length`.
3. **Direction artistique « Salle orbitale »**, thème sombre : quasi-noir, trame de points, filets fins, arêtes vives. Couleur seulement pour un état : turquoise = run en cours, orange = ce qui t'attend, rouge = blocage, vert = machine en ligne, gris hachuré/pointillé = `unknown` ou hors ligne. Couleurs et références proposées par Gemini (consultation design), contrastes recalculés (texte ≥ 4,5:1).
4. **L'étage** : les agents sont montrés dans une scène isométrique — un poste par agent, ta table au centre, la salle des serveurs dans le coin — à côté d'un panneau « Système » (compteurs, demandes reçues, opération principale) et, sous la scène, des blocages et des derniers done.
5. **Mouvement** (décidé par Claude) : seuls les vrais changements d'état bougent ; rien en boucle ; `prefers-reduced-motion` respecté.

## Données : un point d'entrée `GET /api/now`

Une seule lecture, un seul instantané cohérent (une session, une transaction de lecture), pour tenir NFR-7 (< 2 s) et ne pas assembler côté client des morceaux mesurés à des instants différents.

```json
{
  "source": "nexus.db", "measured_at": "…",
  "operation": { "task": "nx-task-31", "title": "…", "lead_agent": "helios", "since": "…", "next_action": "…", "due_at": "…" } | null,
  "auxiliaries": [{ "task": "nx-task-33", "title": "…" }],
  "agents": [{ "agent": "helios", "state": "run" | "idle", "task": "nx-task-31" | null, "title": "…" | null, "run": "session:abc" | null, "since": "…" | null }],
  "asks": [{ "event": "nx-evt-7", "agent": "mnema", "kind": "question" | "needs_human", "subject": "…", "task": "nx-task-32" | null, "at": "…", "received_at": "…",
            "body": "…" | null, "options": ["…"], "consequence": "…" | null,
            "approval": { "ref": "nx-appr-3", "status": "pending" | "approved" | "rejected" | "answered" | "expired", "expires_at": "…" | null, "decided_by": "loic" | null, "decided_at": "…" | null } | null }],
  "blocks": [{ "task": "nx-task-29", "title": "…", "cause": "…", "since": "…", "follow_up_at": "…" | null, "lead_agent": "artemis" | null }],
  "done": [{ "task": "nx-task-27", "title": "…", "agent": "claude" | null, "evidence": ["…"], "at": "…" }]
}
```

- **agents** : tous les agents connus (`nexus.actors.AGENTS`), dans un ordre fixe, pour que chacun garde sa place sur l'étage. `run` = l'agent a un run ouvert (dernier `working` sans événement de clôture, même règle que `_runs`) ; sa tâche et son début viennent de ce `working`. Sinon `idle`. Un agent n'est jamais « bloqué » par lui-même : un blocage appartient à une tâche ; la scène marque le poste de l'agent principal d'une tâche bloquée.
- **asks** : décision 2 (révisée, ADR-019 D6 et D7). `subject`, `body` et `consequence` passent par le même masquage que l'API d'événements (déjà stockés masqués, ADR-006) ; `consequence` est annoncée par le demandeur et non vérifiée. `options` garde les positions de `payload.options` (`choice` en est l'indice ; un élément non textuel devient une chaîne vide). `approval` porte l'état de la demande (`status` effectif : `expired` est calculé à la mesure) ; il est `null` pour une demande d'avant la migration 0004 (pas de rétroremplissage). La liste contient les demandes **en attente de tout âge** et les **traitées des 7 derniers jours**, comptés depuis la décision (`decided_at`) ou, pour une demande expirée, depuis son échéance ; une demande sans approbation reste soumise à la règle de #6 (reçue dans les 7 jours). Tri : réception de la demande, plus récentes d'abord. La tuile « demandes » ne compte que les demandes dont `approval.status` est `pending` ; une demande sans approbation n'est jamais étiquetée « en attente » (on ne sait pas si elle est traitée). Les clés de #6 sont inchangées.
- **blocks** : tâches au statut `blocked`, plus anciennes d'abord. `since` = instant de la dernière ligne d'historique qui a fait passer la tâche à `blocked` (il n'y a pas de colonne dédiée) ; même règle pour `done[].at` avec `done`.
- **auxiliaries** : tâches de rôle `auxiliary` **en cours** (`in_progress`), comme le disent PRD §156 et VIEWS §1 ; une auxiliaire préparée en backlog ou todo n'y figure pas.
- **done** : tâches passées en `done` ces 7 derniers jours (date du dernier changement de statut), avec leurs preuves, plus récentes d'abord, 5 au plus. `agent` = l'acteur qui a fait passer la tâche à `done` (ligne d'historique), pas son agent principal. La fenêtre de 7 jours est une durée réelle, calculée en UTC.
- **nœuds** : pas dans `/api/now` ; l'interface lit `/api/nodes` (autre source, autre cadence, déjà avec provenance).
- Contrat de provenance (#8) : `/api/now` porte `source` et `measured_at` au niveau racine ; le test générique `test_provenance_contract.py` le couvre (objet porteur de `source`).
- Aucune écriture, aucune migration.

## Interface

### Structure (maquette)

- Navigation à gauche (existante), barre d'état en bas (existante, restylée).
- Centre : titre « Maintenant » + provenance ; **la scène de l'étage** ; en dessous, deux colonnes : **Blocages** et **Derniers done**.
- Droite, panneau **Système** : quatre tuiles (agents actifs, demandes, blocages, nœuds en ligne — des comptes, rien d'autre) ; **Demandes reçues** ; **Opération principale** (titre, agent, depuis, prochaine action, échéance, auxiliaires).
- Sous 1100 px : le panneau Système passe sous la scène ; sous 760 px : la scène est remplacée par la liste des agents (même information, en lignes).

### La scène de l'étage (`web/src/now/Floor.tsx`)

- SVG isométrique, géométrie calculée par des fonctions pures (`web/src/now/iso.ts` : projection, boîtes, positions des postes) testées à part.
- **Postes** : un par agent, placés sur deux rangées de part et d'autre de la table ; jusqu'à 12 postes : au-delà de 8, les deux rangées s'allongent (l'étage s'élargit), la table reste au centre. Bureau en volume + écran.
  - run : écran turquoise + flaque de lumière au sol ;
  - inactif : écran éteint, nom en gris ;
  - l'agent a une demande reçue : balise orange plantée sur son écran + lueur ambre + fil pointillé au sol jusqu'à ta table ;
  - agent principal d'une tâche bloquée : plateau hachuré rouge.
- **Ta table** : estrade au centre, une fiche orange par demande reçue (3 au plus, puis « +N ») ; libellé « N demande(s) » ou « aucune demande reçue (7 j) ».
- **Salle des serveurs** : une baie par nœud de `/api/nodes`, LED sur la face visible (vert plein = en ligne ; pointillés gris = `unknown` ; gris creux = hors ligne) ; légende en colonne reliée à chaque baie.
- **Étiquettes** en HTML superposé (pas en texte SVG) : nom de l'agent, tâche, référence et âge (« 42 min »), lisibles sans survol.
- **Accessibilité** : la scène a un `aria-label` ; son contenu est aussi donné en liste lisible par un lecteur d'écran (la même liste que la version étroite, masquée visuellement au-dessus de 760 px).

### Mouvement (seulement sur un vrai changement)

| Changement | Mouvement |
|---|---|
| Nouvelle demande | la balise se déploie (500 ms), une étincelle court sur le fil jusqu'à la table (1,1 s, une fois), la fiche se pose ; la ligne arrive dans « Demandes reçues » avec un fond ambre qui s'efface (1,8 s) |
| Run qui démarre / finit | l'écran s'allume / s'éteint (450 ms), la flaque apparaît / se dissipe (700 ms) |
| Blocage levé | les hachures s'effacent (300 ms) |
| Nœud qui change d'état | les LED changent de couleur (400 ms) |

- L'état d'arrivée s'applique sans attendre une image (`offsetHeight` forcé) : un onglet en arrière-plan reçoit des messages temps réel (leçon de la maquette #6).
- Écart accepté : les hachures (fond `url()` ↔ `none`) et les LED passées en contour ne s'interpolent pas, elles basculent sans fondu.
- `prefers-reduced-motion` : aucun mouvement, états finaux affichés directement.

### Rafraîchissement

- Requête `['now']` : relecture toutes les 10 s (registre `REFRESH_MS`, #8) ; invalidée par le temps réel (#5) sur `task_changed` et `event`.
- Nœuds : `['nodes']`, cadence 60 s (existante).

### États honnêtes

- Chargement : squelette de l'étage (murs seuls), aucun poste allumé.
- Erreur de lecture : la dernière donnée reste affichée, marquée « périmée » (#8) ; jamais d'étage vide présenté comme calme.
- Vide : chaque section reste à sa place et dit ce qu'elle ne contient pas (« Aucun agent ne travaille en ce moment. », « Aucune demande reçue ces 7 derniers jours. », « Aucun blocage actif. », « Rien de terminé ces 7 derniers jours. », « Pas d'opération principale en cours. »).
- `unknown` d'un nœud : affiché tel quel, jamais vert.

### Thème

- #6 introduit les jetons du thème « Salle orbitale » (sombre) dans `web/src/index.css` et l'applique à la **navigation, la barre d'état et Maintenant**. Le tableau Travail garde provisoirement son thème clair ; sa migration est une issue suivante (pour ne pas mêler deux chantiers dans une PR).
- Polices : Barlow / Barlow Condensed (titres), IBM Plex Mono (données), **embarquées** dans l'application (pas de CDN : l'app est locale et ira dans Tauri).

## Cas limites

- 0 agent en run, 0 demande, 0 blocage : scène entière éteinte, table « aucune demande reçue (7 j) », textes de vide.
- Un agent avec plusieurs demandes : une seule balise, plusieurs fiches sur la table.
- Demande sans tâche (`task` null) : fiche sur la table, pas de ligne vers une tâche ; texte « sur aucune tâche ».
- Run ouvert sur une tâche abandonnée ou terminée : l'agent reste « run » (c'est ce que disent les événements) ; la tâche affichée est celle du `working`.
- Plus de 8 agents connus : les rangées s'allongent, l'étage s'élargit.
- Nœud absent de la lecture Tailscale : pas de baie inventée.
- Texte long (sujet, titre) : tronqué avec « … » dans la scène, complet dans les listes.
- Secrets : les sujets de demandes et titres sont déjà stockés masqués ; rien de nouveau n'est reçu.

## Tests

- **Serveur (pytest)** : `/api/now` — opération principale et auxiliaires ; agent en run (working ouvert), run fermé → idle ; demandes filtrées (kind, `needs` contient `loic`, fenêtre de 7 jours, bornes) ; blocages ; derniers done (7 jours, 5 au plus, preuves) ; base vide ; provenance ; un agent qui n'a jamais publié apparaît `idle`.
- **Web (Vitest)** : `iso.ts` (projection, positions, 12 postes) ; état d'un poste selon les données (run, idle, demande, bloqué) ; textes de vide ; invalidation `['now']` par le temps réel ; le mouvement ne se déclenche que sur un changement d'état (pas au premier rendu).
- **Playwright** : un événement `working` posté par l'API allume le poste de l'agent en moins d'une seconde ; une `question` à `loic` fait apparaître la fiche sur la table et la ligne dans « Demandes reçues » ; version étroite (760 px) = liste des agents.
- Contrôle visuel : captures de la vue à 1440×900, 1100 px et 760 px, thème et `prefers-reduced-motion`, avant la PR.

## Hors périmètre

Approbations et réponses (issue suivante), migration du tableau Travail au thème sombre (issue suivante), clic sur un poste pour ouvrir un panneau d'agent (plus tard ; ici un clic sur un poste ou une ligne ouvre la tâche dans Travail), sons.
