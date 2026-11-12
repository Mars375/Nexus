"""The commit sequence of `run_commit` (spec 2026-11-11, §5.4; tests 53, 54, 58-62, 66, 69):
configuration, idempotence, failures, budget, identity, neutrality. No adapter, no fake binary."""

import ast
import dataclasses
import time
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from codex_support import git, make_repo
from run_commit_support import IDENTITY, Spy, isolate_home, make_job, witness_filter

from nexus.adapters import codex_git, run_commit
from nexus.adapters.run_commit import (
    Committed,
    GitFailed,
    Identity,
    Refused,
)


@pytest.fixture(autouse=True)
def private_home(monkeypatch, tmp_path):
    isolate_home(monkeypatch, tmp_path / "home")


def log(job, fmt: str) -> str:
    return git(job.repo, "log", "-1", f"--format={fmt}", job.tree.branch)


# --- 53: filter drivers --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["clean", "smudge", "process"])
def test_a_filter_driver_of_the_repository_is_refused_at_launch(tmp_path, kind):
    job = make_job(tmp_path)
    run_commit.check_no_filter_driver(job.repo)  # none yet: passes
    git(job.repo, "config", f"filter.evil.{kind}", "cat")
    with pytest.raises(ValueError, match="pilote de filtre"):
        run_commit.check_no_filter_driver(job.repo)
    with pytest.raises(ValueError, match="pilote de filtre"):
        run_commit.check_no_filter_driver(job.repo, job.gitdir)


def test_a_filter_that_is_only_required_is_not_a_driver(tmp_path):
    job = make_job(tmp_path)
    git(job.repo, "config", "filter.lfs.required", "true")
    run_commit.check_no_filter_driver(job.repo, job.gitdir)


def test_a_driver_in_the_worktree_config_is_seen_only_with_its_gitdir(tmp_path):
    job = make_job(tmp_path)
    git(job.repo, "config", "extensions.worktreeConfig", "true")
    git(job.tree.path, "config", "--worktree", "filter.evil.clean", "cat")
    run_commit.check_no_filter_driver(job.repo)
    with pytest.raises(ValueError, match="pilote de filtre"):
        run_commit.check_no_filter_driver(job.repo, job.gitdir)


def test_an_unreadable_configuration_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="illisible"):
        run_commit.check_no_filter_driver(tmp_path / "does-not-exist")


