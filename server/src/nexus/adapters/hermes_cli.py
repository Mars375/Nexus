"""Calls to the `hermes kanban` CLI for the Hermes adapter (spec §3, §7).

Every call is bounded: a list of arguments (never a shell), its own process group, a timeout,
the process tree killed when it expires, output capped. The board is always `nexus` and always
given before the sub-command. stdout and stderr are never logged: only a fixed prefix of stderr
is compared (`no such task`).
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from nexus.adapters import codex_process

BOARD = "nexus"  # not configurable (ADR-023 D7): Loïc creates it by hand
PROBE_TIMEOUT = 30.0
CLI_TIMEOUT = 30.0
STDOUT_MAX = 4 * 1024 * 1024
STDERR_MAX = 4096
TASK_ID = re.compile(r"t_[0-9a-f]{8}")
PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
RUN_REF = re.compile(r"nx-run-[0-9]{1,12}")
TASK_REF = re.compile(r"nx-task-[0-9]{1,12}")
KNOWN_STATUSES = frozenset({"triage", "todo", "scheduled", "ready", "running", "blocked",
                            "review", "done", "archived"})
# The base list without `CODEX_HOME`, plus where Hermes keeps its home when Loïc moved it. Never
# `HERMES_KANBAN_BOARD` or `HERMES_PROFILE`: they would change the board or profile targeted.
ENV_ALLOW = (codex_process.ENV_ALLOW - {"CODEX_HOME"}) | {"HERMES_HOME"}
NO_SUCH_TASK = "no such task"


class HermesUnavailable(RuntimeError):
    """Hermes could not be read right now: retry on the next tick, nothing changes."""


class HermesRefused(Exception):
    """Hermes refused a command twice: nothing was started."""


@dataclass(frozen=True)
class Result:
    code: int | None  # None: timed out
    stdout: str
    stderr: str
    stopped: bool  # on a timeout: the process tree is confirmed gone

    @property
    def timed_out(self) -> bool:
        return self.code is None


def title_of(ref: str, task: str) -> str:
    if not RUN_REF.fullmatch(ref) or not TASK_REF.fullmatch(task):
        raise ValueError("référence de run invalide")
    return f"Nexus {ref} {task}"


def check_task_id(value: object) -> str:
    if not isinstance(value, str) or not TASK_ID.fullmatch(value):
        raise ValueError("référence Hermes invalide")
    return value


def call(
    binary: str, args: Sequence[str], *, stdin: str | None = None, timeout: float = CLI_TIMEOUT,
    cwd: str, environ: Mapping[str, str] | None = None,
) -> Result:
    """`<binary> kanban --board nexus <args…>`, bounded. Raises OSError if it cannot start."""
    env = codex_process.child_env(environ, ENV_ALLOW)
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    argv = [binary, "kanban", "--board", BOARD, *args]
    process = codex_process.spawn(argv, cwd, env, text=False, stderr=subprocess.PIPE)
    try:
        out, err = process.communicate(
            stdin.encode("utf-8", "replace") if stdin is not None else None, timeout=timeout)
    except subprocess.TimeoutExpired:
        stopped = codex_process.kill_tree(process)
        if stopped:
            try:
                process.communicate(timeout=5.0)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                pass
        return Result(None, "", "", stopped)
    except OSError:  # the process ended before reading its input
        out, err = b"", b""
    return Result(
        process.returncode, out[:STDOUT_MAX + 1].decode("utf-8", "replace"),
        err[:STDERR_MAX].decode("utf-8", "replace"), True)


def read_json(result: Result) -> object:
    """The JSON a successful call printed; HermesUnavailable otherwise (type only, no content)."""
    if result.code != 0 or len(result.stdout) > STDOUT_MAX:
        raise HermesUnavailable("lecture de Hermes impossible")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise HermesUnavailable("sortie de Hermes illisible") from None
