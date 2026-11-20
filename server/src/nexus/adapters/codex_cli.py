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
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from nexus.adapters import codex_process

# The sandbox of Codex under Windows (decided by Loïc, 2026-11-12): unquoted, read as the variant.
WINDOWS_SANDBOX = ("-c", "windows.sandbox=unelevated")
DISABLED = (
    "hooks", "plugins", "remote_plugin", "apps", "memories", "browser_use", "computer_use",
    "in_app_browser", "tool_suggest", "skill_mcp_dependency_install", "skill_search",
)
# The overrides shared by the run and its control calls (§5.2). An unknown feature name makes
# Codex fail: the control calls then refuse the launch before any model runs.
ISOLATION_FLAGS = (
    "-c", "skills.include_instructions=false", "-c", "skills.bundled.enabled=false",
    *(arg for name in DISABLED for arg in ("--disable", name)),
)
CONTROL_TIMEOUT = 30.0
STOP_ATTEMPTS = 3  # a control call whose stop is unconfirmed is tried again before giving up

CODEX_ENV_ALLOW = codex_process.ENV_ALLOW - {"CODEX_HOME"}
TEMP_NAMES = ("TEMP", "TMP", "TMPDIR")
# What `cmd.exe` may read again in an argument of a `.cmd` launcher, even unquoted by Python.
CMD_SPECIAL = frozenset('&|<>^%!()"')

# Rule 1 of §5.3: entries of the home of Nexus that would configure Codex (compared without case:
# Windows finds `agents.md` for `AGENTS.md`). A refusal list: Codex writes working files of its own.
HOME_FILES = frozenset({"config.toml", "agents.md", "agents.override.md", "hooks.json"})
HOME_FOLDERS = ("rules", "plugins", "memories")
SKILL_MARKERS = ("<skills_instructions>", "### Skill roots")


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
    calls and the run get this same dictionary."""
    env = codex_process.child_env(environ, allow=CODEX_ENV_ALLOW)
    for name in [n for n in env if n.upper().startswith("GIT_")]:
        del env[name]
    env.update({
        "CODEX_HOME": str(codex_home),
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": os.devnull,
        "GIT_CONFIG_KEY_1": "core.fsmonitor", "GIT_CONFIG_VALUE_1": "false",
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
        if any(place.is_relative_to(root) for root in roots):
            raise ValueError("emplacement refusé : dossier git ou CODEX_HOME dans une racine "
                             "inscriptible (worktree ou dossier temporaire)")


def _check_home(home: Path) -> None:
    if not home.is_dir():
        raise ValueError("CODEX_HOME de Nexus absent")
    for entry in home.iterdir():
        name = entry.name.casefold()
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
        if stopped:  # unconfirmed, a pipe may still be held: closing it could block (Windows)
            for pipe in filter(None, (process.stdout, process.stderr)):
                pipe.close()
    if not stopped:
        raise ControlNotStopped("contrôle d'isolement : arrêt non confirmé")
    return out if process.returncode == 0 else None


_UNREADABLE = object()


def _decoded(text: str | None) -> object:
    if text is None:
        return _UNREADABLE
    try:
        return json.loads(text)
    except ValueError:
        return _UNREADABLE


def check_isolation(
    binary: str, worktree: Path, env: dict[str, str], *, windows: bool,
    timeout: float = CONTROL_TIMEOUT,
) -> None:
    """The three checks of §5.3 (and a project configuration of Codex, refused: §11, Q5), in the
    worktree, with the run's environment and overrides. ValueError on any doubt."""
    _check_home(Path(env["CODEX_HOME"]))
    if os.path.lexists(worktree / ".codex"):
        raise ValueError("configuration de projet .codex dans le dépôt : lancement refusé")
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
