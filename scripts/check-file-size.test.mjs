import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
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

// Intégration : le script tourne dans un dépôt git temporaire, avec sa vraie ligne de commande.
const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "check-file-size.mjs");

function sandbox(baseline, files) {
  const dir = mkdtempSync(join(tmpdir(), "size-"));
  mkdirSync(join(dir, "scripts"));
  copyFileSync(SCRIPT, join(dir, "scripts", "check-file-size.mjs"));
  // Les variables GIT_* qu'un hook exporte (GIT_INDEX_FILE absolu pour `git commit -a`) ne doivent
  // pas atteindre le dépôt temporaire, ni git ni le script.
  const clean = Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.startsWith("GIT_")));
  // Ni la configuration globale ni celle du système du développeur (commit.gpgsign, hooks globaux).
  mkdirSync(join(dir, ".gitcfg"));
  writeFileSync(join(dir, ".gitcfg", "empty"), "");
  clean.GIT_CONFIG_GLOBAL = join(dir, ".gitcfg", "empty");
  clean.GIT_CONFIG_NOSYSTEM = "1";
  const env = { ...clean, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@t", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@t" };
  const git = (...args) => execFileSync("git", args, { cwd: dir, env, stdio: "ignore" });
  const write = (state) => {
    for (const [path, lines] of Object.entries(state.files ?? {})) {
      mkdirSync(dirname(join(dir, path)), { recursive: true });
      writeFileSync(join(dir, path), `x = 1${String.fromCharCode(13, 10)}`.repeat(lines));
    }
    if (state.baseline) writeFileSync(join(dir, "file-size-baseline.json"), JSON.stringify(state.baseline));
  };
  git("init", "-q");
  write({ baseline, files });
  git("add", "-A");
  git("commit", "-q", "-m", "base");
  const run = (...args) => spawnSync("node", ["scripts/check-file-size.mjs", ...args], { cwd: dir, env: clean, encoding: "utf8" });
  return { dir, git, write, run, done: () => rmSync(dir, { recursive: true, force: true }) };
}

test("cli: growth with a raised ceiling fails, an unknown or missing base fails loudly", () => {
  const box = sandbox({ files: { "big dir/é.py": 450 } }, { "big dir/é.py": 450 });
  try {
    assert.equal(box.run().status, 0);
    box.write({ files: { "big dir/é.py": 480 }, baseline: { files: { "big dir/é.py": 480 } } });
    const raised = box.run();
    assert.equal(raised.status, 1);
    assert.match(raised.stderr, /relevé de 450 à 480/);
    const unknown = box.run("--base", "no-such-ref");
    assert.equal(unknown.status, 1);
    assert.match(unknown.stderr, /introuvable/);
    const missing = box.run("--base");
    assert.equal(missing.status, 1);
    assert.match(missing.stderr, /demande un commit/);
  } finally {
    box.done();
  }
});

test("cli: a base commit without a reference is the first version, nothing to compare", () => {
  const box = sandbox(null, { "a.py": 10 });
  try {
    box.write({ baseline: { files: {} } });
    assert.equal(box.run().status, 0);
  } finally {
    box.done();
  }
});

test("cli: a missing reference file is a clear error, not a stack trace", () => {
  const box = sandbox({ files: {} }, { "a.py": 10 });
  try {
    rmSync(join(box.dir, "file-size-baseline.json"));
    const result = box.run();
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Référence illisible/);
    assert.doesNotMatch(result.stderr, /at readFileSync/);
  } finally {
    box.done();
  }
});

test("cli: --update lowers the reference and never raises it", () => {
  const box = sandbox({ files: { "a.py": 450 } }, { "a.py": 450 });
  try {
    box.write({ files: { "a.py": 420 } });
    assert.equal(box.run().status, 1);
    assert.equal(box.run("--update").status, 0);
    assert.equal(box.run().status, 0);
  } finally {
    box.done();
  }
});

test("cli: --base=<ref> is read, an unknown option is refused, a broken base reference is named", () => {
  const box = sandbox({ files: { "a.py": 450 } }, { "a.py": 450 });
  try {
    const glued = box.run("--base=no-such-ref");
    assert.equal(glued.status, 1);
    assert.match(glued.stderr, /introuvable/);
    const unknown = box.run("--bsae", "HEAD");
    assert.equal(unknown.status, 1);
    assert.match(unknown.stderr, /Option inconnue/);
    writeFileSync(join(box.dir, "file-size-baseline.json"), "{ broken");
    box.git("commit", "-q", "-a", "-m", "break");
    writeFileSync(join(box.dir, "file-size-baseline.json"), JSON.stringify({ files: { "a.py": 450 } }));
    const broken = box.run();
    assert.equal(broken.status, 1);
    assert.match(broken.stderr, /Référence illisible dans le commit de base HEAD/);
  } finally {
    box.done();
  }
});

