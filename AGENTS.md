# AGENTS.md

## Development

- `server/`: Python (FastAPI, SQLAlchemy, Alembic), managed with `uv`. `web/`: React + TypeScript + Vite, managed with `pnpm`.
- From the repo root: `pnpm install` then `pnpm bootstrap` once; `pnpm dev` to run; run `pnpm test` and `pnpm lint` before committing.
- Schema changes go through a new Alembic migration in `server/src/nexus/migrations/versions/`; the server applies migrations on startup.
- The UI only talks to the FastAPI API — no browser-only APIs, so the same UI can ship inside Tauri later (ADR-017).
- Product docs and user-facing text are in French (ADR-009); identifiers stay in English.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues, managed with the `gh` CLI. They track the development of Nexus itself; operational tasks will live in Nexus once it runs (ADR-012) — never mirror one into the other. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. The decision log is still `DECISIONS.md` and the glossary is `docs/GLOSSARY.md`. See `docs/agents/domain.md`.
