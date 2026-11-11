"""Fixes from the Antigravity review of #181: empty progress, a commit that is not a hash, and a
child whose input pipe failed (the call must not pass for a confirmed stop)."""

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
