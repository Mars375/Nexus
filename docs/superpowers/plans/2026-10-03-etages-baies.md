# Plan — Maintenant : étages de baies (#36)

Spec : issue #36 (choix de Loïc). Termine le point 1 de #28 (« étage plus petit que l'espace » : la légende d'une ligne par nœud que le cadre réservait), issue déjà fermée : la PR y renvoie avec `Refs #28` et ferme `Closes #36`.

## Principe

L'étage 1 reste le bureau (postes, table, 4 premières baies). Les nœuds suivants montent par paquets de 4 dans des **salles des serveurs** : un sol plus petit, centré, dessiné **dans le cadre fixe de l'étage 1**, avec la même projection et le même angle. Changer d'étage ne change que ce qui est dessiné, jamais le cadre, l'angle ni les coins HTML fixes. Le mouvement est une réaction ponctuelle (ascenseur, cascade de LED, pastille), jamais une boucle.

## Modèle de données (`web/src/now/model.ts`)

- `RACKS_PER_FLOOR = 4`. `nodeFloors(nodes: NodeState[]): NodeState[][]` : tri par `id` (comparaison de code, `a.id < b.id`, pas `localeCompare` qui dépend de la locale), puis paquets de 4. Étage 1 = paquet 0. L'ordre ne dépend que de l'ensemble des `id`, jamais de `status` ni de l'ordre de la réponse : un nœud qui passe hors ligne ne fait changer personne d'étage.
- Nombre d'étages : `nodes === undefined` → 1 (l'étage 1 garde sa baie fantôme « lecture des nœuds… », comme aujourd'hui) ; sinon `max(1, ceil(n / 4))`. 0 nœud → 1 étage, 0 baie, pas de sélecteur.
- `floorAlert(nodes, stale): 'off' | 'unknown' | null` par étage : `'off'` (rouge, `--danger`) si un nœud est `offline` et frais ; sinon `'unknown'` (ambre, `--attention`) si un nœud est `unknown` ou périmé, ou si la relecture a échoué (`nodesFailed`) ; sinon `null`. **`offline-by-design` ne donne pas de pastille** (sinon artemis, hors ligne prévu, garderait une alerte rouge permanente).
- La tuile « Nœuds en ligne » de `NowView.tsx` reste globale (inchangée, un test le fixe à 12 nœuds).

## Géométrie (`web/src/now/iso.ts`)

- `layoutFloor(agentCount, rackCount, angle = 0, floorCount = 1)` : l'étage 1, inchangé pour `floorCount = 1` (le composant passe `rackCount = min(4, n)`, donc une seule colonne de baies ; le code multi-colonnes reste, testé, inutilisé par l'UI : suppression hors périmètre).
- **Zones** : `zonesOf(vb, legendRows, selector)` ; `legendRows = max(1, min(rackCount, RACKS_PER_FLOOR))` : la légende ne dépasse plus 4 lignes, quel que soit le nombre total de nœuds (c'est ce qui rendait l'étage plus petit). Quand `floorCount > 1`, la zone haut-gauche s'agrandit pour le sélecteur, sous les boutons de rotation (`SELECTOR = { w: 170, h: 40 }` en px au rendu minimal). La clé du cache `frames` devient `${agentCount}:${rackCount}:${floorCount > 1}`.
- **Cadre unique** : `fixedFrame` fait aussi grandir le cadre sur la salle des serveurs (sol, sommets des baies, chemin de câbles) à chaque angle échantillonné. La salle étant contenue dans l'emprise au sol de l'étage 1 et centrée sur le même centre de rotation, c'est un garde-fou sans effet attendu : pour `floorCount = 1`, le viewBox reste celui de `master` (valeurs relevées avant le changement et figées dans un test). Les tests `fixedFrame` existants restent verts tels quels.
- `layoutServerFloor(base: Layout, rackCount: number): ServerFloor` (pure) réutilise `base.project`, `viewBox`, `sees`, `depthOf`, `angle`, `zones` : aucun cadre propre, donc rien ne saute.
  - `room` : `SERVER_ROOM = { w: 11, d: 7 }` centré sur `(base.width / 2, base.depth / 2)` ; taille constante pour 1 à 4 baies.
  - `racks` : une rangée le long de x, pas `RACK_PITCH`, centrée sur le centre de la salle (`x_i = cx - ((k - 1) × pitch + RACK.w) / 2 + i × pitch`, `y = cy - RACK.d / 2`) : 1 à 3 baies restent centrées, et le centre de la rangée est le centre de rotation, donc centrée à chaque quart de tour.
  - `aisles` : allée froide devant la face LED (+y, dalles perforées) et allée chaude derrière, symétriques (`(room.d - RACK.d) / 2` chacune).
  - `tray` : chemin de câbles, boîte fine (`h 0,12`) à `z = RACK.h + 0,35`, longueur fixe d'une rangée de 4 (ne change pas d'un étage à l'autre).
  - `marker` : matrice affine `matrix(a b c d e f)` du plan du sol à `z = 0` (dérivée de `project`), pour poser « ÉTAGE n » sur le sol de l'allée froide ; il tourne avec l'étage.
  - Face LED : `+y` si visible, sinon `-y` (LED avant et arrière) ; jamais `±x`, qu'une voisine de rangée peut cacher. Repli sur la chaîne actuelle à 45° pile.
