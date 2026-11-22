"""Containment of a run's process tree, on every platform (spec 2026-11-13, §4.4, §4.5, and the end
detection of §1.3; tests B8, B10 and B11). Ungated: they run in the Linux CI and the local hook."""

import signal
import subprocess
import sys
import time

import pytest
from claude_code_support import OK_LINES as CLAUDE_OK
from claude_code_support import Rig, claude_info, write
from codex_support import OK_LINES, calls, make_fake_codex, make_repo, run_info
from process_support import detach_spec, grandchild_pid, stopped, wait_until

from nexus.adapters import codex_process, hermes_cli
from nexus.adapters.codex import CodexAdapter

# --- B8: without `contain`, the launch and the stop are what they were (Hermes) ------------------


class Recorder:
    calls: list = []

    def __init__(self, args, **kwargs):
        Recorder.calls.append((args, kwargs))
        self.pid = 4242

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def recorder(monkeypatch):
    Recorder.calls = []
    monkeypatch.setattr(subprocess, "Popen", Recorder)
    return Recorder.calls


def platform_options() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def test_a_launch_without_contain_is_unchanged(recorder):
    text = codex_process.spawn(["x", "--y"], "here", {"A": "1"})
    raw = codex_process.spawn(["x"], "here", {}, text=False, stderr=subprocess.PIPE)

    pipes = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE}
    assert recorder == [
        (["x", "--y"], {"cwd": "here", "env": {"A": "1"}, **pipes, "stderr": subprocess.DEVNULL,
                        **platform_options(), "text": True, "encoding": "utf-8",
                        "errors": "replace"}),
        (["x"], {"cwd": "here", "env": {}, **pipes, "stderr": subprocess.PIPE,
                 **platform_options()}),
    ]
    assert not hasattr(text, "nexus_job") and not hasattr(raw, "nexus_job")


def test_a_stop_without_contain_is_unchanged(recorder, monkeypatch):
    process = codex_process.spawn(["x"], "here", {})
    sent = []
    if sys.platform == "win32":
        monkeypatch.setattr(subprocess, "run", lambda argv, **kw: sent.append(argv))
        assert codex_process.kill_tree(process) is True
        assert sent == [["taskkill", "/PID", "4242", "/T", "/F"]]
    else:
        monkeypatch.setattr(codex_process.os, "killpg", lambda *a: sent.append(a))
        assert codex_process.kill_tree(process) is True
        assert sent == [(4242, signal.SIGKILL)]


def test_hermes_never_asks_for_containment(monkeypatch):
    seen = []

    def spy(*args, **kwargs):
        seen.append(kwargs)
        raise OSError("stop here")

    monkeypatch.setattr(codex_process, "spawn", spy)
    with pytest.raises(OSError):
        hermes_cli.call("hermes-fake", ["list"], cwd=".")
    assert seen and "contain" not in seen[0]


# --- B10: Codex and claude-code launch their run contained ---------------------------------------


@pytest.fixture
def spawned(monkeypatch):
    seen = []
    real = codex_process.spawn

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(codex_process, "spawn", spy)
    return seen


def test_claude_code_launches_its_run_contained(tmp_path, monkeypatch, spawned):
    r = Rig(tmp_path, monkeypatch, lines=CLAUDE_OK, actions=[write()])
    r.run()
    assert [kw.get("contain") for kw in spawned] == [True]
    assert r.last().kind == "done"


def test_codex_launches_its_run_contained(tmp_path, spawned):
    # PR C: the two control calls of the launch (spec #186, §5.3) are spawns too, contained.
    adapter = codex_adapter(tmp_path, lines=OK_LINES)
    adapter.dispatch(run_info(1))
    adapter.join("nx-run-1", 20)
    assert spawned and all(kw.get("contain") is True for kw in spawned)
    assert [c["kind"] for c in calls(tmp_path / "fake")][-1] == "run"


# --- B11: a grandchild that holds the output pipe does not keep the run open ---------------------


def codex_adapter(tmp_path, **scenario):
    binary = make_fake_codex(tmp_path / "fake", **scenario)
    repo = make_repo(tmp_path / "repo")
    return CodexAdapter(str(binary), [repo], tmp_path / "data", max_seconds=600)


class StuckReader:
    """A reader thread that never ends (stands for one blocked on a pipe nobody closes)."""

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return True


