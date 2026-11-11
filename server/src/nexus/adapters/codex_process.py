"""Child processes of the Codex adapter: filtered environment, no shell, process-tree kill.

Everything here is bounded: nothing waits without a timeout.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Mapping

# Names (upper case) the child may inherit. Nothing else: no `NEXUS_*`, no key from the shell of
# Loïc (ADR-023, D4). Codex finds its own login through its home directory (`CODEX_HOME`, or
# the user profile): TO BE CONFIRMED on the first real run.
ENV_ALLOW = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "LANG", "LC_ALL", "CODEX_HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE",
})


def child_env(
    environ: Mapping[str, str] | None = None, allow: frozenset[str] = ENV_ALLOW
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return {k: v for k, v in source.items()
            if k.upper() in allow and not k.upper().startswith("NEXUS_")}


def spawn(
    argv: list[str], cwd: str, env: dict[str, str], *, text: bool = True, stderr: int | None = None
) -> subprocess.Popen:
    """A list of arguments, never a shell. Its own process group so the tree can be killed.

    `text=False` gives bytes pipes (no newline translation); `stderr` defaults to discarded.
    """
    options: dict = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    if text:
        options.update(text=True, encoding="utf-8", errors="replace")
    return subprocess.Popen(
        argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL if stderr is None else stderr, **options,
    )


def kill_tree(process: subprocess.Popen, timeout: float = 10.0) -> bool:
    """Kill the process and its children; True once it is confirmed gone.

    The signal is sent even when the parent is already dead: children may survive it, hold the
    output pipe, and keep working. On Windows `taskkill /T` needs a live parent to walk the tree:
    a child orphaned by an earlier death of its parent cannot be found (to be improved with a
    job object).
    """
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
