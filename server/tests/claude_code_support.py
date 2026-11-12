"""Support for the `claude-code` adapter tests: a fake `claude` executable and a throwaway rig.

No test ever runs the real `claude` binary: `NEXUS_CLAUDE_BIN` points to a launcher around
`fake_claude.py`, which replays a scenario (stream-json lines, then actions on the file system
only, never a git command: Nexus is the one that commits) and never talks to any model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from codex_support import git, make_repo
from run_commit_support import isolate_home

from nexus.adapters.base import RunInfo
from nexus.adapters.claude_code import ClaudeCodeAdapter
from nexus.config import Settings

FAKE_SCRIPT = '''
import json, os, sys, time
from pathlib import Path

here = Path(__file__).parent
scenario = json.loads((here / "scenario.json").read_text(encoding="utf-8"))
args = sys.argv[1:]
if args == ["--version"]:
    time.sleep(scenario.get("version_sleep", 0))
    print("2.1.322 (fake)")
    sys.exit(scenario.get("version_exit", 0))
(here / "args.json").write_text(json.dumps(args), encoding="utf-8")
(here / "env.json").write_text(json.dumps(dict(os.environ)), encoding="utf-8")
(here / "stdin.txt").write_bytes(sys.stdin.buffer.read())
(here / "cwd.txt").write_text(os.getcwd(), encoding="utf-8")


def act(step):
    kind = step["do"]
    if kind == "write":
        path = Path(step["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(step.get("content", "work\\n"), encoding="utf-8", newline="")
    elif kind == "big_file":
        Path(step["path"]).write_bytes(b"x" * step["size"])
    elif kind == "nested_repo":
        Path("sub/.git").mkdir(parents=True, exist_ok=True)
        Path("sub/.git/config").write_text("[core]\\n\\tfsmonitor = true\\n", encoding="utf-8")
    elif kind == "rewrite_dotgit":
        Path(".git").unlink()  # hidden on Windows: replaced, not rewritten in place
        Path(".git").write_text("gitdir: " + step["to"] + "\\n", encoding="utf-8")
    elif kind == "hooks_dir":
        Path(".githooks").mkdir(exist_ok=True)
        Path(".githooks/pre-commit").write_text("#!/bin/sh\\nexit 0\\n", encoding="utf-8")
    elif kind == "ignore_all":
        Path(".gitignore").write_text("*\\n", encoding="utf-8")


for text in scenario.get("lines", []):
    print(text, flush=True)
for step in scenario.get("actions", []):
    act(step)
if scenario.get("hang"):
    while True:
        time.sleep(0.05)
release = scenario.get("wait_for")  # stays alive, result already printed, until the file exists
while release and not Path(release).exists():
    time.sleep(0.02)
sys.exit(scenario.get("exit", 0))
'''


def line(**fields) -> str:
    return json.dumps(fields)


TOOLS = ["Edit", "Glob", "Grep", "Read", "Write"]  # the CLI lists them alphabetically


def init(**overrides) -> str:
    fields = {
        "type": "system", "subtype": "init", "cwd": "x", "session_id": "s-1", "tools": TOOLS,
        "mcp_servers": [], "model": "claude-sonnet-5-5", "permissionMode": "dontAsk",
        "slash_commands": [], "apiKeySource": "none",
    }
    fields.update(overrides)
    return json.dumps({k: v for k, v in fields.items() if v is not ...})


INIT_OK = init()
INIT_MCP = init(mcp_servers=[{"name": "m", "status": "connected"}])
INIT_EXTRA_TOOL = init(tools=[*TOOLS, "Bash"])
INIT_MISSING_TOOL = init(tools=[t for t in TOOLS if t != "Edit"])
INIT_BYPASS = init(permissionMode="bypassPermissions")
INIT_BARE = line(type="system", subtype="init", cwd="x", session_id="s-1")


def assistant(*blocks: dict) -> str:
    return line(type="assistant", message={"role": "assistant", "content": list(blocks)})


ASSISTANT_TEXT = assistant({"type": "text", "text": "Je commence."})
ASSISTANT_BASH = assistant({"type": "tool_use", "name": "Bash", "input": {"command": "ls"}})
ASSISTANT_EDIT = assistant(
    {"type": "tool_use", "name": "Edit", "input": {"file_path": "a.txt", "old_string": "a"}})
USER_TOOL_RESULT = line(type="user", message={"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "t1", "content": "RAW-OUTPUT-NEVER-STORED"}]})
RESULT_OK = line(type="result", subtype="success", is_error=False, num_turns=2, duration_ms=1500,
                 result="Fait.", errors=None, permission_denials=[])
RESULT_IS_ERROR = line(type="result", subtype="success", is_error=True,
                       result="Limite d'usage atteinte", permission_denials=[])
RESULT_ERROR_EXEC = line(type="result", subtype="error_during_execution", is_error=True,
                         errors=["boom"], permission_denials=[])
RESULT_DENIALS = line(type="result", subtype="success", is_error=False, num_turns=1,
                      duration_ms=10, permission_denials=[
                          {"tool_name": "Bash", "tool_use_id": "t",
                           "tool_input": {"command": "x"}}])
OK_LINES = [INIT_OK, ASSISTANT_TEXT, ASSISTANT_EDIT, USER_TOOL_RESULT, RESULT_OK]


def write(path: str = "a.txt", content: str = "work\n") -> dict:
    return {"do": "write", "path": path, "content": content}


def make_fake_claude(folder: Path, **scenario) -> Path:
    """A launcher for the fake binary in `folder`, replaying `scenario`."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fake_claude.py").write_text(FAKE_SCRIPT, encoding="utf-8")
    (folder / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    script = folder / "fake_claude.py"
    if sys.platform == "win32":
        launcher = folder / "fake-claude.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = folder / "fake-claude"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        launcher.chmod(0o755)
    return launcher


def claude_info(n: int = 1, *, model: str | None = "sonnet", workdir: str | None = None,
                brief: str = "Fais le travail", external_ref: str | None = None,
                cursor: str | None = None) -> RunInfo:
    return RunInfo(
        run_id=n, ref=f"nx-run-{n}", task="nx-task-1", executor="claude", agent="claude",
        brief=brief, workdir=workdir, external_ref=external_ref, status="dispatched",
        native_status=None, watch_cursor=cursor, version=1, model=model)


class Rig:
    """A fake `claude`, a repository with an identity of its own, an adapter, a private HOME."""

    def __init__(self, tmp_path: Path, monkeypatch, **scenario):
        isolate_home(monkeypatch, tmp_path / "home")
        self.dir = tmp_path / "fake"
        self.bin = make_fake_claude(self.dir, **scenario)
        self.repo = make_repo(tmp_path / "repo")
        git(self.repo, "config", "user.name", "Helios Test")
        git(self.repo, "config", "user.email", "helios@example.invalid")
        self.data = tmp_path / "data"
        self.adapter = ClaudeCodeAdapter(str(self.bin), [self.repo], self.data)
        for name in ("NEXUS_TOKEN", "ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID",
                     "GITHUB_TOKEN"):
            monkeypatch.setenv(name, "must-not-leak")

    @property
    def worktree(self) -> Path:
        return self.data / "worktrees" / "nx-run-1"

    @property
    def settings_file(self) -> Path:
        return self.data / "claude-code" / "nx-run-1.settings.json"

    def run(self, n: int = 1, **kwargs):
        info = claude_info(n, **kwargs)
        sent = self.adapter.dispatch(info)
        self.adapter.join(info.ref, 20)
        return info, sent

    def watch(self, n: int = 1, cursor: str | None = None):
        return self.adapter.watch(claude_info(n, external_ref="x", cursor=cursor))

    def last(self, n: int = 1):
        return self.watch(n).events[-1]

    def seen(self, name: str):
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    def head(self, n: int = 1) -> str:
        return git(self.repo, "rev-parse", f"refs/heads/nexus/nx-run-{n}")

    def start(self) -> str:
        return git(self.repo, "rev-parse", "HEAD")


def settings_for(r: Rig, **extra) -> Settings:
    """Settings that register the rig's fake `claude` and repository."""
    # `codex_bin` points nowhere: Codex would otherwise look itself up on the PATH.
    return Settings(data_dir=r.data, claude_bin=str(r.bin), run_workdirs=(r.repo,),
                    codex_bin=str(r.dir / "no-codex"), **extra)
