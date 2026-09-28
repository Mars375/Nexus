# Pre-PR review checklist

Run this checklist **before opening a pull request**. The Codex review bot should confirm the work, not discover these issues: every item below comes from a real finding on PRs #9–#14 (September 2026), where each missed case cost a review round.

How to use it:

1. While planning, list which sections apply to the change and write the edge cases down (in the plan or the PR body).
2. Write the tests for those cases first (TDD), then the code.
3. Before opening the PR, walk through every applicable box and note in the PR body what was checked and what does not apply.

## 1. Secrets (ADR-006 — nothing secret is ever stored, logged or echoed)

- [ ] Every value that reaches storage goes through `nexus.secrets` first: text fields, lists, **dict keys** and **values under credential-named keys** (`{"password": …}`, lists and objects included), identifiers (`id`, `run`), references.
- [ ] Nothing received is echoed back in a response: validation errors (422), not-found messages (404), refusals (409), headers (`X-Nexus-Actor`). Use generic messages or known-safe values only.
- [ ] Validation that happens *before* redaction (Pydantic) never returns the raw input (`RequestValidationError` handler strips `input`).
- [ ] An identifier that contains a secret is refused, not masked (masking breaks uniqueness).
- [ ] A value reduced to `[REDACTED]` (plus its label, e.g. `password=[REDACTED]`) counts as **empty** wherever a readable value is required (`secrets.is_blank`).
- [ ] New secret *formats* the scanner misses go to issue #15, not into the PR.

## 2. Validation

- [ ] Input models forbid unknown fields (`extra="forbid"`): a misspelled field is a 422, never silently ignored.
- [ ] Required text is stripped before length checks (`"   "` is empty).
- [ ] Numbers: `bool` is rejected where a number is expected (`True` is an `int` in Python); `NaN`/`Infinity` are rejected before storage.
- [ ] Types inside free-form JSON (`payload`) are checked before they reach a typed column (e.g. `run_ref` must be a string).
- [ ] References are parsed strictly (ASCII digits, bounded length): `²` or 5 000 digits give a 404, not a 500.
- [ ] Two fields that describe the same thing (`run` vs `payload.run_ref`) must agree, or the request is refused.
- [ ] Error messages are in French, name the field, and never include the received value.

## 3. Concurrency and idempotency

- [ ] Every read-then-write rule is safe under two simultaneous requests: a database constraint (unique/partial index) or the optimistic lock (`Task.version`), plus a test that simulates the race (see `test_*_race*` / `test_concurrent_*`).
- [ ] After a write conflict, re-read and re-check the rule instead of refusing blindly (another actor may legitimately succeed at the same time).
- [ ] Idempotent endpoints: an identical resend returns the original (200), even when it races the first request — on **every** conflict path (unique constraint, version conflict, anti-noise check).
- [ ] Idempotency fingerprints use canonical JSON (`sort_keys`) and include every field that makes two requests different (timestamps, run references).
- [ ] Late or out-of-order messages (e.g. `done(r1)` after `working(r2)`) are recorded but do not mutate current state.

## 4. State invariants

- [ ] Each rule is enforced on **every** path that can break it: creation, update (PATCH), status transition, linking, reopening, and effects triggered by events — not only on the main transition.
- [ ] Fields that only make sense in some states are refused elsewhere (e.g. `operation_role` outside backlog/todo/in_progress).
- [ ] Dependencies: gate progress, refuse late links on advanced tasks, refuse reopening a prerequisite under an advanced dependent.
- [ ] History records what was **actually stored**, not what was requested.

## 5. Provenance and honesty (ADR-005)

- [ ] Every API response item carries `source` and `measured_at`; comments, history and sub-resources included.
- [ ] `source` (where the data was read) is never confused with an origin field (`origin`: `api` or adapter name).
- [ ] Unknown or unreadable external data becomes `unknown` with a reason — never a guessed state (e.g. a non-boolean `Online` field).
- [ ] Anything slow or external has a timeout and a startup fallback that does not block the API (serve an `unknown` snapshot first).

## 6. UI with data that changes

- [ ] The form enforces the same rules as the server before enabling Save (title, objective, next action, block follow-up, evidence on done tasks, dependencies); the reason is shown next to the button.
- [ ] Polling or refresh never discards an unsaved draft; only fields the user edited are sent; external changes are signalled.
- [ ] A failed background refresh keeps the last known data visible, marked as stale.
- [ ] After a mutation, every affected query (detail, comments, history) is refreshed.
- [ ] Keyboard: every action reachable without a mouse (Enter opens, Space drags); inputs mirror server limits (`maxLength`).
- [ ] End-to-end tests cover the scenario where an agent changes the data while the user is looking at it.

## 7. Before opening the PR

- [ ] `pnpm test`, `pnpm lint`, `pnpm --dir web build`, and the Playwright suite pass locally.
- [ ] Migrations tested on an existing database, not only a fresh one.
- [ ] Stacked PRs are retargeted to `master` **before** their base branch is merged and deleted (otherwise GitHub closes them).
- [ ] No stray artefacts committed (screenshots, test data): check `git status` before `git add -A`.