- `drawOrder` reste pour l'étage 1 ; salle : sol, dalles, marquage, baies par `depthOf`, chemin de câbles en dernier.

## Composants

- **`useFloorLevel(count, { loaded })`** (nouveau `web/src/now/useFloorLevel.ts`, sur le modèle de `useFloorRotation`) : étage demandé gardé dans une variable de module (session de la page, aucun stockage navigateur, ADR-017), `resetFloorLevel()` pour les tests. Retourne `{ floor, count, go(delta), dir, layers }`.
  - `go(±1)` part de la **cible** (pas de l'étage affiché) : deux ▲ rapides depuis l'étage 1 donnent 3 ; borné à `[1, count]`.
  - Étage disparu (moins de nœuds) : `floor = min(demandé, count)`, écrit en mémoire **seulement quand `loaded`** (données réellement lues), pour qu'une lecture en cours au remontage n'efface pas l'étage 3 ; repli instantané, sans ascenseur (ce n'est pas une action).
  - `layers` : l'étage courant plus les étages qui partent, chacun `{ floor, role: 'current' | 'leaving', from: 'above' | 'below' }` ; un étage qui part est démonté après `LEVEL_MS + 50` ms (minuteur, pas `transitionend`, absent en jsdom et sous mouvement réduit). Mouvement réduit : jamais de couche `leaving`.
