"""The git that `codex.exe` launches itself, out of its sandbox, at the start of a turn (spec
2026-11-25, A; exp4 and exp5). With the child's environment it reads neither the system nor the
global configuration, so a filter driver defined there never runs. Real git, never Codex."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from codex_support import git, make_repo

from nexus.adapters import codex_cli, codex_git

DRIVER = """import sys
from pathlib import Path
Path(sys.argv[1]).write_text("ran", encoding="utf-8")
sys.stdout.buffer.write(sys.stdin.buffer.read())
"""
# The argv of `git status` measured from `codex.exe` 0.167.1 (spec 2026-11-25, §0).
STATUS = ["git", "-c", "safe.bareRepository=explicit", "-c", f"core.hooksPath={os.devnull}",
          "-c", "core.fsmonitor=false", "status", "--porcelain"]


def quoted(path: Path) -> str:
    """A path as `sh` reads it in a driver command: forward slashes, double quotes."""
    return '"' + path.as_posix() + '"'


@pytest.fixture
def scene(tmp_path):
    """A tracked `.gitattributes` naming `probe`, defined only in a personal `.gitconfig`; a
    worktree created as Nexus creates it; a tracked file made dirty (same size, newer mtime)."""
    repo = make_repo(tmp_path / "repo")
    (repo / ".gitattributes").write_text("*.txt filter=probe\n", encoding="utf-8")
    git(repo, "add", ".gitattributes")
    git(repo, "commit", "-q", "-m", "attributs")
    home = tmp_path / "personnel"
    home.mkdir()
    driver, witness = tmp_path / "driver.py", tmp_path / "witness.txt"
    driver.write_text(DRIVER, encoding="utf-8")
    command = f"{quoted(Path(sys.executable))} {quoted(driver)} {quoted(witness)}"
    git(home, "config", "--file", str(home / ".gitconfig"), "filter.probe.clean", command)
    tree = codex_git.create_worktree(repo, tmp_path / "data" / "worktrees", "nx-run-1")
    dirty = tree.path / "a.txt"
    later = dirty.stat().st_mtime + 100
    os.utime(dirty, (later, later))
    environ = {k: v for k, v in os.environ.items() if k.upper() in codex_cli.CODEX_ENV_ALLOW}
    drive, rest = os.path.splitdrive(str(home))
    environ.update(HOME=str(home), USERPROFILE=str(home), HOMEDRIVE=drive, HOMEPATH=rest)
    return tree.path, environ, witness


def status(worktree: Path, env: dict[str, str]) -> None:
    subprocess.run(STATUS, cwd=worktree, env=env, capture_output=True, check=True)


def test_without_the_two_keys_the_personal_filter_driver_runs(scene, tmp_path):
    """The control of the test: the scene does make git run the driver."""
    worktree, environ, witness = scene
    env = codex_cli.child_env(environ, tmp_path / "codex-home")
    for name in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"):
        env.pop(name, None)
    status(worktree, env)
    assert witness.exists()


def test_with_the_childs_environment_no_system_or_global_driver_runs(scene, tmp_path):
    worktree, environ, witness = scene
    status(worktree, codex_cli.child_env(environ, tmp_path / "codex-home"))
    assert not witness.exists()
