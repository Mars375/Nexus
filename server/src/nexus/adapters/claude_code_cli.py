"""What the `claude-code` adapter hands to the child: argv, settings file, instruction, environment.

Spec 2026-11-11, §3. No shell, never the brief in an argument. The agent has no tool that runs a
command: five file tools, in the worktree of the run, and Nexus makes the commit itself.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

from nexus.adapters import codex_process
from nexus.runs.rules import RUN_MODELS

MODELS = RUN_MODELS  # the closed list, checked again here before an argv is built
TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")
EXPECTED_TOOLS = frozenset(TOOLS)  # compared as a set: the CLI lists them alphabetically

_GIT_DENIED = (".git", ".git/**", "**/.git", "**/.git/**")
# The real barrier is Nexus's check of the worktree before the commit; these only spare a run.
SETTINGS = {
    "disableAllHooks": True,
    "permissions": {
        "allow": ["Read", "Glob", "Grep", "Edit", "Write"],
        "deny": [f"{tool}({path})" for path in _GIT_DENIED for tool in ("Edit", "Write")],
    },
}

# The brief is followed by this instruction. Its figure is `run_commit.MAX_FILE_BYTES` in MiB (a
# test checks they agree); it names no run, no path and no model.
INSTRUCTION = (
    "\n\n---\n"
    "Consigne de Nexus : tu travailles dans un dossier à part, créé pour ce run.\n"
    "Tu peux lire, créer et modifier des fichiers de ce dossier ; tu ne peux lancer aucune "
    "commande\n"
    "(ni git, ni tests). Ne touche pas aux dossiers .git et ne crée ni dépôt git, ni lien, "
    "ni fichier\n"
    "de plus de 20 Mo : Nexus refuserait alors d'enregistrer le travail.\n"
    "Quand tu as fini, arrête-toi : Nexus enregistre lui-même tes changements dans un commit, "
    "que Loïc\n"
    "relira. Si rien n'est à changer, dis pourquoi dans ta réponse finale.\n"
)

# The login is found through the profile (`USERPROFILE`/`HOME`) or `CLAUDE_CONFIG_DIR`; Claude Code
# on Windows looks for Git Bash at startup (kept: it gives no tool). Never `ANTHROPIC_*`: an API
# key would bill the API instead of the subscription. Never the session variables of a parent
# Claude Code.
CLAUDE_ENV_ALLOW = (codex_process.ENV_ALLOW - {"CODEX_HOME"}) | {
    "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_GIT_BASH_PATH"}

RUN_REF = re.compile(r"nx-run-[1-9][0-9]*")


def argv(binary: str, model: object, settings_path: str | os.PathLike[str]) -> list[str]:
    """The command line. `model` is checked against the closed list, whatever the caller did."""
    if not isinstance(model, str) or model not in MODELS:
        raise ValueError("modèle inconnu")
    return [
        binary, "-p", "--output-format", "stream-json", "--verbose", "--model", model,
        "--restricted", "--strict-mcp-config", "--disable-slash-commands",
        "--no-session-persistence", "--tools", ",".join(TOOLS),
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--settings", os.fspath(settings_path),
    ]


def settings_path(folder: Path, run_ref: str) -> Path:
    if not RUN_REF.fullmatch(run_ref):
        raise ValueError("référence de run invalide")
    return folder / f"{run_ref}.settings.json"


def write_settings(folder: Path, run_ref: str) -> Path:
    """The settings file of the run, outside the worktree (the file tools cannot reach it)."""
    path = settings_path(folder, run_ref)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(SETTINGS, indent=2), encoding="utf-8")
    return path


def child_env(
    environ: Mapping[str, str] | None, *, gitdir: Path, worktree: Path
) -> dict[str, str]:
    """The allow-list, then the values the adapter imposes. The agent runs no git, but Claude Code
    does for its own context: the git barriers stay up for it."""
    env = codex_process.child_env(environ, allow=CLAUDE_ENV_ALLOW)
    for name in [n for n in env if n.upper().startswith(("GIT_", "DISABLE_AUTOUPDATER"))]:
        del env[name]
    env.update({
        "GIT_DIR": str(gitdir), "GIT_WORK_TREE": str(worktree),
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": os.devnull,
        "GIT_CONFIG_KEY_1": "core.fsmonitor", "GIT_CONFIG_VALUE_1": "false",
        "GIT_CONFIG_KEY_2": "commit.gpgsign", "GIT_CONFIG_VALUE_2": "false",
        "GIT_EDITOR": ":", "GIT_TERMINAL_PROMPT": "0", "DISABLE_AUTOUPDATER": "1",
    })
    return env
