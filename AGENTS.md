# AGENTS.md

## Development

- `server/`: Python (FastAPI, SQLAlchemy, Alembic), managed with `uv`. `web/`: React + TypeScript + Vite, managed with `pnpm`.
- From the repo root: `pnpm install` then `pnpm bootstrap` once; `pnpm dev` to run; run `pnpm test` and `pnpm lint` before committing.
- The API requires a token (ADR-020). After the first `pnpm dev` (it creates and migrates the database), issue Loïc's browser token once with `uv run --directory server nexus-token issue loic --label navigateur` and paste it into the « Nexus verrouillé » screen; an agent sends its own token as `Authorization: Bearer nxt_…` (`demo_agent` reads `NEXUS_TOKEN` or `--token-file`). `nexus-token` must see the same `NEXUS_DATA_DIR` as `pnpm dev`. Never commit or log a token.
- A pre-commit hook (`.husky/pre-commit`) blocks test artefacts and local databases, runs gitleaks on staged changes (config: `.gitleaks.toml`), lints staged files, then typechecks and runs the fast tests. Never bypass it with `--no-verify`; fix the cause instead. Build fake secrets in tests at runtime (`"ghp_" + "A" * 36`).
- Schema changes go through a new Alembic migration in `server/src/nexus/migrations/versions/`; the server applies migrations on startup.
- The UI only talks to the FastAPI API — no browser-only APIs, so the same UI can ship inside Tauri later (ADR-017).
- Product docs and user-facing text are in French (ADR-009); identifiers, code comments and docstrings stay in English: new ones and the ones a change touches; no mass translation of existing French comments.
- Before opening a PR, walk through `docs/agents/review-checklist.md` (secrets, validation, concurrency, invariants, provenance, UI with changing data) and note in the PR body what was checked. Plan edge cases first and write their tests before the code.

## Branches et PR

- Une branche par issue ou par sujet, jamais deux sujets sur une même branche. Elle part de `master` à jour, sauf une PR empilée sur une autre (à recibler sur `master` avant la fusion de sa base, voir `docs/agents/review-checklist.md` §9). Noms : `feat/<n>-<sujet>`, `fix/<n>-<sujet>`, `docs/<sujet>`, `chore/<sujet>` (le numéro d'issue quand il y en a une) ; une session cloud qui impose `claude/<…>` garde ce nom.
- Jamais de push direct sur `master`, pas de push forcé sauf `--force-with-lease` sur sa propre branche.
- Une PR par branche, fusionnée en squash par l'agent. Règle de Loïc (2026-10-06) : l'agent fusionne **de lui-même** une PR qu'il a ouverte quand toutes les conditions suivantes valent pour le **même commit de tête**, puis passe au sujet suivant (une issue `ready-for-agent` ; il demande à Loïc s'il n'y en a pas ou si le choix n'est pas évident).
  - `reviewer` a relu le diff complet jusqu'à ce commit ; chaque P1 et P2 est corrigé, ou écarté avec sa raison notée dans le corps de la PR.
  - CodeRabbit a approuvé ce commit : sa dernière relecture porte sur lui et ne laisse aucune remarque (relecture approuvée, ou « No actionable comments »). Un statut « Review completed » ou « pending », une relecture qui demande des changements, ou une approbation d'un commit plus ancien ne suffisent pas.
  - Loïc a collé une relecture Antigravity qui approuve, faite sur ce commit ; l'agent note dans la PR le commit qu'elle couvre.
  - Chaque remarque a reçu une réponse, y compris celles qui n'ouvrent pas de fil (remarques « Outside diff range » et nitpicks du résumé CodeRabbit, rapport de `reviewer`, relecture Antigravity), et aucun fil n'est ouvert.
  - La branche est à jour avec `master` ; `pnpm test` et `pnpm lint` passent sur ce commit (plus `pnpm --dir web build` et Playwright quand la PR touche du code, voir la checklist §9).
