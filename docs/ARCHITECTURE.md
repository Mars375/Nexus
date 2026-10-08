# ARCHITECTURE — Nexus

**Version :** 0.2 (refonte : application autonome — ADR-011)
**Date :** 2026-09-28

---

## 1. Vue d'ensemble

```text
┌─────────────────────────────────────────────────────────────────┐
│  SURFACES                                                        │
│  UI web locale : Maintenant · Travail · Conversations · Inbox ·  │
│  Planning · Code · Système · À ne pas oublier                    │
│  Telegram (alertes mobiles)                                      │
├─────────────────────────────────────────────────────────────────┤
│  CORE NEXUS (local, zéro LLM par défaut)                         │
│  · Modèle propre : Task / Run / Event / Conversation / Approval… │
│  · nexus.db = source de vérité de la coordination                │
│  · Politiques (une op principale, unknown, preuves, gating)      │
│  · API d'événements (agents → Nexus) + WebSocket (Nexus → UI)    │
│  · Dispatch explicite (« confier à ») — jamais automatique       │
├─────────────────────────────────────────────────────────────────┤
│  ADAPTATEURS (un par système externe, remplaçables)              │
│  exécutants : hermes · claude-code · codex · orca                │
│  données    : chats · mail · calendar · git · memory · infra ·   │
│               nodes · quotas · cron                              │
├─────────────────────────────────────────────────────────────────┤
│  SYSTÈMES EXTERNES (propriétaires de leurs données)              │
│  Hermes · Claude/Codex/Orca · Telegram · Gmail · Google Calendar │
│  Git/GitHub · Hindsight · Synapse · nœuds                        │
└─────────────────────────────────────────────────────────────────┘
```

## 2. Décision structurante : application autonome

- **Nexus possède son modèle et ses données** (ADR-011, ADR-012) : tâches, événements, approbations, décisions, conversations natives, preuves. Ils vivent dans `nexus.db`.
- **Aucun système externe n'est sa colonne vertébrale.** Hermes, Gmail, Git, etc. sont branchés derrière des adaptateurs ; si l'un disparaît, seul son adaptateur change.
- **Les données externes restent chez leur propriétaire** (ADR-016) : Nexus les lit, peut en garder un index/cache daté pour la recherche et l'affichage, et agit via l'adaptateur — il n'en devient pas la source.
- **Aucune exécution automatique** : une tâche ne part chez un exécutant que par « confier à » (ADR-012, ADR-015).

## 3. Composants

### 3.1 Core Nexus

| Module | Rôle |
|---|---|
| `model` | Types (Task, Run, Event, Conversation, Message, Artifact, Approval, Decision…) et validations |
| `store` | Accès `nexus.db` : tâches, événements, index/cache des sources externes |
| `policy` | Règles produit : une op principale, staleness, `unknown`, preuve ou review, gating |
| `events` | API d'événements : réception, validation, publication, read-back |
| `dispatch` | « Confier à » : crée le run chez l'exécutant, suit son état, rapatrie les preuves |
| `views` | Calcul des vues (agrégations, détections « à ne pas oublier ») |
| `search` | Recherche globale (tâches, chats, mails, code) avec lien vers la source |

### 3.2 Adaptateurs

Interface commune :

```text
probe()        → état de la source (joignable, fraîcheur, erreurs)
read(query)    → données normalisées + provenance
act(action)    → action sur la source (gated si sortante ou irréversible) + read-back
```

Les adaptateurs d'exécution ajoutent :

```text
dispatch(task, options) → run_ref        (création du travail chez l'exécutant)
watch(run_ref)          → événements du run (claimed, progress, blocked, done…)
```

