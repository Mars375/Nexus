"""Hardening of the Codex adapter (review of #170): git, settling, translation."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from codex_support import (
    FAILED,
    OK_LINES,
    THREAD,
    TURN,
    git,
    make_fake_codex,
    make_repo,
    run_info,
)

from nexus.adapters import codex_git, codex_process
from nexus.adapters.codex import CodexAdapter
from nexus.adapters.codex_translate import translate_line


def tree_of(tmp_path) -> tuple[Path, codex_git.Worktree]:
    repo = make_repo(tmp_path / "repo")
    return repo, codex_git.create_worktree(repo, tmp_path / "wt", "nx-run-1")


# --- A1: git runs from the repository, with a clean environment, and judges the branch ------


def test_a_post_checkout_hook_of_the_repository_never_runs(tmp_path):
    repo = make_repo(tmp_path / "repo")
    marker = tmp_path / "hook-ran"
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(f'#!/bin/sh\necho x > "{marker.as_posix()}"\n', encoding="utf-8")
    hook.chmod(0o755)

    codex_git.create_worktree(repo, tmp_path / "wt", "nx-run-1")

    assert not marker.exists()


def test_git_gets_the_filtered_environment_and_no_prompt_or_global_config(monkeypatch):
    monkeypatch.setenv("NEXUS_TOKEN", "nxt_secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["env"] = argv, kwargs["env"]
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    codex_git.git(Path("."), "status")

    assert not {k for k in seen["env"] if k.upper().startswith("NEXUS_")}
    assert "OPENAI_API_KEY" not in seen["env"]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0" and seen["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
    assert seen["env"]["GIT_CONFIG_GLOBAL"]
    assert "core.fsmonitor=false" in seen["argv"] and any(
        a.startswith("core.hooksPath=") for a in seen["argv"])


def test_a_commit_in_the_branch_is_the_proof(tmp_path):
    _, tree = tree_of(tmp_path)
    git(tree.path, "commit", "--allow-empty", "-q", "-m", "work")

    assert codex_git.proof(tree) == git(tree.path, "rev-parse", "HEAD")


def test_a_fake_local_git_directory_in_the_worktree_proves_nothing(tmp_path):
    repo, tree = tree_of(tmp_path)
    (tree.path / ".git").unlink()
    shutil.copytree(repo / ".git", tree.path / ".git")
    git(tree.path, "commit", "--allow-empty", "-q", "-m", "fake")

    assert codex_git.proof(tree) is None  # the branch of the repository did not move


def test_a_detached_head_commit_proves_nothing(tmp_path):
    _, tree = tree_of(tmp_path)
    git(tree.path, "checkout", "-q", "--detach")
    git(tree.path, "commit", "--allow-empty", "-q", "-m", "detached")

    assert codex_git.proof(tree) is None


def test_a_git_timeout_or_a_missing_git_is_a_failed_command_not_an_exception(monkeypatch, tmp_path):
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    assert codex_git.git(tmp_path, "status").returncode != 0

    def missing(argv, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)
    assert codex_git.git(tmp_path, "status").returncode != 0


# --- A3: settling is retryable, confirmed, and not racing the reader ---------------------------


def rig(tmp_path, **scenario):
    binary = make_fake_codex(tmp_path / "fake", **scenario)
    repo = make_repo(tmp_path / "repo")
    return CodexAdapter(str(binary), [repo], tmp_path / "data", max_seconds=0), repo


def test_an_unconfirmed_kill_at_the_time_limit_keeps_the_run_open_and_is_retried(
    tmp_path, monkeypatch
):
    adapter, _ = rig(tmp_path, lines=[THREAD, TURN], hang=True)
    adapter.dispatch(run_info(1))
    real = codex_process.kill_tree
    monkeypatch.setattr(codex_process, "kill_tree", lambda *a, **k: False)

    with pytest.raises(RuntimeError):
        adapter.watch(run_info(1, external_ref="x"))
    monkeypatch.setattr(codex_process, "kill_tree", real)
    result = adapter.watch(run_info(1, external_ref="x"))

    assert result.events[-1].kind == "failed" and "durée maximale" in result.events[-1].payload[
        "cause"]
    assert [e.kind for e in result.events].count("failed") == 1


def test_a_kill_that_times_out_is_reported_as_unconfirmed(monkeypatch):
    process = codex_process.spawn(
        [sys.executable, "-c", "import sys; sys.stdin.read()"], ".", codex_process.child_env())

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    if sys.platform == "win32":
        assert codex_process.kill_tree(process, timeout=0.2) is False
    monkeypatch.undo()
    assert codex_process.kill_tree(process) is True


def test_no_event_follows_the_closing_one(tmp_path):
    adapter, _ = rig(tmp_path, lines=[THREAD, TURN], hang=True)
    adapter.dispatch(run_info(1))
    adapter.watch(run_info(1, external_ref="x"))
    job = adapter._job("nx-run-1")

    job.add("progress", "tardif", "x")  # a reader still draining after the close

    assert job.events[-1].kind == "failed"


def test_a_turn_that_overran_the_limit_is_failed_even_if_it_ended_before_the_poll(tmp_path):
    binary = make_fake_codex(tmp_path / "fake", lines=OK_LINES, commit=True)
    repo = make_repo(tmp_path / "repo")
    adapter = CodexAdapter(str(binary), [repo], tmp_path / "data", max_seconds=5)
    adapter.dispatch(run_info(1))
    adapter.join("nx-run-1", 20)
    job = adapter._job("nx-run-1")
    job.ended_at = job.started + 10  # it finished, but after the limit

    last = adapter.watch(run_info(1, external_ref="x")).events[-1]

    assert last.kind == "failed" and "durée maximale" in last.payload["cause"]


# --- A2: nothing the protocol would refuse is produced ------------------------------------------


@pytest.mark.parametrize("item", [
    {"type": "agent_message", "text": ""},
    {"type": "agent_message", "text": "ghp_" + "A" * 36},
    {"type": "command_execution", "command": "password=hunter2"},
    {"type": "file_change", "changes": []},
])
def test_an_empty_or_secret_only_item_is_not_progress(item):
    assert translate_line(json.dumps({"type": "item.completed", "item": item})) is None


def test_a_failure_message_that_is_only_a_secret_falls_back_to_a_readable_cause():
    line = json.dumps({"type": "error", "message": "ghp_" + "B" * 36})

    fact = translate_line(line)

    assert fact.kind == "failed" and fact.body == "erreur sans détail"


def test_a_secret_only_failure_still_closes_the_run(tmp_path):
    secret = json.dumps({"type": "turn.failed", "error": {"message": "ghp_" + "C" * 36}})
    binary = make_fake_codex(tmp_path / "fake", lines=[THREAD, TURN, secret], exit=1)
    repo = make_repo(tmp_path / "repo")
    adapter = CodexAdapter(str(binary), [repo], tmp_path / "data")
    adapter.dispatch(run_info(1))
    adapter.join("nx-run-1", 20)

    last = adapter.watch(run_info(1, external_ref="x")).events[-1]

    assert last.kind == "failed" and last.payload["cause"] == "échec sans détail"
    assert FAILED  # keeps the fixture import honest
