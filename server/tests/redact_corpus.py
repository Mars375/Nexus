"""Synthetic corpus for the measure of `nexus.secrets.redact` (spec §7.1, plan PR 2 §2).

Invented text only, built at runtime from a fixed seed: French and English prose, Windows and
POSIX paths, URLs without credentials, UUIDs, provenance references, short SHAs, code blocks
and Markdown tables. Two kinds carry a full hex digest (`full_sha`, 40 hex; `sha256`, 64 hex):
the accepted false positive of decision D0 (option A). Seeded secrets are built at runtime and
only counted. Not a test module: pytest does not collect it.
"""

from __future__ import annotations

import hashlib
import random
import string
import uuid

FR = (
    "le la les un une des et ou mais donc car pour avec sans sous sur dans entre vers chez "
    "tâche échéance réunion projet dépôt branche migration fichier dossier serveur client "
    "conversation message recherche index purge rétention fenêtre lecture écriture curseur "
    "masquage secret jeton sauvegarde copie vérifié relecture fusion commit test rouge vert "
    "étape plan cadrage décision réglage source session ligne colonne table déclencheur "
    "est sont fait faut peut doit reste passe garde coupe relit écrit ouvre ferme lance "
    "après avant pendant depuis toujours jamais encore déjà aussi seulement plutôt "
    "Loïc Nexus Helios Codex Claude Hermes Windows Linux SQLite FastAPI Alembic React "
    "très bien mal vite lent long court grand petit nouveau ancien premier dernier même "
    "ça où là-bas aujourd'hui demain hier lundi mardi novembre décembre"
).split()
EN = (
    "the a an and or but so because for with without under over in into between toward "
    "task deadline meeting project repository branch migration file folder server client "
    "conversation message search index purge retention window read write cursor masking "
    "secret token backup copy verified review merge commit test red green step plan "
    "decision setting source session line column table trigger is are does needs can must "
    "stays keeps cuts reads writes opens closes runs after before during since always "
    "never again already also only rather very well badly fast slow long short large "
    "small new old first last same here there today tomorrow yesterday Monday November "
    "let me check the failing test first then fix the import and rerun the suite"
).split()
EXT = ("py", "ts", "tsx", "md", "json", "toml", "sql", "yml", "css", "sh")
DIRS = (
    "server",
    "src",
    "nexus",
    "conversations",
    "tests",
    "web",
    "components",
    "docs",
    "migrations",
    "versions",
    "adapters",
    "runs",
    "tasks",
    "api",
    "utils",
    "scripts",
)


def sentence(rng: random.Random, words: tuple[str, ...] | list[str]) -> str:
    n = rng.randint(6, 22)
    text = " ".join(rng.choice(words) for _ in range(n))
    tail = rng.choice([".", ".", ".", " ?", " !", " :", ";"])
    if rng.random() < 0.15:
        text += f" ({rng.randint(1, 400)} lignes)"
    if rng.random() < 0.08:
        text += f" #{rng.randint(1, 260)}"
    return text[0].upper() + text[1:] + tail


def paragraph(rng: random.Random, words) -> str:
    return " ".join(sentence(rng, words) for _ in range(rng.randint(1, 6)))


def short_sha(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(7))


def full_sha(rng: random.Random) -> str:
    return hashlib.sha1(rng.randbytes(16)).hexdigest()


def uid(rng: random.Random) -> str:
    return str(uuid.UUID(bytes=rng.randbytes(16), version=4))


def win_path(rng: random.Random) -> str:
    parts = [rng.choice(DIRS) for _ in range(rng.randint(1, 5))]
    return "F:\\Projet\\Exemple\\" + "\\".join(parts) + f"\\{rng.choice(DIRS)}.{rng.choice(EXT)}"


def posix_path(rng: random.Random) -> str:
    parts = [rng.choice(DIRS) for _ in range(rng.randint(1, 5))]
    base = rng.choice(
        [
            "/home/user/projets/app",
            "server/src/nexus",
            "web/src",
            "~/.config/app",
            "/usr/local/lib/python3.13/site-packages",
        ]
    )
    line = f":{rng.randint(1, 900)}" if rng.random() < 0.5 else ""
    return (
        f"{base}/"
        + "/".join(parts)
        + f"/{rng.choice(DIRS)}_{rng.choice(DIRS)}.{rng.choice(EXT)}{line}"
    )


