# Plan — Maintenant : faire pivoter l'étage (#30)

Spec : issue #30. Choix validés par Loïc le 2026-10-03 :

- **Cadre fixe** : le viewBox est calculé une fois pour contenir l'étage à tous les angles ; rien ne saute pendant la rotation.
- **Légende des baies dans un coin fixe, sans traits de rappel** : une ligne par baie, avec une pastille de la couleur (ton) de la baie.
- **Étiquettes des postes au-dessus de leur bureau**, avec le même trait de rappel vertical. Révisé pendant l'implémentation : la rangée la plus proche du spectateur a son étiquette en dessous du bureau, et `spreadLabels` écarte celles qui se chevauchent encore (validé par Loïc).

## Principe

Le plan au sol ne change pas (`layoutFloor` place postes, table et baies en unités de sol). Seule la **projection** change : un point `(x, y, z)` est d'abord tourné d'un angle `θ` autour du centre du sol, puis projeté en isométrique comme aujourd'hui. À `θ = 0`, le rendu est identique à l'actuel (au placement de la légende et des étiquettes près).

## Étapes (TDD : test d'abord, chaque étape commitée verte)

### 1. Géométrie (`web/src/now/iso.ts`, `iso.test.ts`)

- `layoutFloor(agentCount, rackCount, angle = 0)` : `project` applique la rotation `angle` (degrés) autour de `(width / 2, depth / 2)` avant la projection isométrique.
- **viewBox fixe** : bornes calculées sur tous les angles (coins du sol et sommets des baies, angle échantillonné tous les 5° ou borne analytique par le rayon du sol), plus les marges actuelles ; indépendant de `angle`. Plus de marge droite dédiée à la légende.
- **Faces visibles** : `box()` renvoie le dessus et les **faces latérales visibles** (normale tournée avec `nx + ny > 0`), chacune avec sa classe d'ombre (`f-left` si `nx - ny < 0`, sinon `f-right`). À `θ = 0` : exactement les faces `left` et `right` actuelles.
- **Ordre de dessin** : fonction pure `depthOf(x, y)` (profondeur après rotation, `x' + y'`) pour trier postes, baies et table du fond vers l'avant.
- **Calage** : `nearestQuarter(angle)` → multiple de 90 le plus proche (gère les angles négatifs et > 360).
- `legend` disparaît du `Layout` (la légende devient un coin HTML fixe).
- Tests : rendu à 0° identique aux points actuels ; à 0/90/180/270°, aucune face cachée rendue et deux faces latérales par boîte ; ordre de dessin correct à chaque quart de tour (un bureau devant n'est jamais dessiné avant un bureau derrière) ; tout le sol et toutes les baies tiennent dans le viewBox à chaque angle échantillonné ; `nearestQuarter` (44 → 0, 46 → 90, -46 → -90 ou 270 normalisé, 359 → 360/0).

### 2. Rendu (`web/src/now/Floor.tsx`, `Floor.test.tsx`)

- `Faces` rend la liste de faces latérales renvoyée par `box()`.
- Postes, baies et table rendus dans l'ordre de `depthOf`.
- **Écran du poste** : dessiné seulement si sa face (normale +y du plan) est visible ; sinon le dos du moniteur (une face de la boîte du moniteur suffit).
- **LED des baies** : sur la face +x seulement si elle est visible ; sinon sur l'autre face latérale visible.
- **Étiquettes** : au-dessus du bureau pour la rangée du fond, en dessous pour la rangée la plus proche (`labelBelow`, selon la profondeur à l'angle courant) ; `spreadLabels` décale ensuite celles qui se chevauchent ; traits de rappel recalculés à l'angle courant.
- **Légende** : coin bas-droit fixe en HTML, une ligne par baie : pastille au ton de la baie (`data-tone`) + texte actuel. « lecture des nœuds… » / « nœuds illisibles » au même endroit.
- Fils de demande et tickets : inchangés (ils passent par `project`).

### 3. Interaction (`Floor.tsx`, nouveau `useFloorRotation.ts` + tests)

- **Glisser** horizontal (pointer events, souris et tactile) : `angle = départ + dx × 0,4°`. Au relâchement : animation ~300 ms (requestAnimationFrame, easing) vers `nearestQuarter`. `prefers-reduced-motion` : calage immédiat, pas d'animation.
- **Clavier** : la scène a `tabIndex=0` et un nom accessible ; ← → tournent de 90° (animés, sauf mouvement réduit).
- **Boutons** ↺ ↻ sur la scène (vrais `<button>`, nom accessible « Tourner l'étage vers la gauche / droite »).
- Un clic sur une étiquette après un glisser ne doit pas ouvrir la tâche (seuil de quelques px avant de considérer un glisser).
- **Mémoire** : angle gardé dans une variable de module (session de la page), pas de stockage navigateur (ADR-017). Rien ne tourne tout seul.
- La liste des agents (lecteurs d'écran, < 760 px) est inchangée.

### 4. Bout en bout (`web/e2e/now.spec.ts`)

- Glisser sur l'étage puis relâcher : l'angle se cale (attendre la fin de l'animation), et **aucune étiquette de poste n'en recouvre une autre** aux trois largeurs du test existant.
- ← au clavier puis → : retour à l'angle de départ.

## Hors périmètre

Zoom, rotation verticale, mémorisation de l'angle entre sessions, nouvelles données.

## Vérification avant PR

`pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm e2e` ; contrôle visuel (capture) à 0°, 90°, 180°, 270° à 1 440 et 1 100 px ; grille `docs/agents/review-checklist.md` §6 (UI avec données changeantes) et §9.
