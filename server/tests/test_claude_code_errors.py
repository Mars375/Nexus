"""How a `claude-code` run fails (spec 2026-11-11, §5.3; tests 19 to 24): no commit on any of them,
and the isolation check fails closed."""

import time

import pytest
from claude_code_support import (
    ASSISTANT_TEXT,
    INIT_BARE,
    INIT_BYPASS,
    INIT_EXTRA_TOOL,
    INIT_MCP,
    INIT_MISSING_TOOL,
    INIT_OK,
    OK_LINES,
    RESULT_DENIALS,
    RESULT_ERROR_EXEC,
    RESULT_IS_ERROR,
    RESULT_OK,
    Rig,
    claude_info,
    init,
    write,
)

from nexus.adapters import codex_process, run_commit

CLOSERS = ("done", "review", "failed")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


@pytest.fixture
def no_commit(monkeypatch):
    calls = []
    monkeypatch.setattr(run_commit, "commit_run", lambda *a, **k: calls.append(1))
    return calls


def closing(r, timeout=20.0):
    """Watch until the run closes: a breach is read by the reader thread, then killed by a tick."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = r.watch().events
        if events and events[-1].kind in CLOSERS:
            return events[-1]
        time.sleep(0.05)
    raise AssertionError("the run never closed")


# --- 19, 20, 21: a bad end --------------------------------------------------------------------


def test_a_success_followed_by_a_bad_exit_fails_and_commits_nothing(rig, no_commit):
    r = rig(lines=OK_LINES, actions=[write()], exit=1)
    r.run()
    last = r.last()
    assert last.kind == "failed" and "code 1" in last.payload["cause"]
    assert not no_commit and r.head() == r.start()
    assert (r.worktree / "a.txt").read_text(encoding="utf-8") == "work\n"  # kept, not committed


def test_an_end_without_a_result_line_fails_and_commits_nothing(rig, no_commit):
    r = rig(lines=[INIT_OK, ASSISTANT_TEXT], actions=[write()], exit=0)
    r.run()
    last = r.last()
    assert last.kind == "failed"
    assert last.payload["cause"] == "le processus s'est arrêté sans résultat"
    assert not no_commit and r.head() == r.start()


@pytest.mark.parametrize("result, expected", [
    (RESULT_IS_ERROR, "Limite d'usage atteinte"), (RESULT_ERROR_EXEC, "boom")])
def test_a_result_in_error_fails_with_its_cause_and_commits_nothing(
        rig, no_commit, result, expected):
    r = rig(lines=[INIT_OK, ASSISTANT_TEXT, result], actions=[write()])
    r.run()
    last = r.last()
    assert last.kind == "failed" and last.payload["cause"] == expected
    assert not no_commit and r.head() == r.start()


def test_the_last_result_line_decides(rig, no_commit):
    r = rig(lines=[INIT_OK, RESULT_OK, RESULT_IS_ERROR], actions=[write()])
    r.run()
    assert r.last().kind == "failed" and not no_commit


def test_a_bad_exit_after_an_error_result_keeps_the_error_as_the_cause(rig):
    r = rig(lines=[INIT_OK, RESULT_IS_ERROR], exit=1)
    r.run()
    assert r.last().payload["cause"] == "Limite d'usage atteinte"


def test_refused_tools_are_told_and_a_run_without_change_ends_in_review(rig):
    r = rig(lines=[INIT_OK, RESULT_DENIALS])
    r.run()
    events = r.watch().events
    assert [e.body for e in events if e.subject == "Outils refusés"] == ["Bash"]
    assert events[-1].kind == "review"


# --- 22: a departure from the isolation -------------------------------------------------------


@pytest.mark.parametrize("bad", [INIT_MCP, INIT_EXTRA_TOOL, INIT_MISSING_TOOL, INIT_BYPASS])
def test_a_breach_kills_the_tree_at_once_without_waiting_for_the_maximum(rig, no_commit, bad):
    r = rig(lines=[bad, ASSISTANT_TEXT], actions=[write()], hang=True)
    r.adapter.dispatch(claude_info())
    job = r.adapter._job("nx-run-1")

    last = closing(r)

    assert last.kind == "failed" and last.payload["cause"].startswith("isolation non respectée")
    assert job.process.poll() is not None  # the stop is confirmed
    assert not no_commit and r.head() == r.start()
    assert "Bash" not in last.payload["cause"]
    assert [e.kind for e in r.watch().events].count("claimed") == 0


def test_nothing_read_after_a_breach_is_recorded(rig):
    r = rig(lines=[INIT_MCP, ASSISTANT_TEXT, INIT_OK, ASSISTANT_TEXT], hang=True)
    r.adapter.dispatch(claude_info())
    closing(r)
    assert [e.kind for e in r.watch().events] == ["failed"]


# --- 23: an isolation that was never proved ---------------------------------------------------


@pytest.mark.parametrize("lines", [
    [INIT_BARE],
    [init(mcp_servers="none")],
    [ASSISTANT_TEXT, INIT_OK],  # the agent spoke before the isolation was proved
])
def test_an_isolation_not_verified_kills_the_tree_and_never_ends_well(rig, no_commit, lines):
    r = rig(lines=lines, actions=[write()], hang=True)
    r.adapter.dispatch(claude_info())
    job = r.adapter._job("nx-run-1")

    last = closing(r)

    assert last.kind == "failed" and last.payload["cause"] == "isolement de la session non vérifié"
    assert job.process.poll() is not None
    assert not no_commit and r.head() == r.start()


def test_a_normal_end_without_any_conform_init_is_not_a_success(rig, no_commit):
    r = rig(lines=[RESULT_OK], actions=[write()])
    r.run()
    last = r.last()
    assert last.kind == "failed" and last.payload["cause"] == "isolement de la session non vérifié"
    assert not no_commit


def test_a_stop_that_is_not_confirmed_raises_and_leaves_the_run_open(rig, monkeypatch):
    r = rig(lines=[INIT_MCP], hang=True)
    r.adapter.dispatch(claude_info())
    real = codex_process.kill_tree
    monkeypatch.setattr(codex_process, "kill_tree", lambda *a, **k: False)
    time.sleep(0.5)  # the reader has read the init line

    with pytest.raises(RuntimeError, match="non confirmé"):
        r.watch()
    with pytest.raises(RuntimeError):
        r.watch()  # tried again, never sealed
    assert r.adapter._job("nx-run-1").settled is False

    monkeypatch.setattr(codex_process, "kill_tree", real)
    assert closing(r).kind == "failed"


# --- 24: the maximum duration -----------------------------------------------------------------


def test_the_maximum_duration_kills_the_tree_and_commits_nothing(rig, no_commit):
    r = rig(lines=OK_LINES[:-1], actions=[write()], hang=True)
    r.adapter.max_seconds = 0.5
    r.adapter.dispatch(claude_info())
    job = r.adapter._job("nx-run-1")

    last = closing(r)

    assert last.kind == "failed" and last.subject == "Durée maximale dépassée"
    assert last.payload["cause"] == "durée maximale dépassée : processus arrêté"
    assert job.process.poll() is not None
    assert not no_commit and r.head() == r.start()
    assert not r.settings_file.exists()


# --- the settings file goes away whatever the end ---------------------------------------------


@pytest.mark.parametrize("scenario", [
    {"lines": OK_LINES, "exit": 1}, {"lines": [INIT_MCP], "hang": True},
    {"lines": [INIT_OK, RESULT_IS_ERROR]}])
def test_the_settings_file_is_removed_after_a_failure(rig, scenario):
    r = rig(**scenario)
    r.adapter.dispatch(claude_info())
    assert closing(r).kind == "failed"
    assert not r.settings_file.exists()