def url(rng: random.Random) -> str:
    return rng.choice(
        [
            f"https://github.com/exemple-org/exemple/pull/{rng.randint(1, 300)}",
            f"https://docs.python.org/3/library/{rng.choice(['sqlite3', 'os', 'asyncio', 're'])}."
            f"html",
            f"http://127.0.0.1:{rng.randint(1024, 9999)}/api/tasks/nx-task-{rng.randint(1, 99)}",
            f"https://www.sqlite.org/fts5.html"
            f"#{rng.choice(['the_optimize_command', 'external_content_tables'])}",
            f"http://localhost:5173/conversations?source=claude-code&limit={rng.randint(1, 100)}",
        ]
    )


def ident(rng: random.Random) -> str:
    return "_".join(rng.choice(DIRS) for _ in range(rng.randint(1, 3)))


def code_block(rng: random.Random) -> str:
    kind = rng.choice(["python", "ts", "bash", "json", "sql", "diff"])
    lines = []
    for _ in range(rng.randint(3, 40)):
        a, b = ident(rng), ident(rng)
        lines.append(
            rng.choice(
                {
                    "python": [
                        f"def {a}({b}: int) -> str:",
                        f'    return f"{{{b}}}-{a}"',
                        f'    {a} = {b}.get("{ident(rng)}", {rng.randint(0, 99)})',
                        f"from nexus.{a} import {b}",
                        f'assert {a} == {b}, "{sentence(rng, EN)}"',
                        "    with opened(candidate) as fd:",
                        f"        os.lseek(fd, {rng.randint(0, 10**7)}, 0)",
                    ],
                    "ts": [
                        f"const {a} = await fetch(`/api/{b}?limit=${{limit}}`);",
                        f"export function {a}({b}: string): number {{",
                        f"  return {b}.length * {rng.randint(1, 9)};",
                        f'import {{ {a} }} from "./{b}";',
                        "}",
                    ],
                    "bash": [
                        f"uv run --directory server pytest -q tests/test_{a}.py -k {b}",
                        f"git log --oneline -5 {short_sha(rng)}",
                        "pnpm --dir web build",
                        f"cd {posix_path(rng)} && ls -la",
                        f'grep -rn "{a}" server/src',
                    ],
                    "json": [
                        f'  "{a}": "{b}",',
                        f'  "{a}": {rng.randint(0, 10**6)},',
                        f'  "id": "{uid(rng)}",',
                        f'  "at": "2026-11-{rng.randint(10, 28)}T10:{rng.randint(10, 59)}:00Z",',
                    ],
                    "sql": [
                        f"SELECT {a}, {b} FROM conversation_messages WHERE id >"
                        f" {rng.randint(1, 9999)};",
                        "INSERT INTO conversation_fts(conversation_fts) VALUES('optimize');",
                        f"UPDATE conversation_cursors SET byte_offset = {rng.randint(0, 10**8)} W"
                        f"HERE path_key = ?;",
                    ],
                    "diff": [
                        f"@@ -{rng.randint(1, 300)},{rng.randint(1, 9)} +{rng.randint(1, 300)}"
                        f",{rng.randint(1, 9)} @@",
                        f"-    {a} = {b}",
                        f"+    {a} = {b}({rng.randint(0, 9)})",
                        f" # {sentence(rng, EN)}",
                    ],
                }[kind]
            )
        )
    return f"```{kind}\n" + "\n".join(lines) + "\n```"


def table(rng: random.Random) -> str:
    rows = ["| Fichier | Lignes | État |", "|---|---|---|"]
    for _ in range(rng.randint(2, 10)):
        rows.append(
            f"| `{posix_path(rng)}` | {rng.randint(1, 400)} |"
            f" {rng.choice(['créé', 'modifié', 'inchangé'])} |"
        )
    return "\n".join(rows)


