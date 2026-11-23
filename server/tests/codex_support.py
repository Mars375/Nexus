"""Support for the Codex adapter tests: a fake `codex` executable and throwaway git repos.

No test ever runs the real `codex` binary: `NEXUS_CODEX_BIN` points to a launcher around
`fake_codex.py`, which replays a scenario and never talks to any model. It answers the control
calls of the launch (`mcp list --json`, `debug prompt-input`, spec #186 §5.3) from the scenario
(`mcp_list`, `prompt_input`, and their `_exit` and `_hang`) and notes every call, with its
environment, in `calls.json`.

The run itself prints `lines`, then plays `actions` in the worktree (file system only, like the
fake `claude`: Nexus is the one that commits, spec #186 §1); `commit` is the agent that commits
anyway, which Nexus must refuse (D3); `trust_home` writes the trust entry a real `codex exec`
writes in its `CODEX_HOME` (measured M1, spec 2026-11-23).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from process_support import LAUNCH

from nexus.adapters.base import RunInfo
from nexus.adapters.codex import CodexAdapter
from nexus.adapters.codex_git import clean_env

FAKE_SCRIPT = LAUNCH + '''
import json, os, subprocess, sys
from pathlib import Path

here = Path(__file__).parent
scenario = json.loads((here / "scenario.json").read_text(encoding="utf-8"))
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 0.0.0-fake")
    sys.exit(0)


def record(kind):
    """Every call with its full environment (C4), apart from the files of the run."""
    path = here / "calls.json"
    calls = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    calls.append({"kind": kind, "args": args, "env": dict(os.environ)})
    path.write_text(json.dumps(calls), encoding="utf-8")


def control(name, default):
    """Answer a control call before anything else: no stdin read, no file of the run touched."""
    record(name)
    if scenario.get(name + "_hang"):
        import time
        end = time.monotonic() + 60
        while time.monotonic() < end:
            time.sleep(0.05)
    sys.stdout.write(scenario.get(name, default))
    sys.stdout.flush()
    sys.exit(scenario.get(name + "_exit", 0))


if args[:3] == ["mcp", "list", "--json"]:
    control("mcp_list", "[]")
if args[:2] == ["debug", "prompt-input"]:
    control("prompt_input", json.dumps([{"type": "message", "role": "developer", "content": [
        {"type": "input_text", "text": "Instructions de base."}]}]))
record("run")
(here / "args.json").write_text(json.dumps(args), encoding="utf-8")
(here / "env.json").write_text(json.dumps(sorted(os.environ)), encoding="utf-8")
(here / "stdin.txt").write_bytes(sys.stdin.buffer.read())  # bytes: no newline change
cd = args[args.index("--cd") + 1] if "--cd" in args else "."


def act(step):
    kind, path = step["do"], Path(step.get("path", "a.txt"))
    if kind == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(step.get("content", "work\\n"), encoding="utf-8", newline="")
    elif kind == "big_file":
        path.write_bytes(b"x" * step["size"])
    elif kind == "nested_repo":
        Path("sub/.git").mkdir(parents=True, exist_ok=True)
        Path("sub/.git/config").write_text("[core]\\n", encoding="utf-8")
    elif kind == "gitfile":
        Path("sub").mkdir(exist_ok=True)
        Path("sub/.git").write_text("gitdir: ../elsewhere\\n", encoding="utf-8")
    elif kind == "junction":
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(step["to"], "lien")
        else:
            os.symlink(step["to"], "lien", target_is_directory=True)
    elif kind == "attributes":
        Path(".gitattributes").write_text("* filter=witness\\n", encoding="utf-8")
    elif kind == "ignore_all":
        Path(".gitignore").write_text("*\\n", encoding="utf-8")
    elif kind == "rewrite_dotgit":
        Path(".git").unlink()  # hidden on Windows: replaced, not rewritten in place
        Path(".git").write_text("gitdir: " + step["to"] + "\\n", encoding="utf-8")
    elif kind == "delete_dotgit":
        Path(".git").unlink()
    elif kind == "trust_home":  # what `codex exec` 0.167.1 writes, out of its sandbox (M1)
        key = os.path.normcase(str(Path(step["repo"]).resolve()))
        entry = "[projects." + json.dumps(key) + "]\\ntrust_level = \\"trusted\\"\\n"
        (Path(os.environ["CODEX_HOME"]) / "config.toml").write_bytes(entry.encode("utf-8"))


for line in scenario.get("lines", []):
    print(line, flush=True)
for step in scenario.get("actions", []):
    act(step)
if scenario.get("commit"):  # the agent commits anyway (D3): Nexus must refuse the run
    subprocess.run(
        ["git", "-c", "user.name=fake", "-c", "user.email=fake@example.invalid",
         "commit", "--allow-empty", "-m", "work"], cwd=cd, check=True, capture_output=True)
if scenario.get("detach"):  # a grandchild that outlives this process and holds its stdout
    launch_detached(scenario["detach"])
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


def mcp_call(event: str = "item.completed", server: str = "srv", tool: str = "tool") -> str:
    return json.dumps({"type": event, "item": {
        "id": "i9", "type": "mcp_tool_call", "server": server, "tool": tool,
        "arguments": {}, "status": "completed"}})


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


def calls(folder: Path) -> list[dict]:
    """The calls the fake received, in order: `kind` (`mcp_list`, `prompt_input`, `run`), `args`,
    `env`."""
    path = folder / "calls.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd, capture_output=True, text=True, check=True, env=clean_env())
    return done.stdout.strip()


def write(path: str = "a.txt", content: str = "work\n") -> dict:
    """The `write` action of the fake: a file of the worktree (accents allowed)."""
    return {"do": "write", "path": path, "content": content}


def wrote(worktree: Path) -> bool:
    """The fake's own `write()` happened: `a.txt` differs from the one of the starting commit."""
    path = worktree / "a.txt"
    return path.exists() and path.read_bytes() != b"a"


