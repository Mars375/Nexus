"""What the Codex adapter hands to the child, and what it checks before a run (spec #186, §2.2,
§2.4, §3, §5).

The configuration of Loïc stays out of reach: the child gets a `CODEX_HOME` of Nexus's own
(`<NEXUS_DATA_DIR>/codex-home`), flags that ignore the user's configuration and rules, the skills
block removed from the model's input and a closed list of features turned off. Before the run,
`check_isolation` asks Codex itself, with the same arguments and the same environment, that no MCP
server and no skill is in sight; it fails closed. No argument holds a character `cmd.exe` would
read again (a launcher `.cmd` may stand for Codex), and never the brief.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from nexus.adapters import codex_process

# The sandbox of Codex under Windows (decided by Loïc, 2026-11-12): unquoted, read as the variant.
WINDOWS_SANDBOX = ("-c", "windows.sandbox=unelevated")
DISABLED = (
    "hooks", "plugins", "remote_plugin", "apps", "memories", "browser_use", "computer_use",
    "in_app_browser", "tool_suggest", "skill_mcp_dependency_install", "skill_search",
    "standalone_web_search",
)
# The overrides shared by the run and its control calls (§5.2). An unknown feature name makes
# Codex fail: the control calls then refuse the launch before any model runs.
ISOLATION_FLAGS = (
    "-c", "skills.include_instructions=false", "-c", "skills.bundled.enabled=false",
    # No web search (#202): a query leaves the machine and may carry text of the brief or the
    # repository. `web_search` is a top-level key (unset means `cached`), not a feature.
    "-c", "web_search=disabled",
    *(arg for name in DISABLED for arg in ("--disable", name)),
)
CONTROL_TIMEOUT = 30.0
# The versions whose own git calls were measured (step 0b of spec 2026-11-13, measured 2026-11-25
# on a real run: four git at the start of the turn, none after the agent's first command). A new
# version is added only in the PR that joins a new 0b measure (spec 2026-11-25, §4.2, §6).
MEASURED_VERSIONS = frozenset({"codex-cli 0.167.1"})
STOP_ATTEMPTS = 3  # a control call whose stop is unconfirmed is tried again before giving up

CODEX_ENV_ALLOW = codex_process.ENV_ALLOW - {"CODEX_HOME"}
TEMP_NAMES = ("TEMP", "TMP", "TMPDIR")
# What `cmd.exe` may read again in an argument of a `.cmd` launcher, even unquoted by Python.
CMD_SPECIAL = frozenset('&|<>^%!()"')

# Rule 1 of §5.3: entries of the home of Nexus that would configure Codex (compared without case:
# Windows finds `agents.md` for `AGENTS.md`). A refusal list: Codex writes working files of its own.
HOME_FILES = frozenset({"config.toml", "agents.md", "agents.override.md", "hooks.json"})
HOME_FOLDERS = ("rules", "plugins", "memories")
# The one exception (spec 2026-11-23, §4): the trust entries `codex exec` writes in `config.toml`.
TRUST_MAX_BYTES = 64 * 1024
TRUST_VALUES = ({"trust_level": "trusted"}, {"trust_level": "untrusted"})
SKILL_MARKERS = ("<skills_instructions>", "### Skill roots")

# After the brief, on stdin (§1.2): Nexus commits, never the agent. No run reference, no path.
INSTRUCTION = """

