"""The network probe of a Codex run under Windows (#207, spec 2026-11-26, §4 and §6).

Under `windows.sandbox=unelevated`, Codex only points the proxy variables at a dead port: a
command of the agent that ignores them reaches any host. Nexus runs MXC strict instead
(`codex_cli.WINDOWS_SANDBOX`, never `prefer_mxc`, which falls back to the old sandbox), and before
each run asks the same sandbox, in the worktree and with the run's environment, to connect to
`192.0.2.1:443` (TEST-NET-1, RFC 5737: routed nowhere, no real host is ever contacted). Only the
exact answer `ERR 10013` (`WSAEACCES`, the refusal MXC gives at once) with code 0 lets the run
start. Anything else (a connection, a timeout, another error, an empty output, MXC missing, an
overrun) refuses the launch in fixed words, with no fallback and no model call. The output is read
in memory only, never logged nor stored.

The probe measures the cut under `codex sandbox`; that `exec` applies it too is confirmed only by a
real run (spec 2026-11-26, §4 step 4).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from nexus.adapters import codex_cli

# The probe, as Python reads it. `winerror` is None for a timeout (the signature of `unelevated`).
PROBE_SOURCE = """\
import socket
try:
    socket.create_connection(('192.0.2.1', 443), 3)
    print('CONNECTE')
except OSError as error:
    print('ERR', getattr(error, 'winerror', None))
"""
# What crosses the command line: one line, hex digits and no character `cmd.exe` would read again
# inside quotes (a `.cmd` launcher may stand for Codex), with a space so that it stays quoted.
PROBE = f"import socket; exec(bytes.fromhex('{PROBE_SOURCE.encode('ascii').hex()}'))"
EXPECTED = "ERR 10013\n"
REFUSED = "contrôle réseau : le réseau du bac à sable n'est pas coupé"


def probe_argv(
    binary: str, worktree: str | os.PathLike[str], python: str = sys.executable,
) -> list[str]:
    """`codex sandbox` with the very sandbox pair of the run (`-P :workspace` is required)."""
    return [
        binary, "sandbox", "-C", os.fspath(worktree), "-P", ":workspace",
        *codex_cli.WINDOWS_SANDBOX, "--", python, "-I", "-c", PROBE,
    ]


def check_network_cut(
    binary: str, worktree: Path, env: dict[str, str], *, python: str = sys.executable,
    timeout: float = codex_cli.CONTROL_TIMEOUT,
) -> None:
    """ValueError unless the probe prints exactly `ERR 10013` with code 0, in time. Run contained,
    like the other control calls (`ControlNotStopped` when its stop stays unconfirmed)."""
    if sys.platform == "win32" and codex_cli.CMD_SPECIAL & set(python):
        raise ValueError("emplacement refusé : chemin de l'interpréteur avec un caractère spécial")
    out = codex_cli._control(probe_argv(binary, worktree, python), worktree, env, timeout)
    if out != EXPECTED:
        raise ValueError(REFUSED)
