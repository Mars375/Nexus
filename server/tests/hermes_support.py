"""Support for the Hermes adapter tests: a fake `hermes` executable and JSON fixtures.

No test ever runs the real `hermes` binary: `NEXUS_HERMES_BIN` points to a launcher around
`fake_hermes.py`, which replays a scenario (`scenario.json`: for each sub-command, a list of
answers consumed in order, the last one repeating) and logs every call to `calls.jsonl`.
The fixture shapes are copied from `kanban_output.py` (Hermes 0.23.0).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from nexus.adapters.base import RunInfo

TASK_ID = "t_9f3a01bc"
T0 = 1_788_000_000  # seconds since the epoch

FAKE_SCRIPT = r'''
import json, os, sys, time
from pathlib import Path

here = Path(__file__).parent
args = sys.argv[1:]
if args[:3] != ["kanban", "--board", "nexus"] or len(args) < 4 or args[3] == "boards":
    sys.exit(2)  # a call without the board before the sub-command, or touching boards
sub = args[3]
stdin = sys.stdin.buffer.read().decode("utf-8") if "--body-file" in args else None
state_file = here / "state.json"
state = json.loads(state_file.read_text()) if state_file.exists() else {}
scenario = json.loads((here / "scenario.json").read_text(encoding="utf-8"))
answers = scenario.get(sub) or [{"exit": 1, "stderr": "no scenario for " + sub}]
index = min(state.get(sub, 0), len(answers) - 1)
state[sub] = state.get(sub, 0) + 1
state_file.write_text(json.dumps(state))
with (here / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps({
        "argv": args, "env": sorted(os.environ), "utf8": os.environ.get("PYTHONUTF8"),
        "stdin": stdin, "at": time.time(),
        "environ": {k: v for k, v in os.environ.items() if k.startswith(("HERMES", "CODEX"))},
    }) + "\n")
answer = answers[index]
if answer.get("hang"):
    while True:
        time.sleep(0.05)
out = answer.get("stdout", "")
sys.stdout.buffer.write((out if isinstance(out, str) else json.dumps(out)).encode("utf-8"))
sys.stderr.buffer.write(answer.get("stderr", "").encode("utf-8"))
sys.exit(answer.get("exit", 0))
'''


def make_fake_hermes(folder: Path, **scenario) -> Path:
    """A launcher for the fake binary in `folder`, replaying `scenario`."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "fake_hermes.py"
    script.write_text(FAKE_SCRIPT, encoding="utf-8")
    set_scenario(folder, **scenario)
    if sys.platform == "win32":
        launcher = folder / "fake-hermes.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = folder / "fake-hermes"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        launcher.chmod(0o755)
    return launcher


def set_scenario(folder: Path, **scenario) -> None:
    (folder / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    state = folder / "state.json"
    if state.exists():
        state.unlink()


def calls(binary: Path) -> list[dict]:
    log = binary.parent / "calls.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def subcommands(binary: Path) -> list[str]:
    return [c["argv"][3] for c in calls(binary)]


def reply(stdout=None, *, exit: int = 0, stderr: str = "", hang: bool = False) -> dict:
    return {"stdout": "" if stdout is None else stdout, "exit": exit, "stderr": stderr,
            "hang": hang}


def event(kind: str, at: int = T0, payload: dict | None = None, run_id: int | None = None) -> dict:
    return {"kind": kind, "payload": payload, "created_at": at, "run_id": run_id}


def show_payload(status: str = "running", events: list | None = None, runs: list | None = None,
                 created_at: int = T0, task_id: str = TASK_ID, summary: str | None = None) -> dict:
    return {
        "task": {"id": task_id, "title": "Nexus nx-run-1 nx-task-1", "status": status,
                 "assignee": "default", "created_at": created_at, "created_by": "nexus"},
        "latest_summary": summary, "comments": [], "events": events or [], "runs": runs or [],
    }


def run_row(run_id: int = 1, outcome: str | None = None, summary: str | None = None,
            metadata: dict | None = None) -> dict:
    return {"id": run_id, "profile": "default", "status": outcome or "running",
            "outcome": outcome, "summary": summary, "error": None, "metadata": metadata}


def attachment(path: str | Path, size: int, uploaded_by: str = "kanban_complete") -> dict:
    return {"id": 1, "task_id": TASK_ID, "filename": Path(str(path)).name,
            "stored_path": str(path), "size": size, "uploaded_by": uploaded_by}


def assignees(profile: str = "default", on_disk: bool = True) -> list[dict]:
    return [{"name": profile, "on_disk": on_disk, "counts": {}}]


def created(status: str = "ready", task_id: str = TASK_ID, title: str = "Nexus nx-run-1 nx-task-1",
            assignee: str = "default") -> dict:
    return {"id": task_id, "title": title, "status": status, "assignee": assignee,
            "created_at": T0, "created_by": "nexus"}


def run_info(n: int = 1, *, brief: str = "Fais le travail", external_ref: str | None = None,
             cursor: str | None = None, workdir: str | None = None, agent: str = "helios",
             native_status: str | None = None) -> RunInfo:
    return RunInfo(
        run_id=n, ref=f"nx-run-{n}", task="nx-task-1", executor="hermes", agent=agent,
        brief=brief, workdir=workdir, external_ref=external_ref, status="dispatched",
        native_status=native_status, watch_cursor=cursor, version=1)
