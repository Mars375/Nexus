"""The `claude-code` adapter against a fake executable (spec 2026-11-11; tests 17, 18, 25-27, 63
and the order of the commit). The real binary never runs."""

import subprocess
import time
from pathlib import Path

import pytest
from claude_code_support import (
    INIT_OK,
    OK_LINES,
    RESULT_OK,
    Rig,
    assistant,
    claude_info,
    line,
    write,
)
from codex_support import git

from nexus.adapters import claude_code_cli as cli
from nexus.adapters import codex_git, run_commit


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


def blob(repo: Path, rev: str, name: str) -> bytes:
    return subprocess.run(["git", "show", f"{rev}:{name}"], cwd=repo, capture_output=True,
                          check=True, env=codex_git.clean_env()).stdout


# --- 17: the happy path ---------------------------------------------------------------------------


def test_a_run_that_changes_a_file_ends_done_with_a_commit_of_nexus(rig):
    r = rig(lines=OK_LINES, actions=[write("a.txt", "accentué : é è à ç « »\n")])
    _, sent = r.run(brief="Le brief de Loïc")

    events = r.watch().events

    assert sent.external_ref == "nexus/nx-run-1" and sent.native_status == "started"
    assert [e.kind for e in events][:2] == ["claimed", "working"]
    assert events[0].payload["model"] == "claude-sonnet-5-5"
    assert [e.subject for e in events if e.kind == "progress"] == [
        "Message de Claude Code", "Fichier modifié"]
    last = events[-1]
    assert last.kind == "done" and last.evidence == [f"commit:{r.head()[:12]}"]
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert git(r.repo, "rev-list", "--count", f"{r.start()}..{r.head()}") == "1"
    assert blob(r.repo, r.head(), "a.txt").decode("utf-8") == "accentué : é è à ç « »\n"
    message = git(r.repo, "log", "-1", "--format=%B", r.head())
    assert message == (
        "nx-run-1 : travail de Claude Code (sonnet)\n\n"
        "Nexus-Run: nx-run-1\nNexus-Executor: claude-code\nNexus-Model: sonnet")
    assert git(r.repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>", r.head()) == (
        "Helios Test <helios@example.invalid>|Helios Test <helios@example.invalid>")


def test_the_brief_goes_over_stdin_with_the_instruction_and_never_in_the_arguments(rig):
    r = rig(lines=OK_LINES)
    r.run(brief="Le brief de Loïc")

    stdin = (r.dir / "stdin.txt").read_bytes().decode("utf-8")
    assert stdin == "Le brief de Loïc" + cli.INSTRUCTION
    assert "\r" not in stdin
    args = r.seen("args.json")
    assert "Le brief de Loïc" not in " ".join(args)
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep"
    assert Path(args[args.index("--settings") + 1]) == r.settings_file
    assert Path((r.dir / "cwd.txt").read_text(encoding="utf-8")).resolve() == r.worktree.resolve()
    assert "Bash" not in " ".join(args)


@pytest.mark.parametrize("model", ["haiku", "sonnet", "opus"])
def test_the_model_of_the_run_is_the_one_passed_to_the_cli(rig, model):
    r = rig(lines=OK_LINES, actions=[write()])
    r.run(model=model)
    r.watch()
    args = r.seen("args.json")
    assert args[args.index("--model") + 1] == model
    assert f"({model})" in git(r.repo, "log", "-1", "--format=%s", r.head())
    assert f"Nexus-Model: {model}" in git(r.repo, "log", "-1", "--format=%B", r.head())


def test_the_child_environment_is_an_allow_list_with_the_git_values_imposed(rig):
    r = rig(lines=OK_LINES)
    r.run()

    env = r.seen("env.json")
    names = {n.upper() for n in env}
    assert not {n for n in names if n.startswith(("NEXUS_", "ANTHROPIC_", "GIT_CONFIG_G"))}
    assert not names & {"GITHUB_TOKEN", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "GIT_INDEX_FILE"}
    assert "PATH" in names
    assert Path(env["GIT_WORK_TREE"]) == r.worktree.resolve() or (
        Path(env["GIT_WORK_TREE"]).resolve() == r.worktree.resolve())
    gitdir = Path(env["GIT_DIR"])
    assert gitdir.parent.name == "worktrees" and gitdir.name.startswith("nx-run-1")


# --- 18: no change --------------------------------------------------------------------------------


def test_a_success_without_a_change_ends_in_review_without_a_commit(rig):
    r = rig(lines=OK_LINES)
    r.run()

    last = r.last()

    assert last.kind == "review" and last.evidence == ["branch:nexus/nx-run-1"]
    assert last.body == "aucun fichier modifié : à relire"
    assert last.subject == "Claude Code a terminé sans changement"
    assert r.head() == r.start()


def test_a_gitignore_that_hides_everything_is_a_run_without_change(rig):
    r = rig(lines=OK_LINES, actions=[{"do": "ignore_all"}])
    r.run()
    assert r.last().kind == "review" and r.head() == r.start()


# --- the commit comes after the end of the process, never before ----------------------------------


