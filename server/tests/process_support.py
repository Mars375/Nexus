"""Support for the process-tree tests (#186, PR B): a heartbeat grandchild and bounded waits.

The grandchild writes its pid, then rewrites a counter every 50 ms for at most a minute (a test that
fails never leaves it running for long). Its stdout is the one it inherited: launched with
`stdout=1`, it keeps the run's output pipe open after its parent has exited.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BEAT_SCRIPT = '''
import os, sys, time
beat, pid = sys.argv[1], sys.argv[2]
tmp = pid + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(str(os.getpid()))
os.replace(tmp, pid)
end, n = time.monotonic() + 60, 0
while time.monotonic() < end:
    n += 1
    try:
        with open(beat + ".tmp", "w", encoding="utf-8") as f:
            f.write(str(n))
        os.replace(beat + ".tmp", beat)
    except OSError:  # the test is reading it: next beat
        pass
    time.sleep(0.05)
'''

# Launches the grandchild: detached from the console on Windows, still in the job; in the same
# process group on POSIX (no setsid). `stdout=1`: the pipe of the run, inherited explicitly.
LAUNCH = '''
def launch_detached(spec):
    import subprocess, sys
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0
    subprocess.Popen([sys.executable, spec["script"], spec["beat"], spec["pid"]],
                     stdin=subprocess.DEVNULL, stdout=1, stderr=subprocess.DEVNULL,
                     creationflags=flags)
'''


def detach_spec(folder: Path) -> dict:
    """Where the grandchild's script, heartbeat and pid live (passed to a fake as `detach`)."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "beat.py"
    script.write_text(BEAT_SCRIPT, encoding="utf-8")
    return {"script": str(script), "beat": str(folder / "beat.txt"), "pid": str(folder / "pid.txt")}


def wait_until(condition, what: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            raise AssertionError(f"never reached: {what}")
        time.sleep(0.02)


def read_beat(spec: dict) -> str | None:
    try:
        return Path(spec["beat"]).read_text(encoding="utf-8")
    except OSError:
        return None


def grandchild_pid(spec: dict) -> int:
    wait_until(lambda: Path(spec["pid"]).exists(), "the grandchild wrote its pid")
    return int(Path(spec["pid"]).read_text(encoding="utf-8"))


def beating(spec: dict) -> None:
    """Wait (bounded) until the heartbeat has moved at least once."""
    wait_until(lambda: read_beat(spec) is not None, "a first heartbeat")
    first = read_beat(spec)
    wait_until(lambda: read_beat(spec) not in (None, first), "the heartbeat moves")


def stopped(spec: dict, timeout: float) -> bool:
    """True once the heartbeat stays still over 300 ms (six beats), within `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        before = read_beat(spec)
        time.sleep(0.3)
        if read_beat(spec) == before:
            return True
    return False


def alive(pid: int) -> bool:
    """Is the process still running? (A zombie counts as gone on POSIX once reaped.)"""
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
