"""Codex `error` lines are signals, not verdicts (#176, seen on the first real run).

codex-cli prints `{"type": "error", "message": "Reconnecting... 1/5 ..."}` while it retries.
Only `turn.failed` (or a bad exit) decides a failure, and its message is the cause shown.
"""

import json

from codex_support import DONE, THREAD, TURN, make_fake_codex, make_repo, run_info

from nexus.adapters.codex import CodexAdapter
from nexus.adapters.codex_translate import translate_line


def _error(message: str) -> str:
    return json.dumps({"type": "error", "message": message})


RECONNECT = _error("Reconnecting... 1/5 (stream disconnected before completion)")
QUOTA = "You've hit your usage limit. Try again at Nov 13th, 2026 7:49 PM."
QUOTA_FAILED = json.dumps({"type": "turn.failed", "error": {"message": QUOTA}})


def _last(tmp_path, lines, **scenario):
    binary = make_fake_codex(tmp_path / "fake", lines=lines, **scenario)
    adapter = CodexAdapter(str(binary), [make_repo(tmp_path / "repo")], tmp_path / "data")
    adapter.dispatch(run_info(1))
    adapter.join("nx-run-1", 20)
    return adapter.watch(run_info(1, external_ref="x")).events[-1]


def test_an_error_line_is_a_signal_not_a_failure():
    fact = translate_line(RECONNECT)

    assert fact.kind == "error" and fact.body.startswith("Reconnecting... 1/5")


def test_a_turn_that_recovers_after_a_reconnect_succeeds(tmp_path):
    last = _last(tmp_path, [THREAD, TURN, RECONNECT, DONE], exit=0, commit=True)

    assert last.kind == "done" and last.evidence[0].startswith("commit:")


def test_the_failed_turn_gives_the_cause_not_the_first_reconnect(tmp_path):
    lines = [THREAD, TURN, RECONNECT, _error("Reconnecting... 2/5"), _error(QUOTA), QUOTA_FAILED]

    last = _last(tmp_path, lines, exit=1)

    assert last.kind == "failed" and "usage limit" in last.payload["cause"]
    assert "Reconnecting" not in last.payload["cause"]


def test_a_crash_after_an_error_line_names_the_last_error(tmp_path):
    last = _last(tmp_path, [THREAD, TURN, RECONNECT, _error("boom final")], exit=2)

    assert last.kind == "failed" and last.payload["cause"] == "boom final"


def test_a_finished_turn_with_a_bad_exit_still_fails(tmp_path):
    last = _last(tmp_path, [THREAD, TURN, RECONNECT, DONE], exit=1, commit=True)

    assert last.kind == "failed" and "code 1" in last.payload["cause"]
