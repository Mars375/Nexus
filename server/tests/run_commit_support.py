"""Support for the `run_commit` tests: throwaway repositories, a witness filter, a private HOME.

Nothing here reads the global git configuration of the machine: `isolate_home` points both
`HOME` and `USERPROFILE` at a temporary folder (git on Windows reads either). `child_env` drops
every `GIT_*` variable, so exporting `GIT_CONFIG_GLOBAL` would prove nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from codex_support import git, make_repo

from nexus.adapters import codex_git, run_commit

IDENTITY = run_commit.Identity("Nexus Test", "nexus-test@example.invalid")


def isolate_home(monkeypatch, home: Path, gitconfig: str | None = None) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    if gitconfig is not None:
        (home / ".gitconfig").write_text(gitconfig, encoding="utf-8")
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    for name in ("XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL"):
        monkeypatch.delenv(name, raising=False)
    return home


@dataclass
class Job:
    repo: Path
    tree: codex_git.Worktree
    gitdir: Path

    def request(self, **overrides) -> run_commit.CommitRequest:
        fields = dict(
            tree=self.tree, gitdir=self.gitdir, identity=IDENTITY, run_ref="nx-run-1",
            adapter="claude-code", label="Claude Code", model="sonnet",
        )
        fields.update(overrides)
        return run_commit.CommitRequest(**fields)

    def write(self, name: str, content: str | bytes = "work\n") -> Path:
        path = self.tree.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="")
        return path

    def branch_head(self) -> str:
        return git(self.repo, "rev-parse", f"refs/heads/{self.tree.branch}")

    def committed_names(self, sha: str) -> list[str]:
        out = git(self.repo, "diff-tree", "-r", "--no-commit-id", "--name-only", f"{sha}^", sha)
        return sorted(out.splitlines())

    def all_objects(self) -> bytes:
        done = subprocess.run(
            ["git", "cat-file", "--batch-all-objects", "--batch"], cwd=self.repo,
            capture_output=True, check=True, env=codex_git.clean_env())
        return done.stdout


def make_job(tmp_path: Path, files: dict[str, str | bytes] | None = None) -> Job:
    """A repository (one commit, plus `files`) with a worktree `nx-run-1`, ready to commit."""
    repo = make_repo(tmp_path / "repo")
    if files:
        for name, content in files.items():
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8", newline="")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "more")
    tree = codex_git.create_worktree(repo, tmp_path / "wt", "nx-run-1")
    return Job(repo, tree, run_commit.worktree_gitdir(tree))


def witness_filter(tmp_path: Path) -> tuple[str, Path]:
    """A git filter command that appends to a witness file when git runs it, and passes the
    content through. Returns (command, witness)."""
    witness = tmp_path / "witness.txt"
    script = tmp_path / "witness_filter.py"
    script.write_text(
        "import sys\n"
        f"open({str(witness)!r}, 'a').write('ran\\n')\n"
        "sys.stdout.buffer.write(sys.stdin.buffer.read())\n", encoding="utf-8")
    python = Path(sys.executable).as_posix()
    return f"'{python}' '{script.as_posix()}'", witness


class Spy:
    """Wraps `run_commit.run_git`: records the subcommands, may run a hook before one."""

    def __init__(self, monkeypatch, before: dict | None = None, after: dict | None = None):
        self.real = run_commit.run_git
        self.calls: list[tuple[str, ...]] = []
        self.before = before or {}
        self.after = after or {}
        monkeypatch.setattr(run_commit, "run_git", self)

    def __call__(self, cwd, args, **kwargs):
        verb = args[0]
        self.calls.append(tuple(args))
        if verb in self.before:
            self.before[verb](cwd, args, kwargs)
        done = self.real(cwd, args, **kwargs)
        if verb in self.after:
            done = self.after[verb](done, cwd, args, kwargs) or done
        return done

    def verbs(self) -> list[str]:
        return [call[0] for call in self.calls]

    def called(self, verb: str) -> bool:
        return verb in self.verbs()


def make_dir_link(kind: str, link: Path, target: Path) -> None:
    """A junction (Windows only) or a symbolic link to a folder (see `symlink_or_skip`)."""
    if kind == "junction":
        if sys.platform != "win32":
            pytest.skip("point de jonction : Windows seulement")
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        return
    symlink_or_skip(target, link, directory=True)


def symlink_or_skip(target: Path, link: Path, *, directory: bool = False) -> None:
    """A symbolic link; skipped only on Windows, where creating one needs a privilege. Anywhere
    else a failure fails the test, so that the link checks always run in the Linux CI."""
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        if sys.platform != "win32":
            raise
        pytest.skip(f"lien symbolique non créable ici : {type(error).__name__}")
