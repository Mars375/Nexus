# Pre-PR review checklist

Run this checklist **before opening a pull request**. The Codex review bot should confirm the work, not discover these issues: every item below comes from a real finding on PRs #9–#19 (September 2026), where each missed case cost a review round.

How to use it:

1. While planning, list which sections apply to the change and write the edge cases down (in the plan or the PR body).
2. Write the tests for those cases first (TDD), then the code.
3. Before opening the PR, walk through every applicable box and note in the PR body what was checked and what does not apply.
4. After every bot round: search the whole codebase for the same pattern and fix every instance, not only the flagged line; then add the lesson to this checklist so the next PR does not repeat it.

## 1. Secrets (ADR-006 — nothing secret is ever stored, logged or echoed)

- [ ] Every value that reaches storage goes through `nexus.secrets` first: text fields, lists, **dict keys** and **values under credential-named keys** (`{"password": …}`, lists and objects included; every naming style: `CLIENT_SECRET`, `client-secret`, `clientSecret`, `ClientSecret`; HTTP credential headers too: `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, whatever the scheme, masked **whole** — multi-part values such as `Digest username="…", response="…"` or `a=1; b=2` must not leak past the first comma or space), identifiers (`id`, `run`), references.
- [ ] Nothing received is echoed back in a response: validation errors (422), not-found messages (404), refusals (409), headers (`X-Nexus-Actor`). Use generic messages or known-safe values only.
- [ ] Validation that happens *before* redaction (Pydantic) never returns the raw input (`RequestValidationError` handler strips `input`) **nor a raw field name**: an unknown key can itself be a secret, so every part of `loc` goes through the scanner before it reaches `loc` or `msg`.
- [ ] Any field used to compare or look things up (event `id`, `run`, `payload.run_ref`, future references) that contains a secret is refused, not masked: two masked values (`run token=alpha`, `run token=beta`) would compare equal.
- [ ] A value reduced to `[REDACTED]` (plus its label, e.g. `password=[REDACTED]`) counts as **empty** wherever a readable value is required (`secrets.is_blank`). A **reference** (evidence) must still carry an identifier once redacted spans and its label are removed (`secrets.is_blank_reference`): `commit: token=[REDACTED]` proves nothing.
- [ ] Teaching the scanner a new secret *format* (a token shape it does not recognise yet) is tracked in issue #15 and does not block a PR — Loïc's decision. This never excuses a new data path: anything the PR stores, logs or echoes still goes through `nexus.secrets`.

## 2. Validation

- [ ] Input models forbid unknown fields (`extra="forbid"`): a misspelled field is a 422, never silently ignored.
- [ ] Required text is stripped before length checks (`"   "` is empty).
- [ ] Numbers: `bool` is rejected where a number is expected (`True` is an `int` in Python); `NaN`/`Infinity` are rejected before storage.
- [ ] Every request body inherits `InputModel` (`nexus.validation`): unknown fields and lone UTF-16 surrogates (`"\ud800"`, keys included) are refused with a 422 — decoded fine, they cannot be encoded back and would break every later read.
- [ ] Types inside free-form JSON (`payload`) are checked before they reach a typed column (e.g. `run_ref` must be a string).
- [ ] References are parsed strictly (ASCII digits, bounded length): `²` or 5 000 digits give a 404, not a 500.
- [ ] Two fields that describe the same thing (`run` vs `payload.run_ref`) must agree, or the request is refused.
- [ ] Error messages are in French, name the field, and never include the received value.

## 3. Concurrency and idempotency

- [ ] Every read-then-write rule is safe under two simultaneous requests: a database constraint (unique/partial index) or the optimistic lock (`Task.version`), plus a test that simulates the race (see `test_*_race*` / `test_concurrent_*`).
- [ ] When a lock only serializes a rule check (e.g. opening a run), a write conflict means re-read and re-check the rule instead of refusing blindly — another actor may legitimately succeed at the same time. Never replay an edit against the new state: a losing `PATCH` stays a 409 so the client reconciles, otherwise it silently overwrites the winning edit.
- [ ] Endpoints keyed by a client identifier or fingerprint (e.g. events and their `id`): an identical resend returns the original (200), even when it races the first request — on **every** conflict path (unique constraint, version conflict, anti-noise check). Other idempotent operations keep their own documented contract (a repeated dependency `PUT` is a 204, a repeated `DELETE` a 404).
- [ ] Idempotency fingerprints use canonical JSON (`sort_keys`) and include every field that makes two requests different (timestamps, run references).
- [ ] Late or out-of-order messages (e.g. `done(r1)` after `working(r2)`, or a closer naming no run while one is active) are recorded but do not mutate current state.
- [ ] A rule that depends on an optional identifier handles its absence explicitly (what does a `done` without `run` mean while a run is open?), and related rules share one definition (e.g. a single `_active_run` for opening runs and applying effects).
- [ ] A lock taken only to serialize leaves no user-visible trace: a refused or no-op effect must not bump `updated_at` (lists are sorted by it).
- [ ] Closing is permanent: once a run reference is closed, a late or replayed opener (`working(r1)` after `done(r1)`) **or a second closer** (`done(r1)` after `handoff(r1)`) is recorded without effect and never becomes the active run again.
- [ ] Race handlers rely on SQLite's legacy transaction mode (implicit `BEGIN` only before the first write, so a lookup holds no snapshot): if that ever changes (explicit `BEGIN`, `autocommit=False`), conflict paths must also catch `OperationalError` (`SQLITE_BUSY_SNAPSHOT`), not only `IntegrityError`.

## 4. State invariants

- [ ] Each rule is enforced on **every** path that can break it: creation, update (PATCH), status transition, linking, reopening, and effects triggered by events — not only on the main transition.
- [ ] Fields that only make sense in some states are refused elsewhere (e.g. `operation_role` outside backlog/todo/in_progress).
- [ ] Dependencies: gate progress, refuse late links on advanced tasks, refuse reopening a prerequisite under an advanced dependent.
- [ ] History records what was **actually stored**, not what was requested.

## 5. Provenance and honesty (ADR-005)

- [ ] Every API response item carries `source` and `measured_at`; comments, history and sub-resources included.
- [ ] Three notions are never mixed: a response's `source` + `measured_at` say where and when the item was read (`nexus.db`); `Task.origin` says where the task came from (message, mail, decision); `Event.origin` names the channel that published the event (`api` or an adapter such as `hermes`) — `DATA-MODEL.md` calls it `Event.source` until #13 renames it.
- [ ] Unknown or unreadable external data becomes `unknown` with a reason — never a guessed state (e.g. a non-boolean `Online` field).
- [ ] Anything slow or external has a timeout and a startup fallback that does not block the API (serve an `unknown` snapshot first).

## 6. UI with data that changes

- [ ] The form enforces the same rules as the server before enabling Save (title, objective, next action, block follow-up, evidence on done tasks, dependencies); the reason is shown next to the button.
- [ ] Polling or refresh never discards an unsaved draft; only fields the user edited are sent; external changes are signalled.
- [ ] Every query renders its loading, error and stale states — detail sections and sub-resources (comments, history) too, not only the main list. A blank section is never an acceptable failure state.
- [ ] A failed background refresh keeps the last known data visible, marked as stale.
- [ ] Every request has a timeout and forwards the query's abort signal: a server that accepts the connection but never answers must end in an error state, not an endless spinner.
- [ ] Every state that matters on the board is visible on the card itself (e.g. both `main` and `auxiliary` operations), not only in the detail pane.
- [ ] Pickers and menus only offer choices the server would accept (e.g. dependency candidates: no cycles, only resolved prerequisites for an advanced task); a choice that becomes invalid while held is kept visible, marked invalid with the reason, and blocks submission until the user changes it — never silently dropped (it is part of the draft).
- [ ] User-facing French is proofread: imperative (`change-le`, not `changes-le`), articles (`Chargement…`, not `Chargement les commentaires…`).
- [ ] After a mutation, every affected query (detail, comments, history) is refreshed.
- [ ] Keyboard: every action reachable without a mouse (Enter opens, Space drags); inputs mirror server limits (`maxLength`).
- [ ] End-to-end tests cover the scenario where an agent changes the data while the user is looking at it.

## 7. Dates and times

- [ ] Compare instants, never text or floats. Server: normalise aware datetimes to UTC and compare them (`.timestamp()` loses microseconds far from 1970; comparing across time zones trips over PEP 495 `fold`). Web: compare `Date.parse(...)` values, never ISO strings (two dates in the repeated autumn hour carry different offsets).
- [ ] Tests include the Europe/Paris fall-back hour (`2026-10-25T02:15:00+01:00` is after `02:30:00+02:00`) and a far-future date with microseconds.

## 8. Tooling and repository hygiene

- [ ] Hooks check exactly what will be committed: unstaged changes **and untracked files** are set aside first, and tool configuration is the indexed one (gitleaks always reads the scanned directory's `.gitleaksignore`). Prove each hook rule with a scenario that fails first, then passes.
- [ ] Secret-scanner exceptions are exact fingerprints (commit, file, rule, line), never a whole path; fake secrets in tests are assembled at runtime (`"ghp_" + "A" * 36`).
- [ ] Adding an ignore rule also untracks files it already matches (`git ls-files -ci --exclude-standard` must print nothing).
- [ ] Scripts edited with `sed`/`perl` are re-read (`cat -A`): an escaping mistake silently turned a hook check into a no-op.
- [ ] Docs and README only name commands that exist on that branch; a dependency on another PR is stated and resolved by merge order, then a rebase.
- [ ] Instructions in docs are reviewed like a spec: they must not read as permission for the wrong behaviour (e.g. "re-check after a conflict" must not mean "replay the losing edit").

## 9. Before opening the PR

- [ ] `pnpm test`, `pnpm lint`, `pnpm --dir web build`, and the Playwright suite pass locally.
- [ ] Migrations tested on an existing database, not only a fresh one.
- [ ] Stacked PRs are retargeted to `master` **before** their base branch is merged and deleted (otherwise GitHub closes them).
- [ ] No stray artefacts committed (screenshots, test data): check `git status` before `git add -A`.
