# Temps réel : WebSocket serveur → interface — conception (#5)

**Date :** 2026-09-30 · **Issue :** #5 · **Références :** ARCHITECTURE §3.5 et §7, EVENT-PROTOCOL §6, ADR-005, ADR-006, spec #8 (provenance et fraîcheur)

## But

L'interface reflète chaque changement sans rechargement : un événement posté par l'API apparaît dans le tableau ouvert en moins d'une seconde, et une coupure suivie d'une reconnexion ne perd aucun changement.

## Décisions (validées avec Loïc le 2026-09-30)

1. **WebSocket + relecture de sécurité.** Le WebSocket déclenche une relecture immédiate des données concernées ; la relecture toutes les 10 s (#8) reste en filet. Un message perdu n'efface jamais rien, et « mesuré il y a … » garde son sens.
2. **Indicateur dans la barre d'état du bas**, à côté de l'état de la base.
3. **Approche B : chaque connexion relit la base toutes les 250 ms** au-delà de son curseur ; la même requête sert au rattrapage et au direct. Pas de branchement dans les chemins d'écriture ; les écritures d'un autre processus sont vues aussi.

## Curseur

- Deux compteurs croissants existent déjà : l'identifiant de `task_history` (chaque changement de tâche, y compris ceux causés par un événement, y écrit une ligne) et l'identifiant de `events`.
- Le curseur est la paire `{"history": <id>, "events": <id>}` : « j'ai vu tout jusqu'à ces identifiants inclus ».
- Aucune nouvelle table, aucune migration.

## Serveur

### Point d'entrée

`/api/ws` (WebSocket). Paramètres de requête facultatifs : `history_after`, `events_after` (entiers ≥ 0).

- **Sans curseur** (premier chargement d'un onglet) : on part du dernier identifiant existant ; l'état actuel vient des lectures REST.
- **Avec curseur** (reconnexion) : on renvoie tout ce qui a changé au-delà, puis on passe en direct.
- **Curseur en avance sur la base** (ex. base restaurée depuis une sauvegarde) : le serveur l'annonce (`reset: true` dans `hello`) et repart de l'existant ; le client relit tout.
- Paramètre invalide (non entier, négatif) : fermeture avec le code 1008 et une raison générique, sans recopier la valeur reçue.

### Messages (JSON, serveur → client)

Volontairement minces : des références et des types, jamais de texte libre reçu (sujet, corps, charge utile). Le client relit via l'API REST, qui garantit déjà le masquage des secrets (ADR-006) et la provenance (#8).

| `type` | Champs | Sens |
|---|---|---|
| `hello` | `cursor`, `reset` (bool) | connexion établie ; curseur de départ |
| `task_changed` | `task` (`nx-task-N`), `cursor` | une tâche a changé (plusieurs lignes d'historique d'une même tâche dans une même relecture → un seul message) |
| `event` | `event` (`nx-evt-N`), `task` (`nx-task-N` ou `null`), `kind`, `cursor` | un événement a été enregistré |
| `resync` | `cursor` | trop de changements d'un coup (plus de 500 lignes) : le client relit tout |
| `ping` | `cursor` | rien de nouveau depuis 15 s ; prouve que la connexion vit |

`cursor` est toujours un curseur jusqu'où tout est vu une fois le message appliqué : le client le garde tel quel. Dans une même relecture, seul le **dernier** message avance le curseur (les précédents portent celui de départ) : une coupure au milieu fait rejouer la relecture — une invalidation de plus, jamais un changement perdu.

### Boucle d'une connexion

1. Vérifier l'origine (ci-dessous) ; accepter ; envoyer `hello`.
2. Toutes les 250 ms : lire les lignes d'historique et d'événements au-delà du curseur (lecture SQLite dans un thread, jamais dans la boucle asynchrone) ; envoyer les messages, dans l'ordre des identifiants ; avancer le curseur.
3. Sans message depuis 15 s : envoyer `ping`.
4. Déconnexion du client : fin propre, sans erreur journalisée.

### Sécurité : origine

Un WebSocket n'est pas protégé par CORS : un site quelconque ouvert dans le navigateur pourrait sinon se connecter à `ws://127.0.0.1:8765` et lire les changements.

- Origines admises : toute origine **de boucle locale** — schéma `http` ou `https`, hôte `localhost`, `127.0.0.1` ou `[::1]`, quel que soit le port (l'interface servie, le serveur de dev Vite sur 5173, celui des tests de bout en bout sur un autre port : le proxy Vite transmet l'`Origin` du navigateur tel quel). S'y ajoute une liste réglable par `NEXUS_ALLOWED_ORIGINS` (séparateur `,`, comparaison exacte) pour Tauri plus tard. Un site Internet n'a jamais une origine de boucle locale : le risque visé reste couvert. (Précision du 2026-09-30 : la première version listait des ports fixes, ce qui aurait refusé le WebSocket en e2e.)
- Une connexion **sans** en-tête `Origin` (client non navigateur, local) est admise : elle pourrait lire l'API REST de toute façon.
- Toute autre origine : handshake refusé (403 / code 1008), sans recopier l'origine reçue dans la réponse.

## Interface

### Connexion (`web/src/live.ts`)

- Adresse relative à la page (`/api/ws`, en `ws:` ou `wss:` selon la page) : fonctionne derrière le proxy Vite (`ws: true` déjà configuré) et, plus tard, dans Tauri.
- **États** : `connecting` (aucune connexion encore réussie), `connected`, `reconnecting` (avec le numéro d'essai), `unknown` (plus de 30 s sans connexion établie, comptées depuis la perte de la connexion ou le chargement de la page).
- **Reconnexion** : attente croissante 0,5 s, 1 s, 2 s … plafonnée à 10 s, avec un aléa de ±20 % ; on renvoie le dernier curseur.
- **Connexion morte** : aucun message (même `ping`) depuis 45 s → on ferme et on reconnecte.
- La machine d'états est une fonction pure testable, séparée de l'objet `WebSocket` (injecté).

### Effets des messages (TanStack Query)

- `task_changed` → invalider la liste des tâches et les requêtes de détail de cette tâche (commentaires, historique).
- `event` → invalider les requêtes d'événements et, si `task` est présent, celles de cette tâche.
- `resync` ou `hello` avec `reset: true` → invalider toutes les requêtes.
- La relecture toutes les 10 s continue dans tous les cas.

### Indicateur (barre d'état du bas)

- « Temps réel : connecté »
- « Temps réel : connexion… » (premier essai)
- « Temps réel : reconnexion… (essai N) »
- « Temps réel : unknown — relecture toutes les 10 s » (couleur « attention »)

Aucune animation ; seul un changement d'état change l'affichage.

## Cas limites

- Rafale de changements : messages coalescés par tâche ; au-delà de 500 lignes d'un coup, `resync`.
- Plusieurs onglets : chaque onglet a sa connexion et son curseur.
- Serveur redémarré (reload en dev) : la connexion tombe, le client reconnecte avec son curseur, aucun changement n'est perdu (les identifiants sont en base).
- Événement sans tâche (`task` null) : `event` avec `task: null`.
- Tâche supprimée : n'existe pas (les tâches sont abandonnées, jamais supprimées).

## Tests

- **Serveur (pytest, TestClient WebSocket)** : `hello` sans curseur part de l'existant ; rattrapage exact depuis un curseur (tâche modifiée, commentaire, événement) ; direct : un changement fait après la connexion arrive ; coalescence par tâche ; `resync` au-delà du seuil ; curseur en avance → `reset: true` ; paramètre invalide refusé sans écho ; origine étrangère refusée, origines par défaut et absence d'`Origin` admises ; aucun texte libre (sujet d'événement, commentaire) dans les messages.
- **Web (Vitest)** : machine d'états (transitions, attente croissante plafonnée, passage à `unknown` après 30 s, reconnexion sur silence de 45 s) avec un faux WebSocket et de faux timers ; effets des messages sur le client TanStack Query ; indicateur pour chaque état.
- **Playwright** : tableau ouvert, une tâche créée par l'API (hors interface) apparaît en moins d'une seconde ; coupure simulée (connexion fermée côté navigateur avec `page.routeWebSocket`) puis reconnexion : un changement fait pendant la coupure apparaît après la reconnexion.

## Documentation

- EVENT-PROTOCOL §6 « Diffusion » : renvoyer à ce document pour le format des messages.
- Checklist : une route WebSocket vérifie l'origine et n'envoie jamais de texte libre reçu.

## Hors périmètre

Notifications (Telegram, Windows), vue Maintenant (#6), messages porteurs de données (l'interface relit toujours par REST).