---
Consigne de Nexus : tu travailles dans un dossier à part, créé pour ce run.
Ne lance ni `git commit`, ni `git add`, ni aucune commande qui écrit dans git : Nexus enregistre
lui-même tes changements dans un commit, que Loïc relira, quand ton tour se termine sans erreur.
Tu peux lire l'état du dépôt (`git status`, `git diff`, `git log`).
Ne touche pas au fichier .git de ce dossier et ne crée ni dépôt git, ni lien (lien symbolique,
point de jonction, lien physique), ni fichier de plus de 20 Mo : Nexus refuserait alors
d'enregistrer le travail.
Ne laisse aucun processus tourner en arrière-plan : Nexus les arrête avant d'enregistrer.
Si rien n'est à changer, dis pourquoi dans ta réponse finale.
"""


def overrides(*, windows: bool) -> list[str]:
    return [*(WINDOWS_SANDBOX if windows else ()), *ISOLATION_FLAGS]


def argv(binary: str, worktree: str | os.PathLike[str], *, windows: bool) -> list[str]:
    """The command line of the run; the brief goes to stdin (`-`). Never `--add-dir`."""
    return [
        binary, "exec", "--json", "--sandbox", "workspace-write", "--ephemeral",
        "--ignore-user-config", "--ignore-rules", *overrides(windows=windows),
        "--cd", os.fspath(worktree), "-",
    ]


def mcp_list_argv(binary: str, *, windows: bool) -> list[str]:
    return [binary, "mcp", "list", "--json", *overrides(windows=windows)]


def prompt_input_argv(binary: str, *, windows: bool) -> list[str]:
    return [binary, "debug", "prompt-input", *overrides(windows=windows), ""]


def child_env(environ: Mapping[str, str] | None, codex_home: Path) -> dict[str, str]:
    """The allow-list, no inherited `GIT_*`, then what Nexus imposes (§2.4, §5.5). The control
    calls and the run get this same dictionary. The git `codex.exe` runs itself, out of its
    sandbox, reads neither the system nor the global configuration: the scope
    `check_no_filter_driver` reads (spec 2026-11-25, A)."""
    env = codex_process.child_env(environ, allow=CODEX_ENV_ALLOW)
    for name in [n for n in env if n.upper().startswith("GIT_")]:
        del env[name]
    env.update({
        "CODEX_HOME": str(codex_home),
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": os.devnull,
        "GIT_CONFIG_KEY_1": "core.fsmonitor", "GIT_CONFIG_VALUE_1": "false",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    })
    return env


def _key(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.normcase(Path(path).resolve()))


def writable_roots(env: Mapping[str, str], worktree: Path) -> list[Path]:
    """The roots the sandbox is assumed to let the agent write (§2.2): the worktree, the child's
    temporary directories (any case of the name, non-empty values) and, under POSIX, `/tmp`."""
    roots = [worktree]
    roots += [Path(v) for k, v in env.items() if k.upper() in TEMP_NAMES and v.strip()]
    if sys.platform != "win32":
        roots.append(Path("/tmp"))
    return roots


def check_locations(
    env: Mapping[str, str], *, common_dir: Path, gitdir: Path | None, codex_home: Path,
    worktree: Path,
) -> None:
    """ValueError when a git directory or the home of Nexus is, or lies under, a writable root.
    `gitdir` is None before the worktree exists (checked again once it does)."""
    if sys.platform == "win32" and CMD_SPECIAL & set(str(worktree)):
        # `--cd <worktree>` may cross a `.cmd` launcher, whose arguments `cmd.exe` parses again.
        raise ValueError("emplacement refusé : chemin du worktree avec un caractère spécial")
    temps = [v for k, v in env.items() if k.upper() in TEMP_NAMES and v.strip()]
    if any(not Path(v).is_absolute() for v in temps):
        # Codex resolves it from its own folder, not the server's: refused rather than guessed.
        raise ValueError("emplacement refusé : dossier temporaire relatif")
    roots = [_key(r) for r in writable_roots(env, worktree)]
    for checked in (common_dir, gitdir, codex_home):
        if checked is None:
            continue
        place = _key(checked)
        # Both ways: a temporary root (not the worktree) inside one would open part of it too.
        if any(place.is_relative_to(r) for r in roots) or any(
                r.is_relative_to(place) for r in roots[1:]):
            raise ValueError("emplacement refusé : dossier git ou CODEX_HOME et racine "
                             "inscriptible (worktree ou dossier temporaire) imbriqués")


def _trust_only(path: Path, roots: Sequence[Path]) -> bool:
    """True when `path` holds only the trust entries `codex exec` writes itself (spec 2026-11-23,
    §4): a regular file of at most 64 KiB, strict UTF-8 TOML, `{"projects": P}` with P not empty,
    each value exactly one `trust_level`, each key the root of a configured repository (never
    resolved on the disk). Any doubt is False; nothing read is ever kept or told."""
    try:
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            return False
        with path.open("rb") as file:
            data = file.read(TRUST_MAX_BYTES + 1)
        if len(data) > TRUST_MAX_BYTES:
            return False
        document = tomllib.loads(data.decode("utf-8"))  # no BOM: strict `utf-8`, never `-sig`
    except (OSError, ValueError, RecursionError):  # TOMLDecodeError, UnicodeDecodeError: values
        return False
    projects = document.get("projects")
    if document.keys() != {"projects"} or not isinstance(projects, dict) or not projects:
        return False
    allowed = {os.path.normcase(str(w.resolve())) for w in roots}
    return all(
        value in TRUST_VALUES and os.path.normcase(key) in allowed
        for key, value in projects.items()
    )


def _check_home(home: Path, roots: Sequence[Path]) -> None:
    if not home.is_dir():
        raise ValueError("CODEX_HOME de Nexus absent")
    for entry in home.iterdir():
        name = entry.name.casefold()
        if name == "config.toml" and _trust_only(entry, roots):
            continue  # a refusal is raised below, out of any `except`: no parser message as context
        if name in HOME_FILES or name.endswith(".config.toml"):
            raise ValueError("CODEX_HOME de Nexus configuré : lancement refusé")
        if name in HOME_FOLDERS or name == "skills":
            if not entry.is_dir() or entry.is_symlink():
                raise ValueError("CODEX_HOME de Nexus configuré : lancement refusé")
            allowed = {".system"} if name == "skills" else set()
            if any(child.name not in allowed for child in entry.iterdir()):
                raise ValueError("CODEX_HOME de Nexus configuré : lancement refusé")


class ControlNotStopped(ValueError):
    """A control call whose stop stayed unconfirmed: it may still run in the worktree, so the
    launch is refused without removing it (its job handle stays open, never closed early)."""


def _control(argv_: list[str], worktree: Path, env: dict[str, str], timeout: float) -> str | None:
    """Run one control call contained and bounded; its output, read in memory only, or None when
    it failed or overran. Never logged. The tree is always stopped, confirmed, before returning."""
    process = codex_process.spawn(argv_, str(worktree), env, contain=True,
                                  stdin=subprocess.DEVNULL)
    out: str | None = None
    try:
        out, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        out = None
    finally:
        stopped = any(codex_process.kill_tree(process) for _ in range(STOP_ATTEMPTS))
        if not stopped:
            # Raised here, over any error of `communicate`: the launch must keep the worktree.
            # The pipes stay open: one still held by a child could block its close (Windows).
            raise ControlNotStopped("contrôle d'isolement : arrêt non confirmé")
        for pipe in filter(None, (process.stdout, process.stderr)):
            pipe.close()
    return out if process.returncode == 0 else None


_UNREADABLE = object()


def _decoded(text: str | None) -> object:
    if text is None:
        return _UNREADABLE
    try:
        return json.loads(text)
    except ValueError:
        return _UNREADABLE


def check_version(
    binary: str, cwd: Path, env: dict[str, str], *, timeout: float = CONTROL_TIMEOUT,
) -> None:
    """ValueError unless `codex --version` prints exactly one measured version and a newline, with
    code 0 and in time (spec 2026-11-25, B). Run contained, with the run's environment."""
    out = _control([binary, "--version"], cwd, env, timeout)
    if out not in {version + "\n" for version in MEASURED_VERSIONS}:
        raise ValueError("contrôle d'isolement : version de Codex non relevée")


