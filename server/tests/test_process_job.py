"""The Windows job object around a run's process tree (spec 2026-11-13, §4.2; tests B1 to B7).

Windows only: the CI runs under Linux and skips this file, so these tests run in the local
pre-commit hook (Helios). Fakes are Python scripts written here; no real executor is ever run.
"""

import json
import subprocess
import sys
import time

import pytest
from process_support import LAUNCH, alive, beating, detach_spec, grandchild_pid, stopped, wait_until

from nexus.adapters import codex_process

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows job object")

if sys.platform == "win32":
    from nexus.adapters import process_job_win

PARENT = LAUNCH + '''
import json, subprocess, sys, time
scenario = json.loads(open(sys.argv[1], encoding="utf-8").read())
if scenario.get("detach"):
    launch_detached(scenario["detach"])
if scenario.get("breakaway"):
    try:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                 creationflags=0x01000000)  # CREATE_BREAKAWAY_FROM_JOB
        outcome = "started %d" % child.pid
    except OSError as exc:
        outcome = "winerror %s" % getattr(exc, "winerror", None)
    open(scenario["breakaway"], "w", encoding="utf-8").write(outcome)
if scenario.get("hang"):
    while True:
        time.sleep(0.05)
'''


def fake(tmp_path, **scenario):
    script = tmp_path / "parent.py"
    script.write_text(PARENT, encoding="utf-8")
    (tmp_path / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    return [sys.executable, str(script), str(tmp_path / "scenario.json")]


def start(tmp_path, **scenario):
    return codex_process.spawn(fake(tmp_path, **scenario), str(tmp_path),
                               codex_process.child_env(), contain=True)


@pytest.fixture
def active(monkeypatch):
    """Every `ActiveProcesses` value the stop read, in order."""
    seen = []
    real = process_job_win._active_processes

    def spy(job):
        seen.append(real(job))
        return seen[-1]

    monkeypatch.setattr(process_job_win, "_active_processes", spy)
    return seen


# --- B1: the detached grandchild is stopped with the tree ---------------------------------------


def test_kill_tree_stops_a_detached_grandchild_and_empties_the_job(tmp_path, active):
    spec = detach_spec(tmp_path / "gc")
    process = start(tmp_path, detach=spec)
    pid = grandchild_pid(spec)
    beating(spec)
    process.wait(10)  # the parent is gone; the grandchild is not

    assert alive(pid)
    assert codex_process.kill_tree(process) is True
    assert stopped(spec, 2.0) and not alive(pid)
    assert active and active[-1] == 0


# --- B2: the death of the server stops everything -----------------------------------------------

SERVER = '''
import json, sys
from nexus.adapters import codex_process
argv = json.loads(sys.argv[1])
process = codex_process.spawn(argv, sys.argv[2], codex_process.child_env(), contain=True)
print(process.pid, flush=True)
sys.stdin.read()
'''


def test_the_death_of_the_server_stops_the_whole_tree(tmp_path):
    spec = detach_spec(tmp_path / "gc")
    server_script = tmp_path / "server.py"
    server_script.write_text(SERVER, encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, str(server_script), json.dumps(fake(tmp_path, detach=spec, hang=True)),
         str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        pid = grandchild_pid(spec)
        beating(spec)

        server.kill()  # TerminateProcess: no clean-up code of the server runs
        server.wait(10)

        assert stopped(spec, 2.0)
        wait_until(lambda: not alive(pid), "the grandchild died with the server", timeout=2.0)
    finally:
        server.stdin.close()
        server.stdout.close()


# --- B3: no breakaway --------------------------------------------------------------------------


def test_a_child_cannot_break_away_from_the_job(tmp_path):
    """The spec expected a refusal (winerror 5). Observed on Windows 11 (2026-11-19): the creation
    succeeds but the child stays in the job. Either way it must not escape: it dies with the job."""
    note = tmp_path / "breakaway.txt"
    process = start(tmp_path, breakaway=str(note))
    process.wait(10)
    outcome = note.read_text(encoding="utf-8")

    assert codex_process.kill_tree(process) is True
    if outcome.startswith("started "):
        pid = int(outcome.split()[1])
        wait_until(lambda: not alive(pid), "the child that asked to break away died with the job",
                   timeout=2.0)
    else:
        assert outcome == "winerror 5"


# --- B4: no race at the start ------------------------------------------------------------------


def test_a_grandchild_launched_at_the_first_instruction_is_always_in_the_job(tmp_path):
    for n in range(20):
        spec = detach_spec(tmp_path / f"gc{n}")
        process = start(tmp_path / f"gc{n}", detach=spec)
        pid = grandchild_pid(spec)

        assert codex_process.kill_tree(process) is True
        wait_until(lambda pid=pid: not alive(pid), f"grandchild {n} stopped with the job",
                   timeout=2.0)


# --- B5: a failed assignment fails closed ------------------------------------------------------


def test_a_failed_assignment_raises_and_leaves_no_process_nor_handle(tmp_path, monkeypatch):
    pids, closed, created = [], [], []
    real_create, real_close = process_job_win._create_job, process_job_win._close

    def create():
        created.append(real_create())
        return created[-1]

    def refuse(job, pid):
        pids.append(pid)
        raise OSError("refused by the test")

    def close(handle):
        closed.append(handle)
        real_close(handle)

    monkeypatch.setattr(process_job_win, "_create_job", create)
    monkeypatch.setattr(process_job_win, "_assign", refuse)
    monkeypatch.setattr(process_job_win, "_close", close)

    with pytest.raises(OSError):
        start(tmp_path, hang=True)

    assert pids and not alive(pids[0])
    assert created and created[0] in closed


def test_a_failed_resume_raises_and_leaves_no_process(tmp_path, monkeypatch):
    pids = []

    def refuse(pid):
        pids.append(pid)
        raise OSError("no thread")

    monkeypatch.setattr(process_job_win, "_resume", refuse)

    with pytest.raises(OSError):
        start(tmp_path, hang=True)
    assert pids and not alive(pids[0])


# --- B6: a clean exit -----------------------------------------------------------------------------


def test_after_a_clean_exit_the_stop_is_immediate_and_repeatable(tmp_path):
    process = start(tmp_path)
    process.wait(10)

    began = time.monotonic()
    assert codex_process.kill_tree(process) is True
    assert codex_process.kill_tree(process) is True
    assert time.monotonic() - began < 2.0
    assert process.nexus_job.handle is None  # closed once, after the confirmed stop


# --- B7: a job that does not empty in time --------------------------------------------------------


def test_a_job_that_does_not_empty_in_time_is_an_unconfirmed_stop(tmp_path, monkeypatch):
    process = start(tmp_path, hang=True)
    monkeypatch.setattr(process_job_win, "_active_processes", lambda job: 1)

    assert codex_process.kill_tree(process, timeout=0.3) is False
    assert process.nexus_job.handle is not None  # kept: the run stays open

    monkeypatch.undo()
    assert codex_process.kill_tree(process) is True


def test_a_failing_query_is_an_unconfirmed_stop_never_an_exception(tmp_path, monkeypatch):
    process = start(tmp_path, hang=True)

    def broken(job):
        raise OSError("query failed")

    monkeypatch.setattr(process_job_win, "_active_processes", broken)
    assert codex_process.kill_tree(process, timeout=0.3) is False
    monkeypatch.undo()
    assert codex_process.kill_tree(process) is True
