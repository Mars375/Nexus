"""The Codex adapter against a fake executable (ADR-023, lot C). The real binary never runs."""

import json
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

from nexus.adapters.codex import CodexAdapter


class Rig:
    def __init__(self, tmp_path: Path, monkeypatch, **scenario):
        self.dir = tmp_path / "fake"
        self.bin = make_fake_codex(self.dir, **scenario)
        self.repo = make_repo(tmp_path / "repo")
        self.data = tmp_path / "data"
        self.adapter = CodexAdapter(str(self.bin), [self.repo], self.data)
        monkeypatch.setenv("NEXUS_TOKEN", "nxt_must-not-leak")
        monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
        monkeypatch.setenv("GITHUB_TOKEN", "must-not-leak")

    def run(self, n=1, **kwargs):
        info = run_info(n, **kwargs)
        sent = self.adapter.dispatch(info)
        self.adapter.join(info.ref, 20)
        return info, sent

    def seen(self, name):
        return json.loads((self.dir / name).read_text(encoding="utf-8"))


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


def test_probe_only_asks_for_the_version(rig, tmp_path):
    assert rig(lines=[]).adapter.probe() is True
    assert CodexAdapter(str(tmp_path / "missing"), [], tmp_path).probe() is False


def test_dispatch_creates_a_worktree_and_a_branch_and_hands_the_brief_over_stdin(rig):
    r = rig(lines=OK_LINES, commit=True)

    info, sent = r.run(brief="Le brief de Loïc")

    worktree = r.data / "worktrees" / "nx-run-1"
    assert worktree.is_dir()
    assert git(r.repo, "branch", "--list", "nexus/nx-run-1")
    assert (r.dir / "stdin.txt").read_text(encoding="utf-8") == "Le brief de Loïc"
    args = r.seen("args.json")
    assert "Le brief de Loïc" not in " ".join(args)
    assert args[:2] == ["exec", "--json"]
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert Path(args[args.index("--cd") + 1]) == worktree
    assert args[-1] == "-"
    assert not any("bypass" in a or "danger" in a for a in args)
    assert sent.external_ref


def test_the_child_environment_is_an_allow_list(rig):
    r = rig(lines=OK_LINES)

    r.run()

    names = {n.upper() for n in r.seen("env.json")}
    assert not {n for n in names if n.startswith("NEXUS_")}
    assert not names & {"OPENAI_API_KEY", "GITHUB_TOKEN"}
    assert "PATH" in names


def test_a_turn_with_a_commit_after_the_start_ends_done_with_the_commit_as_proof(rig):
    r = rig(lines=OK_LINES, commit=True)
    info, _ = r.run()

    result = r.adapter.watch(run_info(1, external_ref="x"))

    kinds = [e.kind for e in result.events]
    assert kinds[:2] == ["claimed", "working"] and kinds[-1] == "done"
    head = git(r.data / "worktrees" / "nx-run-1", "rev-parse", "HEAD")
    assert result.events[-1].evidence == [f"commit:{head[:12]}"]
    assert [e.seq for e in result.events] == list(range(1, len(result.events) + 1))
    assert result.cursor == str(len(result.events))


def test_without_a_new_commit_the_run_ends_in_review(rig):
    r = rig(lines=OK_LINES, commit=False)
    r.run()

    last = r.adapter.watch(run_info(1, external_ref="x")).events[-1]

    assert last.kind == "review" and last.evidence == ["branch:nexus/nx-run-1"]


def test_a_failed_turn_or_a_bad_exit_ends_failed(rig):
    r = rig(lines=[THREAD, TURN, FAILED], exit=1)
    r.run()
    last = r.adapter.watch(run_info(1, external_ref="x")).events[-1]
    assert last.kind == "failed" and "le modèle a échoué" in last.payload["cause"]


def test_a_crash_ends_failed_with_a_cause(rig):
    r = rig(lines=[THREAD], exit=3)
    r.run()

    last = r.adapter.watch(run_info(1, external_ref="x")).events[-1]

    assert last.kind == "failed" and "code 3" in last.payload["cause"]


def test_a_clean_exit_without_a_finished_turn_is_not_a_success(rig):
    r = rig(lines=[THREAD, TURN], exit=0, commit=True)
    r.run()

    assert r.adapter.watch(run_info(1, external_ref="x")).events[-1].kind == "failed"


def test_watch_resumes_after_the_cursor(rig):
    r = rig(lines=OK_LINES, commit=True)
    r.run()
    everything = r.adapter.watch(run_info(1, external_ref="x"))

    later = r.adapter.watch(run_info(1, external_ref="x", cursor="3"))

    assert [e.seq for e in later.events] == [e.seq for e in everything.events][3:]


def test_no_raw_output_is_ever_written(rig):
    r = rig(lines=OK_LINES, commit=True)
    r.run()
    r.adapter.watch(run_info(1, external_ref="x"))

    for folder in (r.data, r.repo):
        for path in folder.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                assert "RAW-OUTPUT-NEVER-STORED" not in path.read_text("utf-8", "ignore")


def test_the_work_directory_must_be_a_configured_repository(rig, tmp_path):
    r = rig(lines=OK_LINES)
    outside = make_repo(tmp_path / "other")

    with pytest.raises(ValueError):
        r.adapter.dispatch(run_info(1, workdir=str(outside)))
    r.adapter.dispatch(run_info(2, workdir=str(r.repo)))  # the configured one is fine
    r.adapter.join("nx-run-2", 20)


def test_several_repositories_need_an_explicit_choice(rig, tmp_path):
    r = rig(lines=OK_LINES)
    second = make_repo(tmp_path / "second")
    adapter = CodexAdapter(str(r.bin), [r.repo, second], r.data)

    with pytest.raises(ValueError):
        adapter.dispatch(run_info(1))


def test_the_repository_the_server_runs_from_is_refused(rig):
    r = rig(lines=OK_LINES)
    server_repo = Path(__file__).resolve().parents[2]
    adapter = CodexAdapter(str(r.bin), [server_repo], r.data)

    with pytest.raises(ValueError):
        adapter.dispatch(run_info(1, workdir=str(server_repo)))


def test_the_maximum_duration_kills_the_process_and_fails_the_run(rig, tmp_path, monkeypatch):
    r = rig(lines=[THREAD, TURN], hang=True)
    adapter = CodexAdapter(str(r.bin), [r.repo], r.data, max_seconds=0)
    adapter.dispatch(run_info(1))

    last = adapter.watch(run_info(1, external_ref="x")).events[-1]

    assert last.kind == "failed" and "durée maximale" in last.payload["cause"]
    assert adapter.is_finished("nx-run-1")


def test_cancel_kills_the_process_tree(rig):
    r = rig(lines=[THREAD, TURN], hang=True)
    info = run_info(1)
    r.adapter.dispatch(info)
    assert not r.adapter.is_finished(info.ref)

    r.adapter.cancel(info)

    assert r.adapter.is_finished(info.ref)


def test_cancelling_a_run_never_launched_stops_nothing_and_does_not_raise(rig):
    rig(lines=[]).adapter.cancel(run_info(9))