def check_no_project_config(path: Path) -> None:
    """A `.codex` entry (folder, file or link) at the root of the main repository or of the
    worktree is refused (§11, Q5; spec 2026-11-23: the controls read the main one's hooks)."""
    if os.path.lexists(path / ".codex"):
        raise ValueError("configuration de projet .codex dans le dépôt : lancement refusé")


def check_isolation(
    binary: str, worktree: Path, env: dict[str, str], *, windows: bool,
    repo_roots: Sequence[Path], timeout: float = CONTROL_TIMEOUT,
) -> None:
    """The three checks of §5.3 (and a project configuration of Codex, refused: §11, Q5), in the
    worktree, with the run's environment and overrides. `repo_roots` are all the configured
    repositories: the home of Nexus is shared by them. ValueError on any doubt."""
    _check_home(Path(env["CODEX_HOME"]), repo_roots)
    check_no_project_config(worktree)
    listed = _control(mcp_list_argv(binary, windows=windows), worktree, env, timeout)
    if listed is None or _decoded(listed) != []:
        raise ValueError("contrôle d'isolement : mcp list n'est pas vide")
    prompt = _control(prompt_input_argv(binary, windows=windows), worktree, env, timeout)
    decoded = _decoded(prompt)
    if prompt is None or decoded is _UNREADABLE:
        raise ValueError("contrôle d'isolement : prompt-input illisible")
    # The decoded strings too: a marker whose `<` is a JSON unicode escape hides from the raw text.
    seen = prompt + json.dumps(decoded, ensure_ascii=False)
    if any(marker in seen for marker in SKILL_MARKERS):
        raise ValueError("contrôle d'isolement : prompt-input contient des skills")