- La relecture et l'approbation de Codex ne sont jamais requises pour fusionner (décision de Loïc, 2026-10-06). Toute remarque qu'il poste quand même suit la règle générale : elle reçoit une réponse et, si elle ouvre un fil, ce fil est résolu.
- Un commit poussé après une relecture la rend caduque : relancer `reviewer`, attendre la nouvelle relecture de CodeRabbit, puis redemander Antigravity à Loïc, de préférence une fois la tête stable. Un rebase change le commit de tête : il rend les relectures caduques comme n'importe quel nouveau commit. Les tests seuls ne suffisent que si le commit de tête ne change pas.
- L'agent **ne fusionne pas** et demande à Loïc dans ces cas : une PR qui touche `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.husky/`, `.gitleaks.toml`, `.gitleaksignore`, `DECISIONS.md` ou une migration de `server/src/nexus/migrations/versions/` ; une remarque qu'il choisit de ne pas corriger alors que la relecture n'approuve pas, ou des relectures qui se contredisent ; tout doute sur le périmètre ou sur une remarque ; une PR que Loïc a demandé de ne pas fusionner. Poser la question ne lève pas le blocage : seule la réponse de Loïc le lève.
- Cette règle ne vaut que pour les PR que l'agent a lui-même ouvertes dans la conversation en cours (il le sait : il a créé la PR). Une PR retrouvée plus tard, ou ouverte par Loïc, par un autre agent ou par un tiers, n'est jamais fusionnée sans l'accord de Loïc. Toutes sont publiées sous `Mars375` et le corps d'une PR, même signé `claude.ai/code`, se recopie : ni l'auteur GitHub ni le corps ne prouvent la provenance. Aucun plan de `docs/superpowers/plans/` (« merge when a round has no P1 ») ne remplace ces conditions. GitHub supprime la branche distante à la fusion ; supprimer aussi la branche locale et lancer `git fetch --prune`.
- Le corps de la PR ferme son issue avec le mot-clé anglais `Closes #<n>` (GitHub ne reconnaît pas « Ferme #<n> », et le mot-clé n'agit que pour une PR qui cible `master`). Une PR qui ne traite qu'une partie de l'issue écrit `Refs #<n>`.
- Relectures, dans l'ordre de « Model routing » ci-dessous : `reviewer`, Antigravity, CodeRabbit, `@codex review` (facultatif, jamais bloquant : voir les conditions de fusion ci-dessus). Ne pas pousser de correction pendant qu'une relecture automatique (CodeRabbit, Codex) tourne encore ; Antigravity est lancée par Loïc, qui colle son résultat dans la conversation, et c'est ce message qui marque sa fin. L'agent vérifie chaque remarque à la source avant de l'appliquer, répond sur chaque fil (correction et commit, ou raison de ne pas corriger) puis le résout.

## Model routing

- Le modèle principal est l'alias `sonnet` (`.claude/settings.json`), résolu par la version de Claude Code installée (garder Claude Code à jour : `claude update`). Le fil principal est celui qui coûte le plus en tokens : Opus n'intervient que dans des subagents (`architect`, `reviewer`, et la relance `model: opus` après deux échecs, plus bas). L'alias `opusplan` n'est pas pris en charge dans nos sessions. Les subagents de `.claude/agents/` portent le modèle adapté à leur rôle (`explorer` Haiku, `implementer` Sonnet, `architect` et `reviewer` Opus). Ne pas forcer un modèle unique avec `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`.
- Toute tâche qui touche une migration, l'authentification, les secrets, la concurrence ou un invariant passe par `architect` avant `implementer`.
- Après deux échecs de test sur la même tâche, relancer avec `model: opus` au lieu de réessayer à l'identique.
- Toute PR passe d'abord par `reviewer`, puis par la relecture Antigravity (lancée par Loïc depuis sa machine : le skill et la CLI ne sont pas disponibles en session cloud), CodeRabbit (automatique sur la PR), et `@codex review` en dernier (facultatif, jamais bloquant : voir les conditions de fusion ci-dessus).
- Les recherches larges en lecture seule vont à `explorer`, pas au modèle principal : recherche d'un motif dans le code, vérification d'une remarque de relecture contre la doc officielle ou le code (étapes 4 et 5 de `docs/agents/review-checklist.md`).

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues, managed with the `gh` CLI. They track the development of Nexus itself; operational tasks will live in Nexus once it runs (ADR-012) — never mirror one into the other. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. The decision log is still `DECISIONS.md` and the glossary is `docs/GLOSSARY.md`. See `docs/agents/domain.md`.
