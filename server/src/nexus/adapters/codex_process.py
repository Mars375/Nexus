"""Child processes of the Codex adapter: filtered environment, no shell, process-tree kill.

Everything here is bounded: nothing waits without a timeout.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping

# Names (upper case) the child may inherit. Nothing else: no `NEXUS_*`, no key from the shell of
# Loïc (ADR-023, D4). Codex finds its own login through its home directory (`CODEX_HOME`, or
# the user profile): TO BE CONFIRMED on the first real run.
ENV_ALLOW = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "LANG", "LC_ALL", "CODEX_HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE",
})
GROUP_POLL = 0.05  # how often an emptying process group is read again (POSIX)


def child_env(
    environ: Mapping[str, str] | None = None, allow: frozenset[str] = ENV_ALLOW
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return {k: v for k, v in source.items()
            if k.upper() in allow and not k.upper().startswith("NEXUS_")}


def spawn(
    argv: list[str], cwd: str, env: dict[str, str], *, text: bool = True,
    stderr: int | None = None, contain: bool = False, stdin: int = subprocess.PIPE,
) -> subprocess.Popen:
    """A list of arguments, never a shell. Its own process group so the tree can be killed.

    `text=False` gives bytes pipes (no newline translation); `stderr` defaults to discarded;
    `stdin` defaults to a pipe (the control calls of Codex pass `DEVNULL`).
    `contain=True` (runs of Codex and claude-code, spec #186 §4): under Windows the process starts
    inside a job object (`process_job_win`); under POSIX `kill_tree` also waits until its process
    group is empty. `contain=False` (Hermes) launches exactly as before.
    """
    options: dict = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    if text:
        options.update(text=True, encoding="utf-8", errors="replace")
    if contain and sys.platform == "win32":
        from nexus.adapters import process_job_win

        return process_job_win.spawn(
            argv, cwd=cwd, env=env, stdin=stdin, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL if stderr is None else stderr, **options,
        )
    process = subprocess.Popen(
        argv, cwd=cwd, env=env, stdin=stdin, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL if stderr is None else stderr, **options,
    )
    if contain:
        process.nexus_job = process.pid  # type: ignore[attr-defined]  # the group it leads
    return process


def kill_tree(process: subprocess.Popen, timeout: float = 10.0) -> bool:
    """Kill the process and its children; True once it is confirmed gone.

    The signal is sent even when the parent is already dead: children may survive it, hold the
    output pipe, and keep working. A contained process (`spawn(contain=True)`) is stopped through
    its job under Windows (every process of the job, orphans included), or through its process
    group under POSIX (killed, then waited for until empty; a descendant that left the group with
    `setsid` is neither killed nor seen: a known limit). Otherwise, on Windows `taskkill /T` needs
    a live parent to walk the tree: a child orphaned by an earlier death of its parent is missed.
    """
    job = getattr(process, "nexus_job", None)
    if job is not None:
        if sys.platform == "win32":
            from nexus.adapters import process_job_win

            return process_job_win.stop(process, job, timeout)
        return _stop_group(process, job, timeout)
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # a member this process may not signal is still there
        return True
    return True


def _stop_group(process: subprocess.Popen, pgid: int, timeout: float) -> bool:
    """POSIX: kill the group, reap its leader, then wait (bounded) until the group is empty."""
    if getattr(process, "nexus_stopped", False):  # confirmed once: its id may be reused since
        return True
    deadline = time.monotonic() + timeout
    if process.poll() is not None and not _group_alive(pgid):
        # Leader reaped and group empty: its id may already belong to another group, so no
        # signal is sent (a pid is not reused while a group of that id still exists).
        process.nexus_stopped = True  # type: ignore[attr-defined]
        return True
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        return False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    while _group_alive(pgid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(GROUP_POLL)
    process.nexus_stopped = True  # type: ignore[attr-defined]
    return True