test("cli: a foreign GIT_INDEX_FILE (hook of `git commit -a`) does not break the sandbox", () => {
  const before = process.env.GIT_INDEX_FILE;
  process.env.GIT_INDEX_FILE = join(tmpdir(), "foreign-index.lock");
  try {
    const box = sandbox({ files: { "a.py": 450 } }, { "a.py": 450 });
    try {
      assert.equal(box.run().status, 0);
    } finally {
      box.done();
    }
  } finally {
    if (before === undefined) delete process.env.GIT_INDEX_FILE;
    else process.env.GIT_INDEX_FILE = before;
  }
});

test("cli: --update refuses to drop a tracked file that is only missing from the work tree", () => {
  const box = sandbox({ files: { "a.py": 450 } }, { "a.py": 450 });
  try {
    rmSync(join(box.dir, "a.py"));
    const result = box.run("--update");
    assert.equal(result.status, 1);
    assert.match(result.stderr, /absent de l'arbre de travail mais suivi/);
    box.git("rm", "-q", "--cached", "a.py");
    assert.equal(box.run("--update").status, 0);
  } finally {
    box.done();
  }
});

test("cli: a signing git configuration of the developer does not break the sandbox", () => {
  const home = mkdtempSync(join(tmpdir(), "home-"));
  writeFileSync(join(home, ".gitconfig"), "[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = /nonexistent\n");
  const saved = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  try {
    const box = sandbox({ files: { "a.py": 450 } }, { "a.py": 450 });
    try {
      assert.equal(box.run().status, 0);
    } finally {
      box.done();
    }
  } finally {
    for (const [name, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
    rmSync(home, { recursive: true, force: true });
  }
});

test("cli: --update exits 1 while violations remain, and --base without a value is refused with it", () => {
  const box = sandbox({ files: { "a.py": 450 } }, { "a.py": 450 });
  try {
    box.write({ files: { "a.py": 480, "new.py": 500 } });
    box.git("add", "-A");
    const grown = box.run("--update");
    assert.equal(grown.status, 1);
    assert.match(grown.stderr, /new\.py : 500 lignes/);
    const unvalued = box.run("--base", "--update");
    assert.equal(unvalued.status, 1);
    assert.match(unvalued.stderr, /demande un commit/);
  } finally {
    box.done();
  }
});

test("cli: a repository without any commit has nothing to compare, an explicit base still must resolve", () => {
  const dir = mkdtempSync(join(tmpdir(), "empty-"));
  try {
    mkdirSync(join(dir, "scripts"));
    copyFileSync(SCRIPT, join(dir, "scripts", "check-file-size.mjs"));
    const clean = Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.startsWith("GIT_")));
    execFileSync("git", ["init", "-q"], { cwd: dir, env: clean });
    writeFileSync(join(dir, "file-size-baseline.json"), JSON.stringify({ files: {} }));
    execFileSync("git", ["add", "-A"], { cwd: dir, env: clean });
    const run = (...args) =>
      spawnSync("node", ["scripts/check-file-size.mjs", ...args], { cwd: dir, env: clean, encoding: "utf8" });
    assert.equal(run().status, 0);
    assert.equal(run("--base", "HEAD").status, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a tracked listed file missing from the work tree gets the right advice", () => {
  const message = check({}, { files: { "a.py": 500 } }, null, new Set(["a.py"]))[0];
  assert.match(message, /absent de l'arbre de travail mais suivi/);
  assert.match(message, /git checkout a\.py/);
});

test("a ceiling that is not a non-negative integer is refused before any comparison", () => {
  for (const bad of ["NaN", "500", null, -1, 1.5, true]) {
    const problems = check({ "a.py": 9000 }, { files: { "a.py": bad } }, { files: { "a.py": 500 } });
    assert.equal(problems.length, 1, JSON.stringify(bad));
    assert.match(problems[0], /plafond invalide/);
  }
  assert.equal(check({ "a.py": 500 }, { files: { "a.py": 500 } }, { files: { "a.py": 500 } }).length, 0);
});