| Adaptateur | Système | Phase | Notes |
|---|---|---|---|
| `hermes` | Hermes Kanban (`kanban.db`, CLI `hermes kanban`, dashboard API + WS) | 2 | exécutant pour Helios/Mnēma/Aether ; lit runs/events ; statuts relevés : [notes/2026-09-28-releve-enums-hermes-kanban.md](notes/2026-09-28-releve-enums-hermes-kanban.md) |
| `claude-code` | sessions `~/.claude` | 2 | lancer une session sur une tâche ; lire transcript + artefacts |
| `codex` | `codex exec -p <profil>`, `~/.codex` | 2 | idem |
| `orca` | CLI `orca`, worktrees | 2 | idem, avec worktrees |
| `chats` | gateway Hermes, Telegram, WhatsApp, `state.db` Hermes, sessions Claude/Codex | 3 | lecture des conversations ; envoi sur tous les canaux (ADR-018), gated vers un tiers |
| `mail` | Gmail | 4 | lecture, tri, brouillons ; envoi gated |
| `calendar` | Google Calendar | 4 | lecture ; création d'événement gated |
| `git` | repos locaux (`F:/Projet/…`), `gh` | 5 | commits, branches, worktrees, PR, diffs |
| `memory` | Hindsight (banks `helios`, `mnema`…) | 5 | lecture des souvenirs/rapports utiles |
| `infra` | Synapse (services, santé) | 5 | lecture ; aucune mutation croisée |
| `nodes` | Tailscale/SSH read-only, healthchecks | 1→5 | Helios, Cortex, Synapse, Artémis (éteint = `offline-by-design`) |
| `quotas` | Go usage, crédits Higgsfield, pools | 5 | fenêtres 429, soldes |
| `cron` | Hermes cron (`jobs.json`, `executions.db`) | 4 | jobs, dernier/prochain run, échecs |

### 3.3 Stockage

- **`nexus.db` (SQLite)** — source de vérité pour : tâches, événements, runs (côté Nexus), approbations, décisions, conversations natives Nexus, politiques.
- **Index/cache externe** (dans `nexus.db`, tables séparées) — snapshots datés des données externes (chats, mails, commits…) pour l'affichage et la recherche. Reconstructible depuis les sources ; jamais considéré comme vérité.
- Sauvegarde : `nexus.db` est la seule donnée non reconstructible → sauvegarde régulière obligatoire (à définir en Phase 1).
- **Restauration d'une sauvegarde** : arrêter Nexus, remplacer `nexus.db` par la copie, supprimer les fichiers `nexus.db-wal` et `nexus.db-shm`, puis redémarrer. La restauration à chaud, Nexus en marche, n'est **pas** prise en charge, et la garantie du temps réel en dépend : à chaque démarrage le serveur tire une nouvelle instance, ce qui oblige les clients à tout invalider une fois (`reset: true`), alors qu'une base remplacée sous un serveur qui tourne laisserait des curseurs périmés passer pour valides. Chaque redémarrage du serveur fait de même, une seule fois par client (voir `docs/superpowers/specs/2026-09-30-temps-reel-design.md`).

### 3.4 Interface

