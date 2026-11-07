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


def child_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return {k: v for k, v in source.items()
            if k.upper() in ENV_ALLOW and not k.upper().startswith("NEXUS_")}


def spawn(argv: list[str], cwd: str, env: dict[str, str]) -> subprocess.Popen:
    """A list of arguments, never a shell. Its own process group so the tree can be killed."""
    options: dict = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(
        argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", **options,
    )


def kill_tree(process: subprocess.Popen, timeout: float = 10.0) -> bool:
    """Kill the process and its children; True once it is confirmed gone."""
    if process.poll() is None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, timeout=timeout, check=False,
            )
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