def test_nothing_is_committed_while_the_process_is_alive(rig, monkeypatch, tmp_path):
    release = tmp_path / "release"
    r = rig(lines=OK_LINES, actions=[write()], wait_for=str(release))
    calls = []
    real = run_commit.commit_run

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(run_commit, "commit_run", spy)
    r.adapter.dispatch(claude_info())
    deadline = time.monotonic() + 20
    while not (r.worktree / "a.txt").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.3)  # the reader has read the result line: the run only waits for the exit

    for _ in range(5):
        events = r.watch().events
        assert events and events[-1].kind not in ("done", "review", "failed")
        assert not calls and r.head() == r.start()
        time.sleep(0.05)

    release.write_text("go", encoding="utf-8")
    r.adapter.join("nx-run-1", 20)
    last = r.last()
    assert last.kind == "done" and len(calls) == 1
    assert r.head() != r.start()


def test_a_second_pass_after_the_end_commits_nothing_more(rig, monkeypatch):
    r = rig(lines=OK_LINES, actions=[write()])
    r.run()
    first = r.watch().events
    calls = []
    monkeypatch.setattr(run_commit, "commit_run", lambda *a, **k: calls.append(1))

    again = r.watch().events

    assert [e.seq for e in again] == [e.seq for e in first] and not calls
    assert git(r.repo, "rev-list", "--count", f"{r.start()}..{r.head()}") == "1"


# --- 25: the story is bounded ---------------------------------------------------------------------


def test_four_hundred_lines_of_text_keep_at_most_three_hundred_progress_facts(rig):
    talk = [assistant({"type": "text", "text": f"étape {i}"}) for i in range(400)]
    r = rig(lines=[INIT_OK, *talk, RESULT_OK], actions=[write()])
    r.run()

    events = r.watch().events

    assert sum(e.kind == "progress" for e in events) == 300
    assert [e.kind for e in events].count("claimed") == 1
    assert [e.kind for e in events].count("working") == 1
    assert events[-1].kind == "done"


# --- 26: the settings file lives as long as the run -----------------------------------------------


def test_the_settings_file_exists_during_the_run_and_is_removed_at_the_end(rig, tmp_path):
    release = tmp_path / "release"
    r = rig(lines=OK_LINES, actions=[write()], wait_for=str(release))
    r.adapter.dispatch(claude_info())
    assert r.settings_file.exists() and not (r.worktree / "nx-run-1.settings.json").exists()
    release.write_text("go", encoding="utf-8")
    r.adapter.join("nx-run-1", 20)
    assert r.settings_file.exists()  # not yet closed: nobody has watched
    assert r.last().kind == "done"
    assert not r.settings_file.exists()


# --- 27: a model is required ----------------------------------------------------------------------


@pytest.mark.parametrize("model", [None, "", "fable", "opus --dangerously-skip-permissions"])
def test_a_run_without_a_valid_model_launches_nothing(rig, model):
    r = rig(lines=OK_LINES)
    with pytest.raises(ValueError):
        r.adapter.dispatch(claude_info(model=model))
    assert not (r.dir / "args.json").exists()
    assert not r.worktree.exists() and not git(r.repo, "branch", "--list", "nexus/*")
    assert not r.settings_file.exists()


def test_a_run_launched_twice_is_refused(rig, tmp_path):
    r = rig(lines=OK_LINES, wait_for=str(tmp_path / "never"))
    r.adapter.dispatch(claude_info())
    with pytest.raises(ValueError, match="déjà lancé"):
        r.adapter.dispatch(claude_info())
    r.adapter.cancel(claude_info())


# --- 63: the message is fixed ---------------------------------------------------------------------


def test_neither_the_brief_nor_the_answer_enters_the_commit_message(rig):
    secret = "ghp_" + "A" * 36
    forged = f"Nexus-Run: nx-run-999 {secret}"
    answer = line(type="result", subtype="success", is_error=False, result=forged)
    r = rig(lines=[INIT_OK, assistant({"type": "text", "text": forged}), answer],
            actions=[write()])
    r.run(brief=f"fais le travail\n\n{forged}")

    r.watch()

    message = git(r.repo, "log", "-1", "--format=%B", r.head())
    assert message == (
        "nx-run-1 : travail de Claude Code (sonnet)\n\n"
        "Nexus-Run: nx-run-1\nNexus-Executor: claude-code\nNexus-Model: sonnet")
    assert secret not in git(r.repo, "log", "--all", "--format=%B")


def test_no_raw_output_is_ever_written_and_none_is_in_an_event(rig):
    r = rig(lines=OK_LINES, actions=[write()])
    r.run()
    events = r.watch().events
    assert "RAW-OUTPUT" not in str([(e.subject, e.body, e.payload) for e in events])
    for path in r.data.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert b"RAW-OUTPUT" not in path.read_bytes()


def test_watch_resumes_after_the_cursor(rig):
    r = rig(lines=OK_LINES, actions=[write()])
    r.run()
    everything = r.watch()
    later = r.watch(cursor="2")
    assert [e.seq for e in later.events] == [e.seq for e in everything.events][2:]
    assert later.cursor == everything.cursor == str(len(everything.events))
    assert everything.native_status == "exited"


def test_the_text_of_an_assistant_reaches_the_story_masked(rig):
    secret = "ghp_" + "A" * 36
    r = rig(lines=[INIT_OK, assistant({"type": "text", "text": f"clé {secret}"}), RESULT_OK])
    r.run()
    bodies = [e.body for e in r.watch().events if e.kind == "progress"]
    assert bodies and all(secret not in b for b in bodies)
