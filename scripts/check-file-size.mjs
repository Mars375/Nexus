// Garde-fou de taille des fichiers (issue #39, AGENTS.md « Taille des fichiers »).
//
// Un fichier de code dépasse le seuil (400 lignes physiques, 600 pour un test) seulement s'il
// figure dans `file-size-baseline.json`, et sa taille ne peut que baisser : le fichier de
// référence est un cliquet. `--update` l'abaisse (jamais ne le relève) et retire les fichiers
// revenus sous le seuil. `exceptions` note la raison d'un fichier qui reste volontairement entier.
// La référence de l'arbre de travail est aussi comparée à celle d'un commit de base (`--base`,
// HEAD par défaut) : relever un plafond ou y ajouter un fichier est refusé, même dans un commit
// qui modifie la référence. Sans référence dans le commit de base (première version), pas de
// comparaison.
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const CODE_LIMIT = 400;
export const TEST_LIMIT = 600;

const CODE = /\.(py|ts|tsx|mts|cts|js|jsx|mjs|cjs)$/;
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
export function ceilingProblems(entries, where) {
  return Object.entries(entries)
    .filter(([, ceiling]) => !Number.isInteger(ceiling) || ceiling < 0)
    .map(
      ([path, ceiling]) =>
        `${path} : plafond invalide dans ${where} (${JSON.stringify(ceiling)}), un entier positif ou nul est attendu.`,
    );
}

// `base`: la référence du commit de base, ou null. Retourne la liste des violations.
export function check(files, baseline, base = null, tracked = new Set()) {
  const problems = [];
  const known = baseline.files ?? {};
  // Un plafond qui n'est pas un entier positif ou nul (`"NaN"`, `null`, `-1`, `"500"`) rend toutes
  // les comparaisons fausses, donc silencieuses : la référence est refusée avant d'être lue, celle
  // du commit de base comme celle de l'arbre de travail.
  const invalid = [
    ...ceilingProblems(known, "la référence"),
    ...(base ? ceilingProblems(base.files ?? {}, "la référence du commit de base") : []),
  ];
  if (invalid.length > 0) return invalid;
  if (base) {
    const before = base.files ?? {};
    for (const [path, ceiling] of Object.entries(known)) {
      if (!(path in before)) {
        problems.push(`${path} : ajouté à la référence ; un fichier trop long se découpe, il n'entre pas dans la référence.`);
      } else if (ceiling > before[path]) {
        problems.push(`${path} : plafond relevé de ${before[path]} à ${ceiling} ; la référence ne se relève pas.`);
      }
    }
  }
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
    if (path in files) continue;
    problems.push(
      tracked.has(path)
        ? `${path} : absent de l'arbre de travail mais suivi par git. Restaure-le (git checkout ${path}), ou retire-le (git rm ${path}) si la suppression est voulue, puis pnpm check:size --update.`
        : `${path} : absent du dépôt mais encore dans la référence. pnpm check:size --update.`,
    );
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
  const tracked = new Set(listed);
  const files = {};
  for (const path of listed) {
    if (limitFor(path) === null) continue;
    try {
      files[path] = countLines(readFileSync(join(root, path), "utf8"));
    } catch (error) {
      // Supprimé de l'arbre de travail mais encore suivi : le prochain commit le retire.
      // Toute autre erreur (droits, verrou) ne doit pas faire sortir le fichier du contrôle.
      if (error.code !== "ENOENT") throw error;
    }
  }
  return { files, tracked };
}

// La référence du commit de base : null seulement quand ce commit n'en a pas (première version).
// Un commit introuvable, un `--base` sans valeur ou un JSON illisible font échouer le contrôle :
// la comparaison ne doit jamais s'éteindre en silence.
function baseOf(root, { ref, explicit }) {
  const git = (...args) => execFileSync("git", args, { cwd: root, stdio: ["ignore", "pipe", "ignore"] }).toString("utf8");
  try {
    git("rev-parse", "--verify", `${ref}^{commit}`);
  } catch {
    // Dépôt sans aucun commit : le premier commit n'a rien à comparer. Une base donnée
    // explicitement qui ne se résout pas, elle, est une erreur.
    if (!explicit) return null;
    throw new Error(`Commit de base introuvable : ${ref} (clone superficiel ? la CI récupère deux commits).`);
  }
  try {
    git("cat-file", "-e", `${ref}:file-size-baseline.json`);
  } catch {
    return null;
  }
  try {
    return JSON.parse(git("show", `${ref}:file-size-baseline.json`));
  } catch (error) {
    throw new Error(`Référence illisible dans le commit de base ${ref} : ${error.message}`);
  }
}

function readBaseline(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`Référence illisible (${path}) : ${error.code ?? error.message}. Restaure file-size-baseline.json.`);
  }
}

// `--base <commit>`, `--base=<commit>` et `--update`, analysés une fois. Toute autre option est
// refusée plutôt qu'ignorée, et une base sans valeur aussi : une base mal écrite ne doit pas
// désactiver la comparaison.
function parseArgs(args) {
  const parsed = { update: false, base: { ref: "HEAD", explicit: false } };
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === "--update") {
      parsed.update = true;
    } else if (arg === "--base" || arg.startsWith("--base=")) {
      const ref = arg === "--base" ? args[(i += 1)] : arg.slice("--base=".length);
      if (!ref || ref.startsWith("--")) throw new Error("--base demande un commit (par exemple HEAD ou HEAD^1).");
      parsed.base = { ref, explicit: true };
    } else {
      throw new Error(`Option inconnue : ${arg} (options : --base <commit>, --update).`);
    }
  }
  return parsed;
}

function report(problems) {
  console.error("Taille des fichiers (AGENTS.md « Taille des fichiers », issue #39) :");
  for (const problem of problems) console.error(`  - ${problem}`);
  return 1;
}

function main() {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const baselinePath = join(root, "file-size-baseline.json");
  const baseline = readBaseline(baselinePath);
  const { update, base } = parseArgs(process.argv.slice(2));
  const { files, tracked } = measure(root);
  if (update) {
    // Un fichier listé que l'arbre de travail ne montre plus mais que git suit (supprimé sans
    // `git rm`, checkout partiel) ne doit pas perdre son entrée : elle ne pourrait pas y revenir.
    const missing = Object.keys(baseline.files ?? {}).filter((path) => !(path in files) && tracked.has(path));
    if (missing.length > 0) {
      throw new Error(`Fichier listé absent de l'arbre de travail mais suivi : ${missing.join(", ")}. Restaure-le (git checkout) ou retire-le (git rm), puis relance --update.`);
    }
    // Une référence invalide est refusée avant d'être réécrite : le fichier reste intact.
    const broken = ceilingProblems(baseline.files ?? {}, "la référence");
    if (broken.length > 0) return report(broken);
    const next = lowered(files, baseline);
    writeFileSync(baselinePath, `${JSON.stringify(next, null, 2)}\n`);
    // La mise à jour abaisse seulement : un nouveau fichier trop long ou une croissance restent
    // des violations, et la commande ne doit pas annoncer un succès qui n'en est pas un.
    const remaining = check(files, next, null, tracked);
    return remaining.length === 0 ? 0 : report(remaining);
  }
  const problems = check(files, baseline, baseOf(root, base), tracked);
  return problems.length === 0 ? 0 : report(problems);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(`Taille des fichiers : ${error.message}`);
    process.exitCode = 1;
  }
}
