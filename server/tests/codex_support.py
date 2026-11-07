"""Support for the Codex adapter tests: a fake `codex` executable and throwaway git repos.

No test ever runs the real `codex` binary: `NEXUS_CODEX_BIN` points to a launcher around
`fake_codex.py`, which replays a scenario and never talks to any model.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from nexus.adapters.base import RunInfo
from nexus.adapters.codex_git import clean_env

FAKE_SCRIPT = '''
import json, os, subprocess, sys
from pathlib import Path

here = Path(__file__).parent
scenario = json.loads((here / "scenario.json").read_text(encoding="utf-8"))
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 0.0.0-fake")
    sys.exit(0)
(here / "args.json").write_text(json.dumps(args), encoding="utf-8")
(here / "env.json").write_text(json.dumps(sorted(os.environ)), encoding="utf-8")
(here / "stdin.txt").write_text(sys.stdin.buffer.read().decode("utf-8"), encoding="utf-8")
cd = args[args.index("--cd") + 1] if "--cd" in args else "."
for line in scenario.get("lines", []):
    print(line, flush=True)
if scenario.get("commit"):
    subprocess.run(
        ["git", "-c", "user.name=fake", "-c", "user.email=fake@example.invalid",
         "commit", "--allow-empty", "-m", "work"], cwd=cd, check=True, capture_output=True)
if scenario.get("hang"):
    import time
    while True:
        time.sleep(0.05)
sys.exit(scenario.get("exit", 0))
'''

THREAD = json.dumps({"type": "thread.started", "thread_id": "t-1"})
TURN = json.dumps({"type": "turn.started"})
MESSAGE = json.dumps({"type": "item.completed", "item": {
    "id": "i1", "type": "agent_message", "text": "Je commence."}})
COMMAND = json.dumps({"type": "item.completed", "item": {
    "id": "i2", "type": "command_execution", "command": "pytest -q",
    "aggregated_output": "RAW-OUTPUT-NEVER-STORED", "exit_code": 0, "status": "completed"}})
DONE = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1}})
FAILED = json.dumps({"type": "turn.failed", "error": {"message": "le modèle a échoué"}})
OK_LINES = [THREAD, TURN, MESSAGE, COMMAND, DONE]


def make_fake_codex(folder: Path, **scenario) -> Path:
    """A launcher for the fake binary in `folder`, replaying `scenario`."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fake_codex.py").write_text(FAKE_SCRIPT, encoding="utf-8")
    (folder / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    script = folder / "fake_codex.py"
    if sys.platform == "win32":
        launcher = folder / "fake-codex.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = folder / "fake-codex"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        launcher.chmod(0o755)
    return launcher


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd, capture_output=True, text=True, check=True, env=clean_env())
    return done.stdout.strip()


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    (path / "a.txt").write_text("a", encoding="utf-8")
    git(path, "add", "a.txt")
    git(path, "commit", "-q", "-m", "init")
    return path


def run_info(n: int = 1, *, workdir: str | None = None, brief: str = "Fais le travail",
             external_ref: str | None = None, cursor: str | None = None) -> RunInfo:
    return RunInfo(
        run_id=n, ref=f"nx-run-{n}", task="nx-task-1", executor="codex", agent="codex",
        brief=brief, workdir=workdir, external_ref=external_ref, status="dispatched",
        native_status=None, watch_cursor=cursor, version=1)