def make_repo(path: Path, *, identity: bool = True) -> Path:
    """A repository with one commit. `identity` writes a git identity in the repository itself:
    a Codex launch resolves one (spec #186, §1.4), and a CI runner has no global one."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    if identity:
        git(path, "config", "user.name", "Codex Test")
        git(path, "config", "user.email", "codex-test@example.invalid")
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


def fail_closing_once(job):
    """The closing event cannot be added once (the exception between `commit_run` and the event)."""
    real, failed = job.add, []

    def add(kind, subject, *args, final=False, **kwargs):
        if final and not failed:
            failed.append(kind)
            raise RuntimeError("événement final perdu")
        return real(kind, subject, *args, final=final, **kwargs)

    job.add = add
    return failed


def trust_home(repo: Path) -> dict:
    """The `trust_home` action of the fake: the trust entry of `repo` in `$CODEX_HOME`."""
    return {"do": "trust_home", "repo": str(repo)}


def trust_key(path: Path) -> str:
    """A key of `[projects]` as the control compares it, quoted as a TOML basic string."""
    return json.dumps(os.path.normcase(str(path.resolve())))


class Rig:
    def __init__(self, tmp_path: Path, monkeypatch, *, max_seconds=600.0, **scenario):
        self.dir = tmp_path / "fake"
        self.bin = make_fake_codex(self.dir, **scenario)
        self.repo = make_repo(tmp_path / "repo")
        self.data = tmp_path / "data"
        self.home = self.data / "codex-home"
        self.adapter = CodexAdapter(str(self.bin), [self.repo], self.data, max_seconds=max_seconds)
        self.adapter.control_timeout = 1.0
        self.monkeypatch = monkeypatch

    def dispatch(self, n=1):
        return self.adapter.dispatch(run_info(n))

    def run(self, n=1):
        self.dispatch(n)
        self.adapter.join(f"nx-run-{n}", 20)
        return self.adapter.watch(run_info(n, external_ref="x"))

    def kinds(self):
        return [c["kind"] for c in calls(self.dir)]

    def refused(self, match=None):
        """The launch fails, the run was never started, and nothing is left behind."""
        with pytest.raises(ValueError, match=match):
            self.dispatch()
        assert "run" not in self.kinds() and not (self.dir / "args.json").exists()
        assert not (self.data / "worktrees" / "nx-run-1").exists()
        assert git(self.repo, "branch", "--list", "nexus/*") == ""
        assert "nx-run-1" not in git(self.repo, "worktree", "list")