- **`Floor`** : compose `useFloorRotation` et `useFloorLevel` ; `onKeyDown` de la scène enchaîne ← → (rotation) puis PageUp / PageDown (étage, `preventDefault`). Sélecteur en haut à gauche, sous ↺ ↻, rendu seulement si `count > 1` : `<button aria-label="Monter d'un étage">▲</button>`, « Étage n / N » (`aria-live="polite"`), `<button aria-label="Descendre d'un étage">▼</button>`, `disabled` aux bornes ; à côté, une pile de repères d'étage (le plus haut en haut), chacun avec `data-alert` et un texte pour lecteur d'écran (« Étage 3 : un nœud hors ligne » / « … état inconnu »).
- **`FloorScene`** reçoit `floor` et `floorCount` (défaut 1, les tests actuels ne changent pas d'appel). Chaque couche est un `div.level` (`absolute inset-0`) qui contient son `<svg>` et, à l'étage 1, les étiquettes HTML et traits de rappel ; la couche qui part a `inert` et `aria-hidden`. Les `<defs>` (dégradés, hachures) passent dans un `<svg>` unique de taille nulle, pour ne pas dupliquer les `id`. Restent hors des couches : légende (nœuds de l'étage affiché seulement, ≤ 4 lignes), sélecteur, boutons de rotation. « TA TABLE » n'est rendu qu'à l'étage 1. Nom accessible de la salle : « Étage n de Nexus : salle des serveurs, k baies ».
- La scène expose `data-floor`, `data-floor-count` et `data-floor-dir="up" | "down"` (absent au premier rendu).

## Mouvement (`web/src/now/floor.css`)

Transitions CSS sur `transform` et `opacity` seulement ; le JS ne décide que des couches montées et de leurs attributs. Une transition repart de la valeur calculée courante quand sa cible change : une pression pendant l'animation reprend donc proprement là où en est l'étage.

- **Ascenseur** : `.level { transition: transform 350ms cubic-bezier(0.2, 0.7, 0.2, 1), opacity 350ms }`. Couche qui arrive : `@starting-style` à `translateY(∓8%)`, opacité 0, selon `data-from`. Couche qui part : `data-role="leaving"` → `translateY(±8%)`, opacité 0. En montant : l'ancien étage descend, le nouveau vient d'en haut ; l'inverse en descendant. Navigateur sans `@starting-style` : la couche apparaît sans glisser (dégradation acceptable ; WebView2 est Chromium).
- **Baies qui se posent** : chaque `g.rack` de la couche qui arrive a `--i` (0 à 3) et `@starting-style { transform: translateY(-12px) ; opacity: 0 }` avec `transition-delay: calc(var(--i) * 40ms)`.
- **Cascade de LED** à l'arrivée sur une salle : `data-arriving` sur la couche, retiré après la cascade ; `.led, .led-on, .led-ring { animation: now-led-in 240ms calc(var(--i) * 40ms) backwards }` avec `@keyframes now-led-in { from { opacity: 0 } }` : la fin est l'opacité de l'état de la baie, jamais un vert forcé.
- **Numéro qui roule** : le chiffre `n` dans un `span` à `overflow: hidden`, re-clé à chaque changement, `animation: now-roll-up | now-roll-down 350ms` (une fois).
- **Pastille** : alerte nouvelle (`useArrivals` sur les `id` en alerte) sur un étage **non affiché** → `is-fresh` sur son repère, une pulsation `transform: scale` unique, comme `now-fresh`.
- `prefers-reduced-motion` : ajout de `.level, .rack, .floor-pick *` au bloc existant (`transition: none; animation: none`) ; côté JS, ni couche `leaving`, ni `data-arriving`, ni `is-fresh`.

## Étapes (TDD : test d'abord, chaque étape commitée verte)

### 1. Étages des nœuds (`model.ts`, `model.test.ts`)
- 0, 1, 4, 5, 8, 9, 12 nœuds → 1, 1, 1, 2, 2, 3, 3 étages, paquets ≤ 4 ; même ensemble d'`id` dans un autre ordre ou avec d'autres `status` → mêmes étages ; `floorAlert` : `offline` rouge, `unknown` et périmé ambre, `offline-by-design` rien, relecture en échec ambre partout.

### 2. Zones et cadre de l'étage 1 (`iso.ts`, `iso.test.ts`)
- viewBox de (1, 0), (8, 4), (12, 4) agents/baies égal aux valeurs de `master` (figées) ; légende de 4 lignes au plus pour 5 à 12 nœuds ; avec `floorCount > 1`, aucune étiquette ne touche la zone du sélecteur à chaque quart de tour, pour 8 et 12 agents ; tests existants inchangés.

### 3. Salle des serveurs (`iso.ts`, `iso.test.ts`)
- Pour 1 à 4 baies : viewBox identique à celui de l'étage 1 à tous les angles ; sol, sommets des baies, chemin de câbles et marquage dans le cadre tous les 5° ; salle contenue dans l'emprise de l'étage 1 ; centre de l'enveloppe projetée des baies = projection du centre du sol (à 0,5 unité près) à 0, 90, 180, 270° ; aucune LED cachée par une autre baie ni par le chemin de câbles aux quarts de tour ; baies sans chevauchement, dans la salle.

### 4. État de l'étage (`useFloorLevel.ts`, `useFloorLevel.test.tsx`)
- Borne et `disabled` ; deux `go(+1)` rapides → 3 ; mémoire au remontage ; repli quand `count` baisse (écrit seulement si `loaded`) ; `dir` ; couche `leaving` démontée après le délai (faux minuteurs) ; aucune couche `leaving` sous mouvement réduit (`matchMedia` simulé).

### 5. Scène par étage (`Floor.tsx`, `Floor.test.tsx`)
- Pas de sélecteur jusqu'à 4 nœuds ; à 12 : ▲ ▼ avec noms accessibles, « Étage 1 / 3 » ; ▲ affiche l'étage 2 : 4 baies, aucun poste, ni table, ni « TA TABLE », légende des seuls nœuds de l'étage ; angle conservé au changement d'étage (`data-angle`) ; `data-floor-dir` vaut `up` puis `down` ; PageUp / PageDown sur la scène ; repère d'étage 3 rouge avec texte lu quand un de ses nœuds est hors ligne, rien pour `offline-by-design` ; test des LED cachées et de la légende réécrits par étage.

### 6. Mouvement (`floor.css`, `Floor.tsx`, `Floor.test.tsx`)
- Aucune classe ni attribut d'animation au premier rendu ; `data-arriving` et `--i` à l'arrivée sur une salle ; `is-fresh` sur le repère d'un autre étage quand une alerte y apparaît, jamais sur l'étage affiché ; sous mouvement réduit : ni couche `leaving`, ni `data-arriving`, ni `is-fresh`.

### 7. Bout en bout (`web/e2e/now.spec.ts`)
- `page.route('**/api/nodes')` sert 12 nœuds (le serveur n'en connaît que 4). Étage 1 → 3 au clavier (PageUp ×2) puis retour aux boutons ; aucune étiquette ne recouvre une autre ni un coin fixe (`expectNoLabelOverlap` compte désormais les boutons présents au lieu de 4) ; un nœud de l'étage 3 hors ligne → repère d'étage 3 visible ; deux clics rapides sur ▲ → `data-floor="3"` puis, après 400 ms, une seule couche `.level` et son opacité calculée à 1 (aucun état intermédiaire figé).

## Risques et cas limites

- **0 nœud, nœuds non lus, relecture en échec** : 1 étage sans sélecteur ; lecture → baie fantôme actuelle ; échec avec données gardées → étages conservés, toutes les pastilles ambre.
- **Moins de nœuds sur l'étage 3** : repli sur le dernier étage existant, sans animation ; pas d'écriture pendant une lecture.
- **Alerte sur un étage caché** : pastille et texte lu dans le sélecteur ; la tuile globale compte toujours tout.
- **Rotation pendant l'ascenseur** : les deux couches reçoivent le même `angle` ; un glisser reste possible (le sélecteur est un `button`, ignoré par `onPointerDown`).
- **Zone du sélecteur** : au-delà de 4 nœuds, le cadre de l'étage 1 réserve un peu plus de place en haut à gauche (étage un peu plus petit qu'à 4 nœuds) ; à mesurer sur les captures.
- **`@starting-style`** : non simulé par jsdom ; la reprise propre n'est vérifiable qu'en e2e.

## Hors périmètre

Choix direct d'un étage par clic sur un repère, Home / End, mémoire entre sessions, plus de 4 baies par étage, suppression du code multi-colonnes de `layoutFloor`, détail d'un nœud au survol, nouvelles données serveur.

## Vérification avant PR

`pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm e2e` ; captures dans le scratchpad à 0/90/180/270°, à 1 440 et 1 100 px, pour l'étage 1, une salle pleine (4 baies) et une salle incomplète (1 à 3) ; grille `docs/agents/review-checklist.md` §6 (UI avec données changeantes) et §9. PR : `Closes #36`, `Refs #28` (point 1).

## À trancher par Loïc

1. Ordre des nœuds : tri par `id` (robuste, mais la légende actuelle passe de helios, cortex, synapse, artemis à artemis, cortex, helios, synapse) ou ordre de la réponse serveur (tuple `NODES`, à garantir par un test serveur).
2. `offline-by-design` sans pastille (proposé), ou pastille neutre.
3. « TA TABLE » masqué sur les salles des serveurs (proposé), ou gardé dans son coin.
4. Sélecteur sous les boutons de rotation, en haut à gauche (proposé).

## Décisions de Loïc (2026-10-03), prioritaires sur ce qui précède
- **Nœud éteint par conception** (`offline_by_design`, ex. Artémis) : pas de pastille sur le sélecteur ; sa baie reste affichée éteinte sur son étage.
- **Ordre des nœuds = ordre d'importance, défini côté serveur** : le tuple `NODES` de `server/src/nexus/nodes.py` devient cortex, synapse, artemis, helios (commentaire : ordre d'importance, il fixe l'étage de chaque nœud). L'interface garde l'ordre reçu de `/api/nodes`, sans tri par `id`. Un test serveur fige cet ordre ; un test d'interface vérifie que l'ordre reçu est conservé et que l'étage d'un nœud ne dépend pas de son statut. Un nœud absent de la réponse suivante ne décale pas les autres d'étage tant que la liste du serveur est la même (l'ordre vient du serveur, pas de la présence).
- **« TA TABLE »** : visible à tous les étages (une demande reçue ne disparaît pas parce que l'on regarde les baies).
- **Sélecteur** : en haut à gauche, sous ↺ ↻ (proposition retenue) ; les captures mesurent la taille de l'étage 1 au-delà de 4 nœuds.

## Ajustements après relecture (2026-10-03)

Prioritaires sur ce qui précède.

### A. Salle des serveurs sur l'emprise de l'étage 1 (option A de Loïc)
- La salle reprend exactement les dimensions du sol de l'étage 1 (`SERVER_ROOM` disparaît) : même emprise de bâtiment, cadre fixe et viewBox de l'étage 1 inchangés (identiques à `master` jusqu'à 4 nœuds, gelés par un test), rien ne saute au changement d'étage.
- La rangée de baies reste centrée (1 à 3 baies aussi) ; allées froide (devant la face LED) et chaude (derrière) de même profondeur, le long de la rangée.
- Décor sobre, statique et manifestement décoratif : dalles techniques sur tout le sol (une seule trace), dalles perforées de l'allée froide, un groupe de refroidissement à chaque bout de la rangée de quatre (position fixe), chemin de câbles de groupe à groupe, marques de zone de travail au sol.
- Règle stricte (checklist §5) : aucun décor ne ressemble à une donnée (ni voyant, ni jauge, ni valeur) ; aucune animation ; moins de 40 éléments SVG hors baies (testé).
- Tests : tout reste dans le cadre fixe à chaque angle échantillonné (unités et marques comprises), baies centrées aux quatre quarts de tour, aucune LED cachée (autre baie, unité de refroidissement, chemin de câbles).

### B. Étiquettes des baies (données réelles seulement)
- Chaque baie d'une salle porte une étiquette HTML placée et écartée par la même mécanique que les postes (`placeLabels` généralisé, `spreadLabels`) : aucune ne touche une autre étiquette ni un coin fixe. Hauteur estimée plus prudente (62 unités) : la scène, limitée en hauteur, peut descendre sous 1 px par unité.
- Contenu : nom du nœud en majuscules (couleur du ton), état en français du modèle (« périmée » et relecture en échec compris) + « · vu il y a … » pour un nœud hors ligne ou inconnu avec `last_seen`, puis `gardien : <agent>` (le nom d'affichage de l'agent). Sous 800 px : lignes 1 et 2 seulement, la ligne 2 est tronquée.
- Légende : celle de l'étage 1 est inchangée. Sur une salle, la légende complète devient lisible par les lecteurs d'écran seulement (`sr-only`) ; une ligne « n / m en ligne » (baies fraîches et en ligne) la remplace à l'écran ; les étiquettes visuelles sont `aria-hidden`.
- Le cadre commun des étages multiples réserve la place de ces étiquettes (pour 4 nœuds et moins, aucun changement).

### C. Constats du reviewer
1. Test de la pastille : un vrai identifiant (`cortex`) ; vérifié en retirant la condition « étage affiché » (le test échoue), puis rétablie.
2. ▲ et ▼ aux bornes : `aria-disabled="true"` au lieu de `disabled`, le focus reste sur le bouton ; PageUp et PageDown continuent de fonctionner.
3. Repli quand un étage disparaît : `lifted`, `arriving` et les couches qui partent sont remis à zéro ; ni glissement ni numéro qui roule.
4. Ordre DOM stable des couches (par étage, la couche affichée passe devant par `z-index` dans un conteneur `isolation: isolate`) : un aller-retour 1 → 2 → 1 ne détache plus aucun nœud. Test jsdom (`MutationObserver`) et test e2e (opacité échantillonnée, aucune image à 0).
5 et 6. Plus de liste de repères : voir D2. L'étage affiché reste identifié par le texte « Étage n / N » (zone `aria-live`) ; alertes dites par les noms des boutons et par l'étiquette.

### D. Trois défauts vus sur les captures
1. « ÉTAGE n » : posé sur l'allée la plus proche du spectateur (les baies, derrière, ne la cachent jamais), retourné de 180° quand son sens de lecture irait vers la gauche, jamais en miroir. Testé tous les 5°.
2. Repères : la colonne de trois points est supprimée. Une pastille sur ▲ (étage au-dessus en alerte) et sur ▼ (au-dessous), de la couleur de l'alerte la plus grave (rouge hors ligne, ambre inconnu ou périmé, rien pour hors ligne prévu), jamais pour l'étage affiché ; texte « Étage 2 / 3 · alerte à l'étage 3 » ; noms accessibles « Monter d'un étage : un nœud hors ligne à l'étage 3 ». Une alerte nouvelle fait pulser la pastille du côté concerné, une fois.

### E. Cette section.

### Ajustements de la relecture 2
- Le marquage « ÉTAGE n » est un obstacle fixe pour l'écart des étiquettes de baies ; la légende lue par les lecteurs d'écran reprend toutes les lignes de l'étiquette (`rackDetail`, « vu il y a » seulement si la date est plausible), le nombre de nœuds en alerte est dit au pluriel, et un repli pendant l'ascenseur se fait sans transition (`data-snap`).
- L'estimation de hauteur des étiquettes de baie passe de 62 à 71 unités (scène basse : 0,53 px par unité) : le cadre des étages multiples grandit de 5,3 % (1 020,7 à 1 074,7), celui de l'étage 1 jusqu'à 4 nœuds ne change pas ; les e2e des salles couvrent 1 100, 1 366, 1 400 (hauteur 600) et 1 440 px.
