// Garde-fou de taille des fichiers (issue #39, AGENTS.md « Taille des fichiers »).
//
// Un fichier de code dépasse le seuil (400 lignes physiques, 600 pour un test) seulement s'il
// figure dans `file-size-baseline.json`, et sa taille ne peut que baisser : le fichier de
// référence est un cliquet. `--update` l'abaisse (jamais ne le relève) et retire les fichiers
// revenus sous le seuil. `exceptions` note la raison d'un fichier qui reste volontairement entier.
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const CODE_LIMIT = 400;
export const TEST_LIMIT = 600;

const CODE = /\.(py|ts|tsx|js|mjs|cjs)$/;
const TEST = /(^|\/)(tests?|e2e)\/|\.(test|spec)\./;
const SKIPPED = /^docs\/|\.d\.ts$/;

export function limitFor(path) {
  if (SKIPPED.test(path) || !CODE.test(path)) return null;
  return TEST.test(path) ? TEST_LIMIT : CODE_LIMIT;
}

export function countLines(text) {
  if (text === "") return 0;
  const newlines = text.split("\n").length - 1;
  return text.endsWith("\n") ? newlines : newlines + 1;
}

// `files`: { path: lignes }. `baseline`: { files: { path: lignes max }, exceptions: { path: raison } }.
// Retourne la liste des violations (vide quand tout est bon).
export function check(files, baseline) {
  const problems = [];
  const known = baseline.files ?? {};
  for (const [path, lines] of Object.entries(files)) {
    const limit = limitFor(path);
    if (limit === null) continue;
    const ceiling = known[path];
    if (ceiling === undefined) {
      if (lines > limit) {
        problems.push(
          `${path} : ${lines} lignes, au-dessus du seuil de ${limit} (découper par sujet, ou noter la raison dans l'issue #39).`,
        );
      }
    } else if (lines > ceiling) {
      problems.push(`${path} : ${lines} lignes, la référence est ${ceiling} et ne se relève pas.`);
    } else if (lines < ceiling) {
      problems.push(
        `${path} : ${lines} lignes, la référence dit ${ceiling}. Abaisse-la : pnpm check:size --update.`,
      );
    }
  }
  for (const path of Object.keys(known)) {
    if (!(path in files)) {
      problems.push(`${path} : absent du dépôt mais encore dans la référence. pnpm check:size --update.`);
    }
  }
  return problems;
}

// Nouvelle référence : abaisse les plafonds, retire ce qui est revenu sous le seuil ou a disparu.
// Un fichier absent de la référence n'y entre jamais (le cliquet ne se relâche pas).
export function lowered(files, baseline) {
  const next = {};
  for (const [path, ceiling] of Object.entries(baseline.files ?? {})) {
    const lines = files[path];
    const limit = limitFor(path);
    if (lines === undefined || limit === null || lines <= limit) continue;
    next[path] = Math.min(ceiling, lines);
  }
  const exceptions = Object.fromEntries(Object.entries(baseline.exceptions ?? {}).filter(([path]) => path in next));
  return {
    ...baseline,
    files: Object.fromEntries(Object.entries(next).sort(([a], [b]) => (a < b ? -1 : 1))),
    exceptions,
  };
}

function measure(root) {
  const listed = execFileSync("git", ["ls-files", "-z"], { cwd: root, maxBuffer: 1 << 26 })
    .toString("utf8")
    .split("\0")
    .filter(Boolean);
  const files = {};
  for (const path of listed) {
    if (limitFor(path) === null) continue;
    try {
      files[path] = countLines(readFileSync(join(root, path), "utf8"));
    } catch {
      // Supprimé de l'arbre de travail mais encore suivi : le prochain commit le retire.
    }
  }
  return files;
}

function main() {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const baselinePath = join(root, "file-size-baseline.json");
  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  const files = measure(root);
  if (process.argv.includes("--update")) {
    writeFileSync(baselinePath, `${JSON.stringify(lowered(files, baseline), null, 2)}\n`);
    return 0;
  }
  const problems = check(files, baseline);
  if (problems.length === 0) return 0;
  console.error("Taille des fichiers (AGENTS.md « Taille des fichiers », issue #39) :");
  for (const problem of problems) console.error(`  - ${problem}`);
  return 1;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  process.exitCode = main();
}
