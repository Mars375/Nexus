"""Fixes from the Antigravity review of #181: empty progress, a commit that is not a hash, and a
child whose input pipe failed (the call must not pass for a confirmed stop)."""

import subprocess
from datetime import UTC, datetime

import pytest
from hermes_support import T0, event, run_row, show_payload

from nexus.adapters import hermes_cli
from nexus.adapters.hermes_translate import translate

NOW = datetime.fromtimestamp(T0 + 60, UTC)


def _facts(*events, runs=None):
    show = show_payload("running", events=list(events), runs=runs or [])
    return translate(show, 0, proofs=[], now=NOW, max_seconds=3600.0).events


@pytest.mark.parametrize("ev", [
    event("review_requested", T0 + 3),
    event("changes_requested", T0 + 3),
    event("completion_blocked_empty_result", T0 + 3),
    event("timed_out", T0 + 3, {"pid": 4, "elapsed_seconds": 9, "limit_seconds": 5}),
    event("crashed", T0 + 3, {"pid": 4}),
])
def test_every_progress_fact_describes_itself(ev):
    """The event protocol refuses a progress without a body (`progress_empty`): the cursor would
    never move and the same refusal would come back every tick."""
    facts = _facts(event("spawned", T0 + 1), event("spawned", T0 + 2), ev)

    progress = [f for f in facts if f.kind == "progress"]
    assert len(progress) == 2  # the second spawn, then the event under test
    assert all(f.body and f.body.strip() for f in progress)


def _completion_payload(commit):
    runs = [run_row(1, "completed", "fini", metadata={"commit": commit})]
    facts = _facts(event("completed", T0 + 5, {"summary": "fini"}, 1), runs=runs)
    return facts[-1].payload


def test_a_secret_given_as_commit_never_reaches_the_payload():
    payload = _completion_payload("ghp_" + "A" * 36)

    assert "commit" not in payload
    assert "ghp_" not in repr(payload)


def test_a_real_commit_hash_is_kept_short():
    assert _completion_payload("0123456789abcdef" * 2 + "01234567")["commit"] == "0123456789ab"


class _BrokenPipe:
    """A child whose input pipe broke: `communicate` raises before any wait."""

    def __init__(self, alive: bool):
        self.alive, self.returncode = alive, None

    def communicate(self, *_a, **_k):
        if self.returncode is None and self.alive:
            raise OSError("broken pipe")
        return b"", b""

    def poll(self):
        return None if self.alive else self.returncode


def test_a_broken_input_pipe_is_not_a_confirmed_stop(monkeypatch):
    child = _BrokenPipe(alive=True)
    monkeypatch.setattr(hermes_cli.codex_process, "spawn", lambda *a, **k: child)
    killed = []

    def kill(process):
        killed.append(process)
        process.alive, process.returncode = False, 1
        return True

    monkeypatch.setattr(hermes_cli.codex_process, "kill_tree", kill)

    result = hermes_cli.call("hermes", ["create"], stdin="brief", cwd=".")

    assert killed == [child]
    assert result.code == 1 and not result.timed_out


def test_a_broken_pipe_on_a_child_that_cannot_be_stopped_is_unconfirmed(monkeypatch):
    child = _BrokenPipe(alive=True)
    monkeypatch.setattr(hermes_cli.codex_process, "spawn", lambda *a, **k: child)
    monkeypatch.setattr(hermes_cli.codex_process, "kill_tree", lambda p: False)

    result = hermes_cli.call("hermes", ["create"], stdin="brief", cwd=".")

    assert result.timed_out and not result.stopped


# --- CodeRabbit, round 1 on adce21a --------------------------------------------------------------

from hermes_support import (  # noqa: E402
    TASK_ID,
    make_fake_hermes,
    reply,
    run_info,
    set_scenario,
    subcommands,
)

from nexus.adapters.base import Dispatched, LaunchUncertain  # noqa: E402
from nexus.adapters.hermes import HermesAdapter  # noqa: E402
from nexus.adapters.hermes_cli import HermesRefused  # noqa: E402

