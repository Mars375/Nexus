# AGENTS.md

## Development

- `server/`: Python (FastAPI, SQLAlchemy, Alembic), managed with `uv`. `web/`: React + TypeScript + Vite, managed with `pnpm`.
- From the repo root: `pnpm install` then `pnpm bootstrap` once; `pnpm dev` to run; run `pnpm test` and `pnpm lint` before committing.
- A pre-commit hook (`.husky/pre-commit`) blocks test artefacts and local databases, runs gitleaks on staged changes (config: `.gitleaks.toml`), lints staged files, then typechecks and runs the fast tests. Never bypass it with `--no-verify`; fix the cause instead. Build fake secrets in tests at runtime (`"ghp_" + "A" * 36`).
- Schema changes go through a new Alembic migration in `server/src/nexus/migrations/versions/`; the server applies migrations on startup.
- The UI only talks to the FastAPI API — no browser-only APIs, so the same UI can ship inside Tauri later (ADR-017).
- Product docs and user-facing text are in French (ADR-009); identifiers stay in English.
- Before opening a PR, walk through `docs/agents/review-checklist.md` (secrets, validation, concurrency, invariants, provenance, UI with changing data) and note in the PR body what was checked. Plan edge cases first and write their tests before the code.

## Model routing

- Le modèle principal est `claude-opus-5-5` (`.claude/settings.json`) ; l'alias `opusplan` n'est pas pris en charge dans nos sessions. Les subagents de `.claude/agents/` portent le modèle adapté à leur rôle (`explorer` Haiku, `implementer` Sonnet, `architect` et `reviewer` Opus). Ne pas forcer un modèle unique avec `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`.
- Toute tâche qui touche une migration, l'authentification, les secrets, la concurrence ou un invariant passe par `architect` avant `implementer`.
- Après deux échecs de test sur la même tâche, relancer avec `model: opus` au lieu de réessayer à l'identique.
- Toute PR passe d'abord par `reviewer`, puis par la relecture Antigravity (lancée par Loïc depuis sa machine : le skill et la CLI ne sont pas disponibles en session cloud), CodeRabbit (automatique sur la PR), et `@codex review` en dernier.
- Les recherches larges en lecture seule vont à `explorer`, pas au modèle principal : recherche d'un motif dans le code, vérification d'une remarque de relecture contre la doc officielle ou le code (étapes 4 et 5 de `docs/agents/review-checklist.md`).

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues, managed with the `gh` CLI. They track the development of Nexus itself; operational tasks will live in Nexus once it runs (ADR-012) — never mirror one into the other. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. The decision log is still `DECISIONS.md` and the glossary is `docs/GLOSSARY.md`. See `docs/agents/domain.md`.