- **UI web locale** (servie sur le poste de Loïc) : les vues, recherche, provenance cliquable, actions. Encapsulée plus tard dans une **application Windows** (Tauri, §7).
- **Contrat UI ↔ API** (#16, ADR-020 D4) : l'UI ne parle qu'à l'API FastAPI. Le serveur exige un jeton sur toute route REST sauf `GET /api/health` (SECURITY §3). Le jeton `loic` est enregistré dans le navigateur (`localStorage`, clé `nexus.token`) ; `request()` (`web/src/api.ts`) l'envoie dans `Authorization: Bearer …` sur les seules adresses `/api/…` ; `GET /api/health` reste anonyme. Un 401 de l'API affiche l'écran « Nexus verrouillé » (VIEWS §9), sauf si le jeton enregistré a changé depuis le départ de la requête (nouveau jeton ou jeton oublié) : la réponse tardive est alors ignorée par le verrou et signalée comme un échec ordinaire. Quand il verrouille, un 401 `auth_required` ou `invalid_token` fait aussi oublier le jeton envoyé. Le WebSocket `/api/ws` ne porte pas de jeton en Phase 1 (ADR-020 D5). Aucun cookie : l'en-tête n'est jamais joint automatiquement par le navigateur, le même contrat vaudra dans Tauri.
- **Telegram** : alertes, rapports, questions urgentes (surface mobile).
- Pas d'exposition publique ; pas d'app mobile dédiée. Seule exception envisagée : un webhook entrant WhatsApp, limité à cet endpoint (à trancher en Phase 3, ADR-018).

### 3.5 Événements

- Les agents publient leurs événements via l'**API locale** de Nexus (EVENT-PROTOCOL).
- Pour un run confié à un exécutant, l'adaptateur traduit les événements natifs (ex. Hermes `claimed`, `blocked`, `completed`, `review_requested`) en événements Nexus.
- L'UI reçoit les changements en temps réel par WebSocket.

## 4. Flux

### 4.1 Travail humain (Phase 1)

```text
Loïc crée / déplace / commente une carte → nexus.db → vues
                    (aucun appel LLM, aucun agent déclenché)
```

### 4.2 Agent qui se déclare (Phase 1)

```text
agent lancé ailleurs → POST /api/events → validation → nexus.db → read-back → vues
```

### 4.3 « Confier à » (Phase 2)

```text
Loïc clique « confier à <exécutant> » sur une carte
  → policy (gating si coûteux/sensible)
  → adaptateur.dispatch() → run créé chez l'exécutant (ex. tâche Hermes assignée à helios)
  → adaptateur.watch() → événements traduits → nexus.db
  → done + preuve relue → carte en done (ou review si preuve absente)
```

### 4.4 Lecture des sources externes (Phases 3–5)

```text
adaptateurs → normalisation → index daté (provenance + fraîcheur) → vues / recherche
```

- Fréquences : événementiel quand possible (WS Hermes), sinon 30–60 s pour l'actif, à la demande pour le reste.
- Source injoignable → `unknown` + dernière vérification, jamais d'erreur bloquante.

### 4.5 Action sortante (Phases 3–5)

```text
action (répondre à un chat, envoyer un mail, créer un événement…)
  → gating (go explicite de Loïc)
  → adaptateur.act()
  → read-back (l'effet est relu et confirmé)
  → événement publié
```

## 5. Frontières multi-nœuds

- **Règle Nexus :** chaque nœud applique ses changements locaux par son gardien (Helios, Mnēma/Cortex, Aether/Synapse, Artémis).
- Nexus tourne sur Helios ; la lecture distante passe par SSH/Tailscale read-only ; aucune mutation croisée sans demande au gardien.
- Artémis : éteint volontairement → `offline-by-design`, jamais « en panne ».

## 6. Sûreté de fonctionnement

- Source morte ou erreur de parsing → la vue affiche la dernière donnée connue **datée**, marquée périmée.
- Chaque adaptateur est indépendant : une panne n'en affecte pas d'autre.
- Le noyau (tableau, Maintenant, événements) reste utile si 100 % des LLM et des sources externes sont indisponibles.

## 7. Stack (ADR-014, ADR-017)

- **Serveur :** Python, FastAPI.
- **Base :** SQLite (`nexus.db`).
- **UI :** React + TypeScript + Vite. Aucune dépendance à une API propre au navigateur : tout passe par l'API FastAPI.
- **Temps réel :** WebSocket serveur → UI ; patterns repris du dashboard Hermes quand utiles.
- **Adresse de l'API :** relative à la page par défaut (navigateur). Dans une WebView, la page n'est pas servie par l'API : `VITE_NEXUS_API_URL` (origine seule `http(s)://hôte:port`, sans chemin, fixée à la compilation et validée par `vite.config.ts`, qui refuse la compilation sinon) devient la base des requêtes REST et du WebSocket. Côté serveur, il restera à autoriser l'origine de la WebView à deux endroits : `NEXUS_ALLOWED_ORIGINS` pour le WebSocket (fermé en 1008 sinon ; CORS ne s'y applique pas) et un middleware CORS pour le REST, qui n'existe pas encore (#47). Ce CORS n'aura qu'à autoriser l'en-tête `Authorization` (et `Content-Type`, `X-Nexus-Actor`) sur l'origine de la WebView, **sans `allow_credentials`** : le jeton voyage dans un en-tête que le navigateur ne joint jamais de lui-même (pas de cookie, pas de CSRF). Le contrôle de `Host` (SECURITY §3) vaut pour toute origine : le nom d'hôte que la WebView appelle doit être loopback ou figurer dans `NEXUS_ALLOWED_HOSTS`.
- **Application Windows (cible long terme) :** Tauri 2 — la même UI dans WebView2, le serveur FastAPI lancé en sidecar ; icône de barre des tâches, notifications Windows, démarrage automatique. Repli possible : Electron.

```text
Aujourd'hui :  navigateur ──HTTP/WS──> FastAPI (localhost) ──> nexus.db
Demain      :  Tauri (WebView2 + même UI) ──HTTP/WS──> FastAPI (sidecar) ──> nexus.db
```

## 8. Contraintes techniques connues (vérifiées 2026-09-27/28)

- Hermes v0.21.4 sur Helios (version exécutée à reconfirmer — voir la note de relevé) ; dispatcher 60 s ; décomposition automatique active ; `review_dispatch` actif : **toute tâche posée dans Hermes finit exécutée par un agent** — d'où ADR-011.
- Statuts Hermes : `triage`, `todo`, `scheduled`, `ready`, `running`, `blocked`, `review`, `done`, `archived` — lus au niveau du run par l'adaptateur `hermes`, jamais comme statuts de tâche Nexus.
