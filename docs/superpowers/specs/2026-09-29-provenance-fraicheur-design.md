# Provenance et fraîcheur partout — conception (#8)

**Date :** 2026-09-29 · **Issue :** #8 · **Références :** ADR-005, DATA-MODEL §1 et §5, VIEWS §9, PRD FR-5

## But

Toute donnée affichée dit d'où elle vient et quand elle a été mesurée ; une donnée trop vieille change visiblement d'état. Aucune route de l'API ne peut renvoyer une donnée sans provenance sans faire échouer les tests.

## Décisions (validées avec Loïc le 2026-09-29)

1. **Affichage par vue et dans le détail.** Une ligne discrète en en-tête du tableau Travail (toutes les cartes viennent de la même lecture) ; la provenance complète dans le panneau d'une tâche. Pas de provenance sur chaque carte.
2. **Péremption = 3 × la cadence de rafraîchissement** du type de donnée, calculée dans l'interface (option A).
3. **« [ouvrir] » seulement si la source a une adresse** : champ facultatif `source_url` ; absent pour `nexus.db` et Tailscale.

## Contrat API

- Tout objet renvoyé par une route `GET` de l'API — chaque élément d'une liste, chaque sous-bloc d'une réponse composée (ex. `db`, `backup` de `/api/health`) — porte `source` (texte non vide) et `measured_at` (ISO-8601 avec fuseau).
- `source_url` est facultatif ; quand il est présent, c'est une URL `https://` (jamais une valeur libre).
- **Test générique** (`server/tests/test_provenance_contract.py`) : il parcourt les routes `GET` déclarées dans l'application FastAPI (hors `/docs`, `/openapi.json`), prépare une donnée de chaque sorte (une tâche avec commentaire et historique ; un événement une fois #4 fusionné), appelle chaque route et vérifie le contrat sur chaque objet renvoyé. Une nouvelle route sans provenance fait échouer ce test sans qu'il faille l'y ajouter à la main.
- Correction attendue : le bloc `backup` de `/api/health` reçoit un `measured_at`.

## Interface

### Registre des cadences (`web/src/freshness.ts`)

- `REFRESH_MS` par type : `tasks` 10 s (déjà `TASKS_REFRESH_MS`), `health` 10 s, `nodes` 60 s. Les requêtes TanStack Query lisent leur `refetchInterval` dans ce registre : une seule source de vérité.
- `STALE_FACTOR = 3` ; `isStale(measuredAt, kind, now)` vrai si `now - measuredAt > 3 × REFRESH_MS[kind]`.
- `measured_at` vient du serveur (même machine, pas de décalage d'horloge à gérer en Phase 1). Une date illisible compte comme périmée (honnêteté, ADR-005).

### Horloge (`useNow`)

- Un seul intervalle d'une seconde, partagé par tous les composants qui l'utilisent ; l'âge affiché avance même sans nouvelle lecture, et c'est précisément ainsi qu'une donnée devient périmée quand le serveur ne répond plus.

### Composant `Provenance` (`web/src/Provenance.tsx`)

- Props : `source`, `measuredAt`, `kind`, `url?`.
- Rendu : `nexus.db · mesuré il y a 32 s` ; `· ouvrir` en lien (nouvel onglet, `rel="noreferrer"`) si `url` est présente.
- Périmée : texte coloré « attention » et mot explicite « périmée » (la couleur seule ne suffit pas) ; `title` donne l'heure exacte de mesure.
- Accessible : texte lisible par un lecteur d'écran, pas d'animation sans changement réel (motion : seul le passage à « périmée » est un changement d'état).

### Intégration

- **Travail** : en-tête du tableau (`WorkView`) avec la provenance de la liste des tâches ; panneau d'une tâche (`TaskPane`) avec la provenance de la tâche, et celles des commentaires et de l'historique dans leurs sections.
- **Santé** : `HealthStatus` réécrit avec `Provenance` (même texte qu'aujourd'hui, plus l'état périmé).
- **Maintenant (#6)** et **Nœuds** (pas encore d'interface) l'utiliseront à leur arrivée ; hors périmètre ici.

## Cas limites

- Données en cache après un rafraîchissement raté : l'âge continue d'avancer, la donnée passe « périmée » (cohérent avec « non à jour » déjà affiché).
- `measured_at` dans le futur (horloge) : âge affiché « à l'instant », jamais négatif.
- `source_url` non `https://` : ignorée par l'interface (pas de lien), refusée par le test de contrat côté serveur.
- Rendu initial sans données : pas de provenance affichée (rien n'est mesuré), l'état de chargement existant suffit.

## Tests

- Serveur : test générique de contrat (échoue aujourd'hui sur `backup` : RED réel).
- Web (Vitest) : `isStale` aux bornes (3 × cadence, date illisible, date future) ; `Provenance` affiche « périmée » quand l'horloge dépasse le seuil (faux timers) et le lien seulement avec une URL https.
- Playwright : l'en-tête Travail et le panneau d'une tâche affichent la provenance (le passage à « périmée » est couvert par les tests Vitest à faux timers, sans attendre 30 s).

## Hors périmètre

Vue Nœuds, vue Maintenant, `source_url` réelles (arrivent avec les adaptateurs, Phase 2).
