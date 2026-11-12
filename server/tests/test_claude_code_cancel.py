"""Cancelling, closing and restarting with `claude-code` (spec 2026-11-11, §5.4, §7; tests 30 to 32
and 65). A cancel or a restart never leaves a commit of Nexus behind."""

import pytest
from claude_code_support import OK_LINES, Rig, claude_info, settings_for, write
from codex_support import git
from conftest import ActorClient, tailscale_json
from runs_support import code_of, dispatch, make_task, tick

from nexus.adapters import claude_code, run_commit
from nexus.app import create_app


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


@pytest.fixture
def commits(monkeypatch):
    calls = []
    real = run_commit.commit_run

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(run_commit, "commit_run", spy)
    return calls


# --- 30: cancel ---------------------------------------------------------------------------------


def test_cancel_kills_the_tree_and_commits_nothing(rig, commits):
    r = rig(lines=OK_LINES[:-1], actions=[write()], hang=True)
    r.adapter.keep_finished = 0
    r.adapter.dispatch(claude_info())
    job = r.adapter._job("nx-run-1")

    r.adapter.cancel(claude_info(external_ref="nexus/nx-run-1"))

    assert job.process.poll() is not None
    assert job.settled and r.adapter._job("nx-run-1") is None  # purgeable, and purged
    assert not commits and r.head() == r.start()
    assert (r.worktree / "a.txt").exists() and not r.settings_file.exists()
    assert r.watch().events == ()


def test_a_cancel_that_cannot_confirm_the_stop_raises_and_keeps_the_run(rig, monkeypatch):
    from nexus.adapters import codex_process

    r = rig(lines=OK_LINES[:-1], hang=True)
    r.adapter.dispatch(claude_info())
    real = codex_process.kill_tree
    monkeypatch.setattr(codex_process, "kill_tree", lambda *a, **k: False)

    with pytest.raises(RuntimeError, match="non confirmé"):
        r.adapter.cancel(claude_info(external_ref="nexus/nx-run-1"))
    assert r.adapter._job("nx-run-1").settled is False

    monkeypatch.setattr(codex_process, "kill_tree", real)
    r.adapter.cancel(claude_info(external_ref="nexus/nx-run-1"))


# --- 31: after a restart --------------------------------------------------------------------------


def test_after_a_restart_nothing_is_known_and_nothing_is_committed(rig, commits):
    r = rig(lines=OK_LINES, actions=[write()])
    fresh = claude_code.ClaudeCodeAdapter(str(r.bin), [r.repo], r.data)

    assert fresh.watch(claude_info(external_ref="nexus/nx-run-1")).events == ()
    assert fresh.recover(claude_info(external_ref="nexus/nx-run-1")) is None
    assert not commits

    fresh.cancel(claude_info())  # never launched: nothing to stop
    marker = r.data / "worktrees" / ".stopped" / "nx-run-1"
    with pytest.raises(RuntimeError, match="inconnu"):
        fresh.cancel(claude_info(external_ref="nexus/nx-run-1"))  # launched, no marker
    marker.parent.mkdir(parents=True)
    marker.touch()
    fresh.cancel(claude_info(external_ref="nexus/nx-run-1"))  # stopped at a clean shutdown


# --- 32: shutdown ---------------------------------------------------------------------------------


def test_close_kills_the_process_and_notes_it(rig, commits):
    r = rig(lines=OK_LINES[:-1], actions=[write()], hang=True)
    r.adapter.dispatch(claude_info())
    job = r.adapter._job("nx-run-1")

    r.adapter.close()

    assert job.process.poll() is not None
    assert (r.data / "worktrees" / ".stopped" / "nx-run-1").exists()
    after = claude_code.ClaudeCodeAdapter(str(r.bin), [r.repo], r.data)
    after.cancel(claude_info(external_ref="nexus/nx-run-1"))  # the stop is known and confirmed
    assert not commits and r.head() == r.start()


# --- 65: cancel against commit, through the real supervisor --------------------------------------


def client_for(r):
    app = create_app(settings_for(r), nodes_runner=tailscale_json)
    return ActorClient(app)


def hand_over(client, r):
    task = make_task(client)
    res = dispatch(client, task, executor="claude", agent="claude", model="sonnet",
                   workdir=str(r.repo))
    assert res.status_code == 201, res.text
    return task


def test_a_cancel_asked_before_the_turn_that_sees_the_end_wins(rig, tmp_path, commits):
    release = tmp_path / "release"
    r = rig(lines=OK_LINES, actions=[write()], wait_for=str(release))
    with client_for(r) as client:
        hand_over(client, r)
        tick(client)  # launches
        release.write_text("go", encoding="utf-8")
        client.app.state.adapters.get("claude").join("nx-run-1", 20)  # the process has ended
        assert client.post("/api/runs/nx-run-1/cancel").status_code == 200

        tick(client)  # the cancel is handled before the follow-up: no commit

        run = client.get("/api/runs/nx-run-1").json()
        assert run["status"] == "cancelled"
        assert not commits and r.head() == r.start()


def test_a_cancel_asked_after_the_run_closed_changes_nothing(rig, tmp_path, commits):
    release = tmp_path / "release"
    r = rig(lines=OK_LINES, actions=[write()], wait_for=str(release))
    with client_for(r) as client:
        hand_over(client, r)
        tick(client)
        release.write_text("go", encoding="utf-8")
        client.app.state.adapters.get("claude").join("nx-run-1", 20)
        tick(client)  # sees the end, commits, closes
        assert client.get("/api/runs/nx-run-1").json()["status"] == "done"
        head = r.head()

        refused = client.post("/api/runs/nx-run-1/cancel")

        assert refused.status_code == 409 and code_of(refused) == "run_not_cancellable"
        tick(client)
        assert client.get("/api/runs/nx-run-1").json()["status"] == "done"
        assert r.head() == head and len(commits) == 1
        assert git(r.repo, "rev-list", "--count", f"{r.start()}..{head}") == "1"