def test_codex_closes_a_run_whose_grandchild_holds_the_pipe(tmp_path):
    spec = detach_spec(tmp_path / "gc")
    adapter = codex_adapter(tmp_path, lines=OK_LINES, detach=spec)
    try:
        adapter.dispatch(run_info(1))
        job = adapter._job("nx-run-1")
        grandchild_pid(spec)
        wait_until(lambda: codex_process.exited(job.process), "the fake exited")  # not reaped

        result = adapter.watch(run_info(1, external_ref="x"))

        assert job.settled and result.events[-1].kind == "review"  # judged, not timed out
        assert not job.reader.is_alive()
        assert stopped(spec, 2.0)
    finally:
        adapter.close()


def test_codex_keeps_the_run_open_while_the_reader_has_not_finished(tmp_path):
    adapter = codex_adapter(tmp_path, lines=OK_LINES)
    adapter.dispatch(run_info(1))
    job = adapter._job("nx-run-1")
    adapter.join("nx-run-1", 20)
    job.reader = StuckReader()

    with pytest.raises(RuntimeError):
        adapter.watch(run_info(1, external_ref="x"))
    assert not job.settled and all(e.kind != "review" for e in job.events)


def test_claude_code_closes_a_run_whose_grandchild_holds_the_pipe(tmp_path, monkeypatch):
    spec = detach_spec(tmp_path / "gc")
    r = Rig(tmp_path, monkeypatch, lines=CLAUDE_OK, actions=[write()], detach=spec)
    try:
        r.adapter.dispatch(claude_info())
        job = r.adapter._job("nx-run-1")
        grandchild_pid(spec)
        wait_until(lambda: codex_process.exited(job.process), "the fake exited")  # not reaped

        last = r.last()

        assert job.settled and last.kind == "done"  # judged, and Nexus committed
        assert not job.reader.is_alive()
        assert stopped(spec, 2.0)
    finally:
        r.adapter.close()


def test_claude_code_keeps_the_run_open_while_the_reader_has_not_finished(tmp_path, monkeypatch):
    r = Rig(tmp_path, monkeypatch, lines=CLAUDE_OK, actions=[write()])
    info, _ = r.run()
    job = r.adapter._job(info.ref)
    job.reader = StuckReader()

    with pytest.raises(RuntimeError):
        r.watch()
    assert not job.settled and r.head() == r.start()  # nothing decided, nothing committed


class FinishedReader:
    """A reader thread that has ended."""

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


def test_codex_judges_the_deadline_on_when_the_exit_was_first_seen(tmp_path, monkeypatch):
    adapter = codex_adapter(tmp_path, lines=OK_LINES)
    adapter.dispatch(run_info(1))
    job = adapter._job("nx-run-1")
    adapter.join("nx-run-1", 20)
    job.reader, job.ended_at = StuckReader(), None  # the pipe is still held: no EOF yet

    with pytest.raises(RuntimeError):
        adapter.watch(run_info(1, external_ref="x"))
    later = time.monotonic() + 10**6  # the next tick comes after the maximum duration
    monkeypatch.setattr(time, "monotonic", lambda: later)
    job.reader = FinishedReader()
    result = adapter.watch(run_info(1, external_ref="x"))

    assert job.settled and result.events[-1].kind == "review"
    assert all(e.subject != "Durée maximale dépassée" for e in job.events)


def test_claude_code_judges_the_deadline_on_when_the_exit_was_first_seen(tmp_path, monkeypatch):
    r = Rig(tmp_path, monkeypatch, lines=CLAUDE_OK, actions=[write()])
    info, _ = r.run()
    job = r.adapter._job(info.ref)
    job.reader, job.ended_at = StuckReader(), None

    with pytest.raises(RuntimeError):
        r.watch()
    later = time.monotonic() + 10**6
    monkeypatch.setattr(time, "monotonic", lambda: later)
    job.reader = FinishedReader()

    assert r.last().kind == "done"