def message(rng: random.Random, kind: str) -> str:
    words = FR if rng.random() < 0.55 else EN
    parts: list[str] = []
    if kind == "prose":
        parts = [paragraph(rng, words) for _ in range(rng.randint(1, 4))]
    elif kind == "paths":
        for _ in range(rng.randint(1, 4)):
            parts.append(
                f"{sentence(rng, words)} `{rng.choice([win_path, posix_path])(rng)}`"
                f" {sentence(rng, words)} {url(rng)}"
            )
    elif kind == "ids":
        for _ in range(rng.randint(1, 4)):
            parts.append(
                rng.choice(
                    [
                        f"{sentence(rng, words)} session {uid(rng)}, commit {short_sha(rng)}.",
                        f"Référence claude-session:{uid(rng)}/{uid(rng)} ; voir nx-task"
                        f"-{rng.randint(1, 300)}.",
                        f"codex-session:{uid(rng)}/{rng.randint(1, 5000)} à 2026-11"
                        f"-{rng.randint(10, 28)}T0{rng.randint(1, 9)}:12:33Z.",
                        f"PR #{rng.randint(1, 260)} fusionnée en {short_sha(rng)} "
                        f"({sentence(rng, words)})",
                    ]
                )
            )
    elif kind == "code":
        parts = [sentence(rng, words), code_block(rng), sentence(rng, words)]
        if rng.random() < 0.4:
            parts.append(code_block(rng))
    elif kind == "mixed":
        parts = [
            paragraph(rng, words),
            table(rng),
            "- " + sentence(rng, words),
            "- " + sentence(rng, words),
            code_block(rng),
            paragraph(rng, words),
        ]
    elif kind == "full_sha":
        parts = [
            sentence(rng, words),
            f"`git rev-parse HEAD` donne {full_sha(rng)}.",
            paragraph(rng, words),
        ]
    elif kind == "sha256":
        parts = [
            sentence(rng, words),
            f"head_sha256 = {hashlib.sha256(rng.randbytes(8)).hexdigest()}",
            sentence(rng, words),
        ]
    return "\n\n".join(parts)


def seeded_secret(rng: random.Random) -> str:
    alnum = string.ascii_letters + string.digits
    return rng.choice(
        [
            "ghp_" + "".join(rng.choice(alnum) for _ in range(36)),
            "sk-ant-" + "".join(rng.choice(alnum) for _ in range(40)),
            "nxt_" + "".join(rng.choice(alnum + "-_") for _ in range(43)),
            "AKIA" + "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(16)),
            "password=" + "".join(rng.choice(alnum) for _ in range(14)),
            "postgres://alice:" + "".join(rng.choice(alnum) for _ in range(12)) + "@db.local/app",
            "Authorization: Bearer " + "".join(rng.choice(alnum) for _ in range(32)),
        ]
    )


# Weights of the clean corpus. `full_sha` and `sha256` are the categories known to be masked
# (spec §7.1: a 40-character SHA is masked whole); they are reported apart so that the rate
# can be read with and without them.
KINDS = {"prose": 30, "paths": 12, "ids": 12, "code": 22, "mixed": 14, "full_sha": 5, "sha256": 5}

HASH_KINDS = ("full_sha", "sha256")


def build(size: int, *, seed: int, hash_weight: float = 5.0) -> list[tuple[str, str]]:
    """Messages `(kind, text)` until `size` UTF-8 bytes; `hash_weight` weighs each hash kind."""
    rng = random.Random(seed)
    weights = dict(KINDS, full_sha=hash_weight, sha256=hash_weight)
    kinds, values = zip(*((k, w) for k, w in weights.items() if w > 0), strict=True)
    corpus: list[tuple[str, str]] = []
    total = 0
    while total < size:
        kind = rng.choices(kinds, values)[0]
        text = message(rng, kind)
        corpus.append((kind, text))
        total += len(text.encode("utf-8"))
    return corpus


def seeded(count: int, *, seed: int) -> list[tuple[str, str]]:
    """`count` messages `(secret, text)`, each with one secret built at runtime."""
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        secret = seeded_secret(rng)
        out.append((secret, f"{paragraph(rng, FR)} {secret} {paragraph(rng, EN)}"))
    return out


def visible(secret: str, masked: str) -> bool:
    """Whether a seeded secret (or its value after a label) is still readable in `masked`."""
    value = secret.split("=", 1)[-1].split(":", 1)[-1] if "=" in secret else secret
    return secret in masked or (len(value) > 8 and value in masked)


def provenance_ref(rng: random.Random) -> str:
    return f"claude-session:{uid(rng)}/{uid(rng)}"
