import assert from "node:assert/strict";
import { test } from "node:test";
import { check, countLines, limitFor, lowered } from "./check-file-size.mjs";

test("physical lines, with or without a final newline", () => {
  assert.equal(countLines(""), 0);
  assert.equal(countLines("a\nb\n"), 2);
  assert.equal(countLines("a\nb"), 2);
  assert.equal(countLines("\n\n"), 2);
});

test("limits by kind of file", () => {
  assert.equal(limitFor("server/src/nexus/secrets.py"), 400);
  assert.equal(limitFor("server/tests/test_secrets.py"), 600);
  assert.equal(limitFor("web/src/live.test.ts"), 600);
  assert.equal(limitFor("web/e2e/now.spec.ts"), 600);
  assert.equal(limitFor("docs/superpowers/plans/x.md"), null);
  assert.equal(limitFor("web/pnpm-lock.yaml"), null);
  assert.equal(limitFor("web/src/vite-env.d.ts"), null);
});

test("a new file over the limit is refused, at the limit it is fine", () => {
  assert.equal(check({ "a.py": 400 }, { files: {} }).length, 0);
  assert.equal(check({ "a.py": 401 }, { files: {} }).length, 1);
  assert.equal(check({ "tests/t.py": 600 }, { files: {} }).length, 0);
  assert.equal(check({ "tests/t.py": 601 }, { files: {} }).length, 1);
});

test("a listed file may not grow, and must lower its reference when it shrinks", () => {
  const baseline = { files: { "a.py": 500 } };
  assert.equal(check({ "a.py": 500 }, baseline).length, 0);
  assert.match(check({ "a.py": 501 }, baseline)[0], /ne se relève pas/);
  assert.match(check({ "a.py": 450 }, baseline)[0], /Abaisse/);
});

test("a listed file that disappeared is reported", () => {
  assert.match(check({}, { files: { "a.py": 500 } })[0], /absent du dépôt/);
});

test("update lowers, drops what is back under the limit and never admits a newcomer", () => {
  const baseline = { files: { "a.py": 500, "b.py": 450, "c.py": 450 }, exceptions: { "b.py": "raison" } };
  const next = lowered({ "a.py": 430, "b.py": 300, "d.py": 900 }, baseline);
  assert.deepEqual(next.files, { "a.py": 430 });
  assert.deepEqual(next.exceptions, {});
  const kept = lowered({ "b.py": 460 }, { files: { "b.py": 470 }, exceptions: { "b.py": "raison" } });
  assert.deepEqual(kept.exceptions, { "b.py": "raison" });
});

test("the reference may not be raised against the base commit", () => {
  const base = { files: { "a.py": 500 } };
  const same = { "a.py": 500 };
  assert.equal(check(same, { files: { "a.py": 500 } }, base).length, 0);
  assert.equal(check({ "a.py": 450 }, { files: { "a.py": 450 } }, base).length, 0);
  assert.match(check({ "a.py": 520 }, { files: { "a.py": 520 } }, base)[0], /relevé de 500 à 520/);
  const added = check({ "b.py": 450 }, { files: { "b.py": 450 } }, base);
  assert.match(added[0], /ajouté à la référence/);
});

test("without a reference in the base commit nothing is compared", () => {
  assert.equal(check({ "a.py": 500 }, { files: { "a.py": 500 } }, null).length, 0);
});
