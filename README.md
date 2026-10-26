# Nexus

> Le centre de contrôle de Loïc et de ses agents — la seule application à ouvrir.

Nexus est une application locale et autonome qui réunit Loïc et tous ses agents — Helios, Mnēma, Aether, Artémis, Claude Code, Codex, Orca, Hermes — dans un seul espace : tâches, discussions, mails, agenda, code, mémoire, infrastructure, preuves. Il a son propre modèle et ses propres données ; les outils existants y sont branchés derrière des adaptateurs remplaçables. Aucun LLM n'est lancé sans action explicite.

## Le problème

- Trop d'onglets, trop de conversations parallèles, trop d'états invisibles.
- Des tâches se perdent ; des promesses d'agents s'oublient ; des blocages restent silencieux.
- Personne — ni l'humain ni les agents — ne peut répondre vite à : *qui travaille sur quoi ? qui attend qui ? qu'est-ce qui est bloqué ? qu'est-ce qui a réellement été terminé ?*

## Ce que Nexus est, n'est pas

| C'est | Ce n'est pas |
|---|---|
| Une application autonome, avec son propre modèle et ses propres tâches | Une surcouche ou une copie d'un outil existant |
| Le point d'entrée unique : tâches, chats, mails, agenda, code, mémoire, infra | Un lien de plus vers d'autres dashboards |
| Un tableau de tâches utilisable sans aucun appel LLM | Un lanceur automatique d'agents |
| Un endroit où l'on confie explicitement du travail à un agent et où l'on suit son run | Un chatbot |
| Un endroit où chaque état a une source et une fraîcheur | Un dashboard d'animations non vérifiables |

## Architecture en une image

```text
               Loïc  ·  agents (Helios, Mnēma, Aether, Artémis, Claude, Codex, Orca)
                                         ↓
┌───────────────────────────────── NEXUS ─────────────────────────────────┐
│  tâches · événements · conversations · approbations · décisions · preuves │
│  vues : Maintenant · Travail · Conversations · Inbox · Planning · Code ·  │
│         Système · À ne pas oublier                                        │
│                         nexus.db (source de vérité)                       │
└──────────────────────────────────────────────────────────────────────────┘
                                         ↓ adaptateurs remplaçables
  exécutants : Hermes (Helios/Mnēma/Aether) · Claude Code · Codex · Orca
  données    : Telegram · sessions · Gmail · Calendar · Git/GitHub · Hindsight · Synapse · nœuds · quotas
```

## Principes fondateurs

1. **Nexus est autonome.** Ses tâches, événements et décisions vivent dans `nexus.db` ; aucun outil externe n'est sa colonne vertébrale.
2. **Une carte ≠ un appel LLM.** Créer, déplacer ou commenter une tâche ne déclenche aucun agent. Confier une tâche à un agent est une action explicite.
3. **La seule app.** Ce dont Loïc a besoin s'affiche dans Nexus ; les données externes (mails, commits, chats…) restent chez leur propriétaire, Nexus les lit et agit dessus.
4. **Chaque donnée affichée porte sa provenance** (source + fraîcheur).
5. **`unknown` reste `unknown`** jusqu'à vérification — jamais de valeur inventée.
6. **Une seule opération principale active** à la fois.
7. **Aucun secret stocké** — toute valeur sensible est remplacée par `[REDACTED]`.
8. **Rien d'irréversible sans go de Loïc** : envoi, publication, suppression, dépense.
9. **Local, observable, inspectable** — pas de dépendance à un fournisseur unique.
10. **Artémis fait partie du modèle**, même éteint volontairement.

## Documents

- [docs/PRD.md](docs/PRD.md) — le produit : besoin, périmètre, exigences
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — comment c'est construit
- [docs/DATA-MODEL.md](docs/DATA-MODEL.md) — Task / Run / Event / Conversation / Artifact…
- [docs/EVENT-PROTOCOL.md](docs/EVENT-PROTOCOL.md) — ce que les agents publient
- [docs/VIEWS.md](docs/VIEWS.md) — Maintenant, Travail, Conversations, Inbox, Planning, Code, Système, À ne pas oublier
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — exécutants et sources de données
- [docs/ROADMAP.md](docs/ROADMAP.md) — phases et critères de sortie
- [docs/SECURITY.md](docs/SECURITY.md) — secrets, permissions, gating
- [docs/INSPIRATIONS.md](docs/INSPIRATIONS.md) — ce qu'on prend (et évite) ailleurs
- [docs/GLOSSARY.md](docs/GLOSSARY.md) — vocabulaire
- [DECISIONS.md](DECISIONS.md) — journal des décisions
- [AGENTS.md](AGENTS.md) — configuration des agents qui contribuent (issue tracker, labels de triage, docs de domaine)

## Statut