def test_a_failed_contained_codex_launch_leaves_no_worktree(tmp_path, monkeypatch):
    adapter = codex_adapter(tmp_path, lines=OK_LINES)

    def refuse(*args, **kwargs):
        raise OSError("AssignProcessToJobObject : refusé")

    monkeypatch.setattr(codex_process, "spawn", refuse)
    with pytest.raises(OSError):
        adapter.dispatch(run_info(1))

    repo = tmp_path / "repo"
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", "nexus/*"],
                              capture_output=True, text=True, check=True).stdout
    worktrees = subprocess.run(["git", "-C", str(repo), "worktree", "list"],
                               capture_output=True, text=True, check=True).stdout
    assert branches.strip() == "" and "nx-run-1" not in worktrees


class Reaped:
    """A group leader already reaped."""

    returncode = 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def test_an_empty_group_of_a_reaped_leader_is_never_signalled(monkeypatch):
    sent = []

    def killpg(pgid, sig):
        sent.append(sig)
        if sig == 0:
            raise ProcessLookupError

    monkeypatch.setattr(codex_process.os, "killpg", killpg, raising=False)

    assert codex_process._stop_group(Reaped(), 4242, 1.0) is True
    assert sent == [0]  # only the probe: the id may belong to another group by now


class Running:
    """A group leader still running, then reaped by the stop."""

    def __init__(self):
        self.code = None

    @property
    def returncode(self):  # what the stop reads: never `poll()`, which would reap the leader
        return self.code

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.code = -9
        return self.code


def test_a_confirmed_group_stop_never_signals_again(monkeypatch):
    sent, alive = [], [True]

    def killpg(pgid, sig):
        sent.append(sig)
        if sig == 0 and not alive[0]:
            raise ProcessLookupError
        if sig != 0:
            alive[0] = False

    monkeypatch.setattr(codex_process.os, "killpg", killpg, raising=False)
    monkeypatch.setattr(codex_process.signal, "SIGKILL", 9, raising=False)
    process = Running()

    assert codex_process._stop_group(process, 4242, 1.0) is True
    first = list(sent)
    alive[0] = True  # the id now leads another group
    assert codex_process._stop_group(process, 4242, 1.0) is True
    assert sent == first and 9 in first  # no signal, not even a probe, after the confirmation


def test_an_unconfirmed_group_stop_may_be_tried_again(monkeypatch):
    monkeypatch.setattr(codex_process.os, "killpg", lambda pgid, sig: None, raising=False)
    monkeypatch.setattr(codex_process.signal, "SIGKILL", 9, raising=False)
    process = Running()

    assert codex_process._stop_group(process, 4242, 0.1) is False  # the group never empties
    assert not getattr(process, "nexus_stopped", False)


# --- Review of PR B: the id of a reaped group leader may be reused (rule of `_stop_group`) --------


def test_a_reaped_leader_whose_group_still_answers_is_never_signalled(monkeypatch):
    sent = []
    monkeypatch.setattr(codex_process.os, "killpg", lambda pgid, sig: sent.append(sig),
                        raising=False)
    monkeypatch.setattr(codex_process.signal, "SIGKILL", 9, raising=False)

    # Reaped elsewhere, members left: ours or another group's by now, Nexus cannot tell.
    assert codex_process._stop_group(Reaped(), 4242, 0.2) is False
    assert sent and set(sent) == {0}  # probes only, never a signal


def test_a_group_probe_refused_by_permission_is_an_unconfirmed_stop(monkeypatch):
    def killpg(pgid, sig):
        raise PermissionError

    monkeypatch.setattr(codex_process.os, "killpg", killpg, raising=False)

    # EPERM: a member still exists that Nexus may not signal: never a confirmed stop.
    assert codex_process._stop_group(Reaped(), 4242, 0.2) is False


def test_two_stops_of_one_run_are_serialized(monkeypatch):
    import threading

    order = []
    process = Running()
    process.nexus_stop_lock = threading.Lock()
    process.nexus_stop_lock.acquire()  # another stop of the same run is in progress
    monkeypatch.setattr(codex_process.os, "killpg", lambda pgid, sig: order.append(sig),
                        raising=False)

    assert codex_process._stop_group(process, 4242, 0.1) is False  # waited, never signalled
    assert order == []


class Contained:
    """A contained POSIX leader as `exited` sees it: never `poll()` (which would reap it)."""

    returncode = None
    pid = 4242
    nexus_job = 4242

    def poll(self):
        raise AssertionError("poll() reaps the leader")


@pytest.mark.parametrize(("answer", "expected"), [("zombie", True), (None, False),
                                                  (ChildProcessError, True)])
def test_the_end_of_a_contained_posix_leader_is_read_without_reaping_it(monkeypatch, answer,
                                                                         expected):
    seen = []

    def waitid(idtype, pid, options):
        seen.append(options)
        if answer is ChildProcessError:
            raise ChildProcessError
        return answer

    monkeypatch.setattr(codex_process, "_contained_posix", lambda process: True)
    monkeypatch.setattr(codex_process.os, "waitid", waitid, raising=False)
    for name, value in (("P_PID", 1), ("WEXITED", 4), ("WNOHANG", 1), ("WNOWAIT", 0x1000000)):
        monkeypatch.setattr(codex_process.os, name, value, raising=False)

    assert codex_process.exited(Contained()) is expected
    assert seen and all(options & 0x1000000 for options in seen)  # WNOWAIT: never reaped
