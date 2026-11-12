"""The git barriers around a `claude-code` run (spec 2026-11-11, §3.4, §4, §5.4; tests 28, 29 and
the adapter side of 48, 53, 55, 59, 60, 62). The commit itself is tested in `test_run_commit_*`."""

import stat
import subprocess
from pathlib import Path

import pytest
from claude_code_support import OK_LINES, Rig, claude_info, write
from codex_support import git
from run_commit_support import isolate_home, witness_filter

from nexus.adapters import codex_git, run_commit


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


def commit_all(repo: Path, message: str = "more") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def raw_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """git as a user would run it: the repository's own hooks and configuration apply."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
                          env=codex_git.clean_env())


def hook_script(witness: Path) -> str:
    return f"#!/bin/sh\necho ran >> '{witness.as_posix()}'\n"


def no_branch_no_worktree(r: Rig) -> None:
    assert not r.worktree.exists()
    assert git(r.repo, "branch", "--list", "nexus/*") == ""
    assert not r.settings_file.exists()
    assert not (r.dir / "args.json").exists()  # `claude` was never started


# --- 28: the hooks of the repository never run ----------------------------------------------------


def test_no_hook_runs_when_nexus_commits(rig, tmp_path):
    witness = tmp_path / "hook-witness.txt"
    r = rig(lines=OK_LINES, actions=[write()])
    hooks = r.repo / ".githooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text(hook_script(witness), encoding="utf-8", newline="")
    (hooks / "pre-commit").chmod(0o755)
    commit_all(r.repo)
    git(r.repo, "config", "core.hooksPath", ".githooks")
    inner = r.repo / ".git" / "hooks" / "pre-commit"
    inner.write_text(hook_script(witness), encoding="utf-8", newline="")
    inner.chmod(inner.stat().st_mode | stat.S_IXUSR)
    control = raw_git(r.repo, "commit", "--allow-empty", "-q", "-m", "control")
    assert control.returncode == 0 and witness.exists(), control.stderr  # the witness works
    witness.unlink()

    r.run()

    assert r.last().kind == "done" and r.head() != r.start()
    assert not witness.exists()


# --- 29: a `.git` file rewritten by the agent -----------------------------------------------------


def test_a_rewritten_dotgit_file_changes_nothing_to_where_the_commit_goes(rig, tmp_path):
    command, witness = witness_filter(tmp_path)
    trap = tmp_path / "trap"
    trap.mkdir()
    git(trap, "init", "-q")
    git(trap, "config", "core.fsmonitor", command)
    raw_git(trap, "status")
    assert witness.exists()  # a git that reads the trap does run it
    witness.unlink()
    r = rig(lines=OK_LINES, actions=[
        {"do": "rewrite_dotgit", "to": str(trap / ".git")}, write()])

    r.run()

    assert r.last().kind == "done", r.last().payload
    names = git(r.repo, "diff-tree", "-r", "--no-commit-id", "--name-only", r.start(), r.head())
    assert names.split() == ["a.txt"]  # `.git` is not in the commit
    assert not witness.exists()
    assert git(trap, "rev-list", "--all", "--count") == "0"  # nothing went to the trap


# --- 3.4: what is checked before anything is created ----------------------------------------------


def test_a_repository_without_an_identity_launches_nothing(rig):
    r = rig(lines=OK_LINES)
    git(r.repo, "config", "--unset", "user.name")
    git(r.repo, "config", "--unset", "user.email")

    with pytest.raises(ValueError, match="identité git"):
        r.adapter.dispatch(claude_info())

    no_branch_no_worktree(r)


def test_an_identity_that_exists_only_in_the_global_configuration_signs_the_commit(
        rig, tmp_path, monkeypatch):
    r = rig(lines=OK_LINES, actions=[write()])
    git(r.repo, "config", "--unset", "user.name")
    git(r.repo, "config", "--unset", "user.email")
    isolate_home(monkeypatch, tmp_path / "home",
                 "[user]\n\tname = Globale Test\n\temail = globale@example.invalid\n")

    r.run()

    assert r.last().kind == "done"
    assert git(r.repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>", r.head()) == (
        "Globale Test <globale@example.invalid>|Globale Test <globale@example.invalid>")


def test_a_filter_driver_in_the_repository_launches_nothing_and_runs_nothing(rig, tmp_path):
    command, witness = witness_filter(tmp_path)
    r = rig(lines=OK_LINES)
    (r.repo / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
    commit_all(r.repo)  # the attributes are in the start commit; the driver comes after
    git(r.repo, "config", "filter.evil.smudge", command)
    git(r.repo, "config", "filter.evil.clean", command)

    with pytest.raises(ValueError, match="pilote de filtre"):
        r.adapter.dispatch(claude_info())

    assert not witness.exists()  # the check came before the extraction of the tree
    no_branch_no_worktree(r)


def test_a_worktree_dir_that_cannot_be_read_removes_the_worktree_and_the_branch(
        rig, monkeypatch):
    r = rig(lines=OK_LINES)

    def broken(tree):
        raise ValueError("dossier git du worktree illisible")

    monkeypatch.setattr(run_commit, "worktree_gitdir", broken)

    with pytest.raises(ValueError):
        r.adapter.dispatch(claude_info())

    no_branch_no_worktree(r)


def test_a_binary_that_cannot_start_removes_what_was_created(rig, tmp_path):
    r = rig(lines=OK_LINES)
    r.adapter.binary = str(tmp_path / "nowhere" / "claude-missing")

    with pytest.raises(OSError):
        r.adapter.dispatch(claude_info())

    no_branch_no_worktree(r)
    assert not r.adapter._jobs


def test_the_next_run_is_not_troubled_by_a_failed_launch(rig, tmp_path):
    r = rig(lines=OK_LINES, actions=[write()])
    good = r.adapter.binary
    r.adapter.binary = str(tmp_path / "nowhere" / "claude-missing")
    with pytest.raises(OSError):
        r.adapter.dispatch(claude_info(1))
    r.adapter.binary = good

    r.run(1)

    assert r.last(1).kind == "done"


# --- how a refusal or a failure of the commit reads -----------------------------------------------


def test_a_nested_repository_fails_the_run_and_nothing_is_added(rig):
    r = rig(lines=OK_LINES, actions=[write(), {"do": "nested_repo"}])
    r.run()

    last = r.last()

    assert last.kind == "failed" and last.evidence == ["branch:nexus/nx-run-1"]
    assert last.payload["cause"] == "commit refusé par Nexus : dépôt git imbriqué"
    assert r.head() == r.start()
    assert (r.worktree / "a.txt").exists()  # kept in the worktree, not committed


def test_a_big_new_file_fails_the_run_with_its_motive(rig):
    r = rig(lines=OK_LINES, actions=[{"do": "big_file", "path": "big.bin", "size": 2048}])
    r.adapter.max_file_bytes = 1024
    r.run()
    assert r.last().payload["cause"] == "commit refusé par Nexus : fichier trop gros"
    assert r.head() == r.start()


def test_a_failing_git_fails_the_run_without_copying_its_output(rig, tmp_path):
    release = tmp_path / "release"
    r = rig(lines=OK_LINES, actions=[write()], wait_for=str(release))
    r.adapter.dispatch(claude_info())
    gitdir = r.repo / ".git" / "worktrees"
    lock = next(gitdir.iterdir()) / "index.lock"
    lock.write_text("", encoding="utf-8")
    release.write_text("go", encoding="utf-8")
    r.adapter.join("nx-run-1", 20)

    last = r.last()

    assert last.kind == "failed" and last.evidence == ["branch:nexus/nx-run-1"]
    assert last.payload["cause"] == "commit de Nexus impossible (add)"
    flat = str([last.subject, last.body, last.payload])
    assert "index.lock" not in flat and "fatal" not in flat
    assert r.head() == r.start()


def test_an_exhausted_budget_says_so_and_never_raises(rig):
    r = rig(lines=OK_LINES, actions=[write()])
    r.adapter.commit_budget = 0.001
    r.run()
    last = r.last()
    assert last.kind == "failed"
    assert last.payload["cause"] == "commit de Nexus impossible (délai dépassé)"