- **2026-09-28** — Phase 0 : fondations documentaires. Refonte du même jour : Nexus devient une application autonome (ADR-011), et non plus une surcouche de Hermes Kanban.
- **2026-09-28** — Phase 0 close (refonte relue et validée par Loïc). Phase 1 en cours : noyau (tableau Nexus, vue Maintenant, API d'événements).
- **2026-10-26** — Phase 1 en usage quotidien : tableau **Travail** (créer, déplacer, commenter, assigner, lier, preuves jointes, tâche « suite »), vue **Maintenant**, API d'événements et temps réel WebSocket, authentification par jeton d'acteur (ADR-020), sauvegardes quotidiennes et nœuds Tailscale en lecture seule. Les tests couvrent le serveur (pytest) et l'UI (Vitest, Playwright) ; une CI GitHub Actions (lint, typage, build, tests, e2e) vérifie chaque PR.

## Lancer Nexus

Prérequis : [uv](https://docs.astral.sh/uv/), Node.js et pnpm.

```sh
pnpm install     # outil de lancement (racine)
pnpm bootstrap   # dépendances serveur (uv) + UI (pnpm)
pnpm dev         # serveur http://127.0.0.1:8765 + UI http://localhost:5173
pnpm test        # tests serveur (pytest) + UI (Vitest)
pnpm lint        # ruff + oxlint
```

Chaque commit passe par un hook (Husky) : refus des artefacts de tests et des bases locales, scan de secrets **gitleaks** (à installer : `winget install Gitleaks.Gitleaks`), lint des fichiers modifiés, typage et tests rapides. La suite Playwright (`pnpm e2e`) se lance avant d'ouvrir une PR.

- **Premier démarrage : jeton d'accès.** Nexus exige un jeton sur toute route REST de l'API sauf `GET /api/health` (ADR-020 ; la documentation OpenAPI n'en porte pas, et le WebSocket exige un ticket obtenu avec ce jeton). Une fois `pnpm dev` lancé une première fois (il crée et migre la base), émets le jeton de Loïc pour le navigateur : `uv run --directory server nexus-token issue loic --label navigateur`. Lance `nexus-token` avec le même `NEXUS_DATA_DIR` que le serveur : sinon la CLI vise une autre base : elle refuse une base absente ou pas à jour (« démarre Nexus une fois »), ou écrit le jeton ailleurs et le serveur répond 401 `invalid_token`. Le jeton s'affiche **une seule fois** : colle-le dans l'écran « Nexus verrouillé » de l'interface (il reste dans le navigateur). Un agent a son propre jeton (`nexus-token issue helios --label cli`, puis variable `NEXUS_TOKEN` ou `--token-file`) ; `nexus-token list` et `nexus-token revoke nx-tok-<n>` les gèrent. Le serveur écoute la boucle locale ; pour le tailnet, `NEXUS_HOST=127.0.0.1,<adresse tailnet>` (une adresse `100.x` ou `fd7a:115c:a1e0::…` de ce nœud, confirmée par Tailscale avant chaque ouverture, ADR-021) ; pose aussi la règle de pare-feu de SECURITY §3. Il ne répond qu'aux en-têtes `Host` locaux et à ses propres adresses (autres noms : `NEXUS_ALLOWED_HOSTS`, liste séparée par des virgules).
- **Origine de la WebView (Tauri, #47).** Déclare l'origine exacte de la page dans `NEXUS_ALLOWED_ORIGINS` (liste séparée par des virgules, `schéma://hôte[:port]`, sans chemin ni slash final) : `http://tauri.localhost` sous Windows, `https://tauri.localhost` si Tauri utilise HTTPS, `tauri://localhost` sous macOS/Linux. La même liste sert au CORS du REST et au WebSocket ; la boucle locale reste admise pour le WebSocket. `VITE_NEXUS_API_URL` désigne l'adresse de l'API (`http://127.0.0.1:8765`), pas l'origine de la page.
- Données : `%LOCALAPPDATA%\Nexus\nexus.db` (modifiable avec `NEXUS_DATA_DIR`). La base est créée et migrée au démarrage.
- Sauvegardes : `%LOCALAPPDATA%\Nexus\backups\`, une au démarrage puis toutes les 24 h, les 14 dernières conservées (`NEXUS_BACKUP_INTERVAL_HOURS`, `NEXUS_BACKUP_KEEP`).
- Nœuds : lus en lecture seule via `tailscale status --json`, toutes les 60 s (`NEXUS_NODES_REFRESH_SECONDS`, binaire : `NEXUS_TAILSCALE_BIN`). Sans Tailscale, les nœuds s'affichent `unknown`.

## Structure du dépôt

- `server/` — serveur Python (FastAPI, SQLAlchemy, Alembic), géré avec `uv`.
- `web/` — UI React + TypeScript + Vite.
- `docs/` — documentation de conception ; les critères de chaque phase sont vérifiables et passent par un go explicite de Loïc.