TITLE = "Nexus nx-run-1 nx-task-1"


@pytest.fixture
def rig(tmp_path):
    binary = make_fake_hermes(tmp_path / "fake")
    (tmp_path / "data").mkdir()
    return HermesAdapter(str(binary), "default", tmp_path / "data"), binary


def _listed(title=TITLE, by="nexus", status="ready"):
    return {"id": TASK_ID, "title": title, "created_by": by, "status": status}


def test_two_refusals_after_a_task_was_written_find_that_task(rig):
    """Hermes inserts the row before printing it: a crash after the insert is a refusal that
    nevertheless created the task. It is found by its title and followed, never orphaned."""
    adapter, binary = rig
    set_scenario(binary.parent, create=[reply(exit=1, stderr="boom")], list=[reply([_listed()])])

    assert adapter.dispatch(run_info()) == Dispatched(external_ref=TASK_ID, native_status="ready")
    assert subcommands(binary) == ["create", "create", "list"]


def test_two_refusals_with_an_unreadable_list_stay_uncertain(rig):
    adapter, binary = rig
    set_scenario(binary.parent, create=[reply(exit=1)], list=[reply(exit=1, stderr="locked")])
    with pytest.raises(LaunchUncertain):
        adapter.dispatch(run_info())


def test_two_refusals_and_no_such_task_are_a_refusal(rig):
    adapter, binary = rig
    others = [_listed(title="Nexus nx-run-2 nx-task-1"), _listed(by="user")]
    set_scenario(binary.parent, create=[reply(exit=1)], list=[reply(others)])
    with pytest.raises(HermesRefused):
        adapter.dispatch(run_info())


def _archived_without_termination(runs):
    show = show_payload("archived", events=[event("archived", T0 + 9)], runs=runs)
    return show


def test_archived_without_termination_while_a_run_is_open_is_not_confirmed(rig):
    """Hermes writes `archived`, then stops the worker in another transaction: until the
    termination is written, an open run means the worker may still be alive."""
    adapter, binary = rig
    open_run = run_row(1) | {"worker_pid": 77, "ended_at": None}
    set_scenario(binary.parent, archive=[reply("")],
                 show=[reply(_archived_without_termination([open_run]))])
    with pytest.raises(RuntimeError):
        adapter.cancel(run_info(external_ref=TASK_ID))


def test_archived_without_termination_and_no_open_run_is_confirmed(rig):
    adapter, binary = rig
    ended = run_row(1, "completed") | {"worker_pid": 77, "ended_at": T0 + 8}
    for runs in ([], [ended]):
        set_scenario(binary.parent, archive=[reply("")],
                     show=[reply(_archived_without_termination(runs))])
        adapter.cancel(run_info(external_ref=TASK_ID))


def test_an_out_of_range_timestamp_is_a_malformed_event_not_a_stuck_cursor():
    show = show_payload("running", events=[event("spawned", 10**100), event("spawned", T0 + 2)])

    t = translate(show, 0, proofs=[], now=NOW, max_seconds=3600.0)

    assert t.cursor == "2" and [e.seq for e in t.events] == [2]


class _Lingering:
    """The CLI died but a descendant keeps the pipe open: the second read times out too."""

    returncode = None

    def communicate(self, *_a, timeout=None, **_k):
        raise subprocess.TimeoutExpired("hermes", timeout)

    def poll(self):
        return None


def test_a_pipe_still_held_after_the_kill_is_an_unconfirmed_stop(monkeypatch):
    monkeypatch.setattr(hermes_cli.codex_process, "spawn", lambda *a, **k: _Lingering())
    monkeypatch.setattr(hermes_cli.codex_process, "kill_tree", lambda p: True)

    result = hermes_cli.call("hermes", ["create"], stdin="brief", cwd=".", timeout=0.01)

    assert result.timed_out and not result.stopped

