"""The confirmed stop of a run's process group under POSIX (spec 2026-11-13, §4.3; test B9).

POSIX only: skipped under Windows, so these tests first run in the Linux CI. The grandchild stays in
the group of the run (no setsid); one that leaves the group is a known limit (§4.3), untested here.
"""

import json
import sys

import pytest
from process_support import LAUNCH, alive, beating, detach_spec, grandchild_pid, stopped, wait_until

from nexus.adapters import codex_process

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process group")

PARENT = LAUNCH + '''
import json, sys, time
scenario = json.loads(open(sys.argv[1], encoding="utf-8").read())
if scenario.get("detach"):
    launch_detached(scenario["detach"])
if scenario.get("hang"):
    while True:
        time.sleep(0.05)
'''


def start(tmp_path, **scenario):
    script = tmp_path / "parent.py"
    script.write_text(PARENT, encoding="utf-8")
    (tmp_path / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    return codex_process.spawn([sys.executable, str(script), str(tmp_path / "scenario.json")],
                               str(tmp_path), codex_process.child_env(), contain=True)


def test_a_grandchild_in_the_group_is_stopped_with_the_tree(tmp_path):
    spec = detach_spec(tmp_path / "gc")
    process = start(tmp_path, detach=spec)
    pid = grandchild_pid(spec)
    beating(spec)
    wait_until(lambda: codex_process.exited(process), "the parent is gone")  # not reaped (6a)

    assert codex_process.kill_tree(process) is True
    assert stopped(spec, 2.0)
    wait_until(lambda: not alive(pid), "the grandchild is gone", timeout=5.0)


def test_kill_tree_waits_for_the_group_to_be_empty(tmp_path, monkeypatch):
    process = start(tmp_path, hang=True)
    answers = [True, True, False]
    asked = []

    def group_alive(pgid):
        asked.append(pgid)
        return answers.pop(0) if answers else False

    monkeypatch.setattr(codex_process, "_group_alive", group_alive)

    assert codex_process.kill_tree(process) is True
    assert asked == [process.pid] * 3


def test_a_group_that_does_not_empty_in_time_is_an_unconfirmed_stop(tmp_path, monkeypatch):
    process = start(tmp_path, hang=True)
    monkeypatch.setattr(codex_process, "_group_alive", lambda pgid: True)

    assert codex_process.kill_tree(process, timeout=0.3) is False

    monkeypatch.undo()
    assert codex_process.kill_tree(process) is True


def test_a_leader_reaped_without_the_stop_is_never_signalled(tmp_path):
    """Its id may be taken by another group once its own was empty: once the leader is reaped
    without the stop, Nexus only reads the group, and an answer is an unconfirmed stop."""
    import os
    import signal

    spec = detach_spec(tmp_path / "gc")
    process = start(tmp_path, detach=spec)
    pid = grandchild_pid(spec)
    try:
        process.wait(10)  # reaped by someone else than `kill_tree`, its group not signalled

        assert codex_process.kill_tree(process, timeout=0.5) is False
        assert alive(pid)  # never signalled
    finally:
        os.kill(pid, signal.SIGKILL)