def test_a_driver_added_during_the_run_stops_the_commit_before_add(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    command, witness = witness_filter(tmp_path)
    job.write(".gitattributes", "* filter=evil\n")
    job.write("new.txt")
    git(job.repo, "config", "filter.evil.clean", command)  # after the dispatch, during the run
    spy = Spy(monkeypatch)
    assert run_commit.commit_run(job.request()) == Refused("pilote de filtre")
    assert not spy.called("add") and not witness.exists()
    assert job.branch_head() == job.tree.start


# --- 54: the global configuration is never read by the commit ------------------------------------


def global_config(tmp_path, command: str) -> str:
    attrs = tmp_path / "global-attributes"
    attrs.write_text("* filter=evil\n", encoding="utf-8")
    return (
        "[user]\n\tname = Global Person\n\temail = global@example.invalid\n"
        f"[core]\n\tautocrlf = true\n\tattributesFile = {attrs.as_posix()}\n"
        f'[filter "evil"]\n\tclean = {command}\n\tsmudge = {command}\n')


def test_the_global_configuration_is_ignored_by_the_commit(monkeypatch, tmp_path):
    command, witness = witness_filter(tmp_path)
    isolate_home(monkeypatch, tmp_path / "home", global_config(tmp_path, command))
    job = make_job(tmp_path, {"untouched.txt": "one\ntwo\n"})
    job.write(".gitattributes", "* filter=evil\n")
    job.write("new.txt", "hello\n")
    outcome = run_commit.commit_run(job.request())
    assert isinstance(outcome, Committed)
    assert not witness.exists()
    assert job.committed_names(outcome.sha) == [".gitattributes", "new.txt"]


def test_the_witness_does_run_when_the_global_configuration_is_let_through(
    monkeypatch, tmp_path
):
    """The previous test must be able to fail: without the two forced values, the filter runs."""
    command, witness = witness_filter(tmp_path)
    isolate_home(monkeypatch, tmp_path / "home", global_config(tmp_path, command))
    job = make_job(tmp_path)
    job.write(".gitattributes", "* filter=evil\n")
    job.write("new.txt", "hello\n")
    forced = {k: v for k, v in run_commit.FORCED_ENV.items()
              if k not in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
    monkeypatch.setattr(run_commit, "FORCED_ENV", forced)
    monkeypatch.setattr(run_commit.CommitSession, "check_filters", lambda self: None)
    run_commit.commit_run(job.request())
    assert witness.exists()


def test_the_hooks_of_the_repository_never_run(tmp_path):
    job = make_job(tmp_path)
    witness = tmp_path / "hook-witness.txt"
    hook = f"#!/bin/sh\necho ran >> '{witness.as_posix()}'\nexit 0\n"
    for folder in (job.repo / ".githooks", job.repo / ".git" / "hooks"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "pre-commit").write_text(hook, encoding="utf-8", newline="\n")
        (folder / "pre-commit").chmod(0o755)
    git(job.repo, "config", "core.hooksPath", ".githooks")
    job.write("new.txt")
    assert isinstance(run_commit.commit_run(job.request()), Committed)
    assert not witness.exists()


# --- 58: idempotence -----------------------------------------------------------------------------


def test_a_second_pass_gives_the_same_commit_and_does_not_commit_again(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    first = run_commit.commit_run(job.request())
    assert isinstance(first, Committed)
    spy = Spy(monkeypatch)
    assert run_commit.commit_run(job.request()) == first
    assert not spy.called("add") and not spy.called("commit")
    assert git(job.repo, "rev-list", "--count", f"{job.tree.start}..{job.tree.branch}") == "1"


def test_a_commit_already_on_the_branch_is_the_answer_and_nothing_is_added(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    git(job.tree.path, "add", "-A")
    git(job.tree.path, "commit", "-q", "-m", "earlier pass")
    spy = Spy(monkeypatch)
    outcome = run_commit.commit_run(job.request())
    assert outcome == Committed(job.branch_head())
    assert not spy.called("add")


# --- 59, 60: failures and the budget -------------------------------------------------------------


def test_a_git_failure_is_a_failed_step_and_its_output_is_not_kept(tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    (job.gitdir / "index.lock").write_text("", encoding="utf-8")
    outcome = run_commit.commit_run(job.request())
    assert outcome == GitFailed("add")
    assert "index.lock" not in repr(outcome)


def timed_out(*_args, **_kwargs):
    return CompletedProcess([], 124, "", "")


def test_a_timeout_is_a_failed_step_never_an_exception(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    Spy(monkeypatch, after={"add": lambda done, *a: CompletedProcess([], 124, "", "")})
    assert run_commit.commit_run(job.request(), budget=30.0) == GitFailed("add", timed_out=True)


def test_an_exhausted_budget_fails_the_first_step(tmp_path):
    job = make_job(tmp_path)
    outcome = run_commit.commit_run(job.request(), budget=0.0)
    assert isinstance(outcome, GitFailed) and outcome.timed_out


def test_a_commit_written_before_the_timeout_is_found_by_the_last_proof(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    Spy(monkeypatch, after={"commit": lambda done, *a: CompletedProcess([], 124, "", "")})
    outcome = run_commit.commit_run(job.request(), budget=30.0)
    assert outcome == Committed(job.branch_head())


def test_a_failed_commit_with_no_commit_written_is_a_failed_step(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    Spy(monkeypatch, before={"commit": lambda cwd, args, kw: kw.update(
        extra_env={**(kw.get("extra_env") or {}), "GIT_AUTHOR_NAME": ""})})
    outcome = run_commit.commit_run(job.request())
    assert isinstance(outcome, GitFailed) and outcome.step == "commit"


# --- 61: no background maintenance ---------------------------------------------------------------


def test_git_commit_starts_no_subprocess(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    trace = tmp_path / "trace.txt"
    Spy(monkeypatch, before={"commit": lambda cwd, args, kw: kw.update(
        extra_env={**(kw.get("extra_env") or {}), "GIT_TRACE": str(trace)})})
    assert isinstance(run_commit.commit_run(job.request()), Committed)
    text = trace.read_text(encoding="utf-8", errors="replace")
    assert "built-in: git commit" in text  # the trace is really captured
    assert "run_command" not in text and "maintenance" not in text


# --- 62: identity --------------------------------------------------------------------------------


def test_the_identity_comes_from_the_global_config_and_is_pinned_for_the_commit(
    monkeypatch, tmp_path
):
    config = "[user]\n\tname = Loïc Test\n\temail = loic@example.invalid\n"
    isolate_home(monkeypatch, tmp_path / "home", config)
    job = make_job(tmp_path)
    identity = run_commit.resolve_identity(job.repo)
    assert identity == Identity("Loïc Test", "loic@example.invalid")
    job.write("new.txt")
    pinned = Identity("Pinned", "pinned@example.invalid")
    outcome = run_commit.commit_run(job.request(identity=pinned))
    assert isinstance(outcome, Committed)
    # the commit reads no global configuration: the pinned identity wins everywhere
    assert log(job, "%an|%ae|%cn|%ce") == "|".join([pinned.name, pinned.email] * 2)


def test_the_local_identity_of_the_repository_is_used(tmp_path):
    job = make_job(tmp_path)
    git(job.repo, "config", "user.name", "Local Person")
    git(job.repo, "config", "user.email", "local@example.invalid")
    found = run_commit.resolve_identity(job.repo)
    assert found == Identity("Local Person", "local@example.invalid")


def test_no_identity_anywhere_is_refused_with_a_clear_message(tmp_path):
    job = make_job(tmp_path)
    with pytest.raises(ValueError, match="aucune identité git"):
        run_commit.resolve_identity(job.repo)


@pytest.mark.parametrize("config", [
    '[user]\n\tname = "two\\nlines"\n\temail = a@example.invalid\n',
    '[user]\n\tname = Someone\n\temail = "a@example.invalid\\nb"\n',
    "[user]\n\tname = Someone\n",
    "[user]\n\tname = \n\temail = a@example.invalid\n",
])
def test_an_identity_with_a_line_break_or_a_hole_is_refused(monkeypatch, tmp_path, config):
    isolate_home(monkeypatch, tmp_path / "home", config)
    job = make_job(tmp_path)
    with pytest.raises(ValueError, match="aucune identité git"):
        run_commit.resolve_identity(job.repo)


def test_a_worktree_that_is_not_one_of_the_repository_is_refused(tmp_path):
    job = make_job(tmp_path)
    other = make_repo(tmp_path / "other")
    foreign = dataclasses.replace(job.tree, path=other)
    with pytest.raises(ValueError):
        run_commit.worktree_gitdir(foreign)
    with pytest.raises(ValueError):
        run_commit.worktree_gitdir(dataclasses.replace(job.tree, path=tmp_path / "missing"))
    assert run_commit.worktree_gitdir(job.tree).parent.name == "worktrees"


# --- 66: neutrality ------------------------------------------------------------------------------


def test_the_message_is_fixed_and_a_codex_request_has_no_model_trailer(tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    outcome = run_commit.commit_run(job.request(adapter="codex", label="Codex", model=None))
    assert isinstance(outcome, Committed)
    assert log(job, "%B").strip() == (
        "nx-run-1 : travail de Codex\n\nNexus-Run: nx-run-1\nNexus-Executor: codex")


def test_the_message_of_the_first_adapter(tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    assert isinstance(run_commit.commit_run(job.request()), Committed)
    assert log(job, "%B").strip() == (
        "nx-run-1 : travail de Claude Code (sonnet)\n\nNexus-Run: nx-run-1\n"
        "Nexus-Executor: claude-code\nNexus-Model: sonnet")
    assert log(job, "%an|%ae|%cn|%ce") == f"{IDENTITY.name}|{IDENTITY.email}|" \
        f"{IDENTITY.name}|{IDENTITY.email}"


@pytest.mark.parametrize("overrides", [
    {"run_ref": "nx-run-0"}, {"run_ref": "nx-run-1\nx"}, {"run_ref": "nx-run-01"},
    {"adapter": "Codex Evil"}, {"adapter": "codex\n"}, {"label": "Co\ndex"}, {"label": ""},
    {"label": "x" * 41}, {"model": "Opus x"}, {"model": "opus\n"}, {"model": "o" * 17},
    {"identity": Identity("a\nb", "c@example.invalid")},
])
def test_an_invalid_request_is_refused_without_calling_git(monkeypatch, tmp_path, overrides):
    job = make_job(tmp_path)
    job.write("new.txt")
    spy = Spy(monkeypatch)
    assert run_commit.commit_run(job.request(**overrides)) == Refused("requête invalide")
    assert spy.calls == []


def test_run_commit_depends_on_codex_git_only():
    tree = ast.parse(Path(run_commit.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    assert not any(name.startswith("nexus.runs") for name in imported)
    assert not any("claude_code" in name for name in imported)
    assert "nexus.adapters.codex" not in imported


# --- 69: the proof, read inside the budget -------------------------------------------------------


def same_proof(job, tree) -> str | None:
    request = job.request(tree=tree)
    mine = run_commit.CommitSession(request, 60.0).proof("preuve")
    assert mine == codex_git.proof(tree)
    return mine


def test_the_proof_reads_the_same_as_codex_git(tmp_path):
    job = make_job(tmp_path)
    assert same_proof(job, dataclasses.replace(job.tree, branch="nexus/missing")) is None
    assert same_proof(job, job.tree) is None  # the branch is still at the start commit
    unrelated = git(job.repo, "commit-tree", f"{job.tree.start}^{{tree}}", "-m", "elsewhere")
    job.write("new.txt")
    git(job.tree.path, "add", "-A")
    git(job.tree.path, "commit", "-q", "-m", "work")
    assert same_proof(job, dataclasses.replace(job.tree, start=unrelated)) is None
    assert same_proof(job, job.tree) == job.branch_head()


def test_a_slow_git_never_overruns_the_budget_by_more_than_one_call(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    monkeypatch.setattr(run_commit, "CALL_TIMEOUT", 0.3)

    def slow(cwd, args, **kwargs):
        time.sleep(0.3)
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(run_commit, "run_git", slow)
    began = time.monotonic()
    outcome = run_commit.commit_run(job.request(), budget=1.0)
    assert isinstance(outcome, GitFailed) and outcome.timed_out
    assert time.monotonic() - began <= 1.0 + 0.3 + 0.5


def test_the_last_proof_shares_the_reserve_and_stops_at_the_deadline(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")
    calls = []  # (start, timeout) of git commit, then of each read of the last proof
    real = run_commit.run_git

    def slow_from_commit(cwd, args, *, timeout, **kwargs):
        if not calls and args[:1] != ["commit"]:
            return real(cwd, args, timeout=timeout, **kwargs)
        calls.append((time.monotonic(), timeout))
        time.sleep(timeout * 0.95)  # slow, yet answering: the proof goes on to its next read
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(run_commit, "run_git", slow_from_commit)
    began = time.monotonic()
    outcome = run_commit.commit_run(job.request(), budget=1.0)
    assert isinstance(outcome, GitFailed) and len(calls) >= 2
    # every read of the proof stops at the deadline: the reserve is shared, never given again
    assert all(start + timeout <= began + 1.0 + 0.02 for start, timeout in calls)


def test_the_module_survives_a_missing_git(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("new.txt")

    def boom(*_a, **_k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(run_commit.subprocess, "run", boom)
    outcome = run_commit.commit_run(job.request())
    assert isinstance(outcome, GitFailed) and not outcome.timed_out
