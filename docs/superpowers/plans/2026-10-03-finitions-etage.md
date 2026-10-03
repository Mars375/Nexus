# Plan — Maintenant : finitions de l'étage (#28)

Spec : issue #28. État vérifié sur `master` (après #29 et #33) :

| Point | État |
|---|---|
| 1. Étage ~25 % plus petit que l'espace (marges du viewBox) | non traité ici : la marge `PAD` n'explique que ~2,5 % en largeur et ~8 % en hauteur ; la place perdue vient surtout de la légende des nœuds (une ligne par nœud) que le cadre réserve. Tentative de resserrement annulée après relecture (cadre plus haut que master, étiquette hors cadre pendant un glisser). Suite : légende compacte, issue à part |
| 2. Sous 800 px, seulement le nom de l'agent | à faire : tâche tronquée (choix de Loïc, 2026-10-03) |
| 3. Légende « lecture des nœuds… » contre tuile « illisibles » | corrigé par #29 (`Floor.tsx` légende et `NowView.tsx` tuile suivent `nodesFailed`/`isError`) |
| 4. Décalage de l'étage à 0 nœud | corrigé par #29 (`layoutFloor(…, nodes === undefined ? 1 : racks.length, …)`) |
| 5. Hachures et LED changent d'un coup | à faire : fondu par opacité d'un calque |
| 6. Plus de 7 nœuds : baies hors de la profondeur | à faire |
| 7. `/api/now` relit tous les `working` | traité par #29 : filtre SQL `NOT EXISTS` sur colonnes indexées (`ix_events_kind`, `ix_events_actor`, `ix_events_task_id`) ; à borner seulement si l'historique devient un problème mesuré |
| 8. Mise en forme `now.py` | à faire : `ruff format` (`tasks ={` à la ligne 92) |

## Étapes (TDD : test d'abord, chaque étape commitée verte)

### 1. Baies dans la profondeur (`iso.ts`, `iso.test.ts`)
- Test d'abord : pour `rackCount` de 1 à 12, toutes les baies tiennent dans `[0, depth]` (y + profondeur de baie ≤ `depth`), sans se chevaucher.
- Au-delà de 7 baies, colonnes de 7 au plus, espacées de 3,6 unités pour que les LED d'une baie ne soient pas cachées par la colonne voisine aux quatre quarts de tour ; à 7 nœuds ou moins, positions inchangées.

### 2. viewBox resserré (abandonné, voir tableau) (`iso.ts`, `iso.test.ts`, e2e)
- Test d'abord : le cadre fixe contient toujours, à chaque angle échantillonné, le sol, les baies et les étiquettes écartées (test existant) ; nouveau test : la marge entre ce contenu et le bord du viewBox ne dépasse pas une petite valeur (≤ 2 unités) sur au moins un côté horizontal et un côté vertical.
- Réduire `PAD` au minimum qui garde le test de contenance vert ; ne rien couper (traits de rappel, étiquettes du dessous, coins réservés `zonesOf`).
- e2e existants (aucun chevauchement à 1440 et 1100 px, avant et après un glisser) restent verts.

### 3. Étiquettes sous 800 px (`Floor.tsx`, `Floor.test.tsx`, e2e)
- Sous 800 px de largeur d'étage : nom de l'agent puis la tâche sur une ligne, tronquée par « … » (CSS `truncate` avec largeur max) ; la durée reste réservée à 800 px et plus.
- Test unitaire : la tâche est rendue dans l'étiquette à toutes les largeurs (classe de troncature présente).
- e2e : nouveau cas à 800 px de largeur de fenêtre (étage < 800 px) : aucune étiquette n'en recouvre une autre, avant et après un glisser.

### 4. Fondu hachures et LED (`floor.css`, `Floor.tsx`)
- Les hachures d'un blocage et l'état de la LED deviennent des calques superposés dont seule l'`opacity` change (transition), au lieu d'un `fill` `url()`/`none` qui saute.
- `prefers-reduced-motion` : pas de transition.
- Test unitaire : le calque de hachures existe toujours, son opacité dépend de l'état (`data-block`).

### 5. `ruff format` sur `server/src/nexus/now.py`

## Vérifications avant PR
`pnpm lint`, `pnpm test`, e2e de `web/e2e/now.spec.ts`, captures 1440/1100/800 px dans le scratchpad. PR : `Closes #28`, tableau ci-dessus dans le corps.
