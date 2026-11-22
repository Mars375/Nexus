"""Cancel against the commit of Nexus, through the real supervisor, for Codex and `claude-code`
(spec #186, §1.3 « Annulation après le commit de Nexus », §7; tests D10 and D14), and the
registration of Codex outside Windows (§4.3)."""

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from claude_code_support import OK_LINES as CLAUDE_OK
from claude_code_support import Rig as ClaudeRig
from claude_code_support import settings_for as claude_settings
from codex_support import (
    OK_LINES,
    THREAD,
    TURN,
    fail_closing_once,
    git,
    make_fake_codex,
    make_repo,
    run_info,
    write,
)
from conftest import ActorClient, tailscale_json
from process_support import wait_until
from runs_support import dispatch, events_of, make_task, tick
from sqlalchemy.exc import OperationalError

from nexus.adapters import codex
from nexus.adapters.base import RunAlreadyCommitted
from nexus.adapters.codex import CodexAdapter
from nexus.adapters.registry import AdapterRegistry
from nexus.app import create_app
from nexus.config import Settings
from nexus.runs import supervisor


@dataclass
class Setup:
    """One executor wired into a real app: what to hand over, where its branch lives."""

    settings: Settings
    executor: str
    fields: dict
    repo: Path

    def head(self) -> str:
        return git(self.repo, "rev-parse", "refs/heads/nexus/nx-run-1")

    def start(self) -> str:
        return git(self.repo, "rev-parse", "HEAD")

    def commits(self) -> int:
        return int(git(self.repo, "rev-list", "--count", f"{self.start()}..{self.head()}"))


def codex_setup(tmp_path, monkeypatch, *, change=True, **scenario) -> Setup:
    actions = [write()] if change else []
    binary = make_fake_codex(tmp_path / "fake", lines=OK_LINES, actions=actions, **scenario)
    repo = make_repo(tmp_path / "repo")
    settings = Settings(data_dir=tmp_path / "data", codex_bin=str(binary), run_workdirs=(repo,),
                        run_weak_containment=sys.platform != "win32")
    return Setup(settings, "codex", {"workdir": str(repo)}, repo)


def claude_setup(tmp_path, monkeypatch, *, change=True, **scenario) -> Setup:
    r = ClaudeRig(tmp_path, monkeypatch, lines=CLAUDE_OK, actions=[write()] if change else [],
                  **scenario)
    fields = {"executor": "claude", "agent": "claude", "model": "sonnet", "workdir": str(r.repo)}
    return Setup(claude_settings(r), "claude", fields, r.repo)


SETUPS = pytest.mark.parametrize("make", [codex_setup, claude_setup], ids=["codex", "claude"])


def closing_lost(client, s: Setup) -> tuple[str, object]:
    """Launch, let the run end, then lose its closing event once: the commit was attempted (and
    made when there was a change), the run is still open."""
    task = make_task(client)
    assert dispatch(client, task, **s.fields).status_code == 201
    tick(client)  # launches
    adapter = client.app.state.adapters.get(s.executor)
    adapter.join("nx-run-1", 20)
    job = adapter._job("nx-run-1")
    fail_closing_once(job)
    tick(client)  # the end is judged, `commit_run` called, its event lost (logged by type)
    assert job.commit_attempted and not job.settled
    assert client.get("/api/runs/nx-run-1").json()["status"] in ("dispatched", "running")
    assert client.post("/api/runs/nx-run-1/cancel").status_code == 200
    return task, job


# --- D14: a cancel after the commit of Nexus ends on that commit ---------------------------------


@SETUPS
def test_a_cancel_after_the_commit_ends_done_on_it(tmp_path, monkeypatch, make):
    s = make(tmp_path, monkeypatch)
    with ActorClient(create_app(s.settings, nodes_runner=tailscale_json)) as client:
        task, _ = closing_lost(client, s)

        tick(client)

        assert client.get("/api/runs/nx-run-1").json()["status"] == "done"
        got = events_of(client, task)
        done = [e for e in got if e["kind"] == "done" and e["run"] == "nx-run-1"]
        assert len(done) == 1 and done[0]["evidence"] == [f"commit:{s.head()[:12]}"]
        assert all(e["subject"] != "run annulé" for e in got)
        assert s.commits() == 1


@SETUPS
def test_a_cancel_after_nothing_to_commit_ends_cancelled(tmp_path, monkeypatch, make):
    s = make(tmp_path, monkeypatch, change=False)
    with ActorClient(create_app(s.settings, nodes_runner=tailscale_json)) as client:
        task, _ = closing_lost(client, s)

        tick(client)

        assert client.get("/api/runs/nx-run-1").json()["status"] == "cancelled"
        assert s.head() == s.start()
        assert any(e["subject"] == "run annulé" for e in events_of(client, task))


@SETUPS
def test_a_lost_publication_after_the_commit_never_turns_into_a_cancel(tmp_path, monkeypatch,
                                                                       make):
    s = make(tmp_path, monkeypatch)
    with ActorClient(create_app(s.settings, nodes_runner=tailscale_json)) as client:
        task, job = closing_lost(client, s)
        real, failed = supervisor._publish, []

        def publish_fails_once(*args, **kwargs):
            if not failed:
                failed.append(1)
                raise OperationalError("INSERT", {}, Exception("disk I/O error"))
            return real(*args, **kwargs)

        monkeypatch.setattr(supervisor, "_publish", publish_fails_once)
        tick(client)  # the commit wins, but its end cannot be written: the run stays open
        assert failed and job.settled
        assert client.get("/api/runs/nx-run-1").json()["status"] in ("dispatched", "running")

        tick(client)  # the job is closed now: the recorded outcome still decides

        assert client.get("/api/runs/nx-run-1").json()["status"] == "done"
        assert all(e["subject"] != "run annulé" for e in events_of(client, task))
        assert s.commits() == 1


# --- D10: a cancel before the commit, and one after the close -------------------------------------


def test_a_cancel_during_the_turn_commits_nothing(tmp_path, monkeypatch):
    s = codex_setup(tmp_path, monkeypatch, hang=True)
    with ActorClient(create_app(s.settings, nodes_runner=tailscale_json)) as client:
        task = make_task(client)
        dispatch(client, task, **s.fields)
        tick(client)
        worktree = tmp_path / "data" / "worktrees" / "nx-run-1"
        adapter = client.app.state.adapters.get("codex")
        job = adapter._job("nx-run-1")
        wait_until((worktree / "a.txt").exists, "the fake wrote a.txt")
        assert client.post("/api/runs/nx-run-1/cancel").status_code == 200

        tick(client)

        assert client.get("/api/runs/nx-run-1").json()["status"] == "cancelled"
        assert s.head() == s.start() and (worktree / "a.txt").exists()
        assert not job.commit_attempted


def test_a_cancel_after_the_close_changes_nothing(tmp_path, monkeypatch):
    s = codex_setup(tmp_path, monkeypatch)
    with ActorClient(create_app(s.settings, nodes_runner=tailscale_json)) as client:
        task = make_task(client)
        dispatch(client, task, **s.fields)
        tick(client)
        client.app.state.adapters.get("codex").join("nx-run-1", 20)
        tick(client)
        assert client.get("/api/runs/nx-run-1").json()["status"] == "done"

        assert client.post("/api/runs/nx-run-1/cancel").status_code == 409
        tick(client)

        assert client.get("/api/runs/nx-run-1").json()["status"] == "done"
        assert s.commits() == 1


# --- The adapter's side of the rule ---------------------------------------------------------------


def test_the_adapter_raises_once_its_commit_is_made_and_cancels_otherwise(tmp_path):
    for n, actions in ((1, [write()]), (2, [])):
        binary = make_fake_codex(tmp_path / f"fake{n}", lines=OK_LINES, actions=actions)
        repo = make_repo(tmp_path / f"repo{n}")
        adapter = CodexAdapter(str(binary), [repo], tmp_path / f"data{n}")
        adapter.dispatch(run_info(1))
        adapter.join("nx-run-1", 20)
        job = adapter._job("nx-run-1")
        fail_closing_once(job)
        with pytest.raises(RuntimeError):
            adapter.watch(run_info(1, external_ref="x"))

        if actions:
            with pytest.raises(RunAlreadyCommitted):
                adapter.cancel(run_info(1, external_ref="x"))
            assert job.events[-1].kind == "done"
            with pytest.raises(RunAlreadyCommitted):  # again: the outcome is kept
                adapter.cancel(run_info(1, external_ref="x"))
        else:
            adapter.cancel(run_info(1, external_ref="x"))
            assert job.settled


def test_a_close_that_cannot_happen_keeps_the_cancel_pending(tmp_path):
    binary = make_fake_codex(tmp_path / "fake", lines=OK_LINES, actions=[write()])
    adapter = CodexAdapter(str(binary), [make_repo(tmp_path / "repo")], tmp_path / "data")
    adapter.dispatch(run_info(1))
    adapter.join("nx-run-1", 20)
    job = adapter._job("nx-run-1")
    fail_closing_once(job)
    with pytest.raises(RuntimeError):
        adapter.watch(run_info(1, external_ref="x"))
    job.settle_lock.acquire()  # another closing attempt in progress
    try:
        with pytest.raises(RuntimeError, match="fermeture"):
            adapter.cancel(run_info(1, external_ref="x"))
    finally:
        job.settle_lock.release()
    assert not job.settled


# --- §4.3: outside Windows, Codex only with the weak containment ---------------------------------


def registered(tmp_path, *, windows, **extra) -> bool:
    binary = make_fake_codex(tmp_path / "fake", lines=[THREAD, TURN])
    repo = make_repo(tmp_path / "repo")
    settings = Settings(data_dir=tmp_path / "data", codex_bin=str(binary), run_workdirs=(repo,),
                        **extra)
    registry = AdapterRegistry()
    done = codex.register_configured(registry, settings, windows=windows)
    assert (registry.get("codex") is not None) is done
    return done


def test_codex_is_registered_under_windows(tmp_path, caplog):
    assert registered(tmp_path, windows=True) is True
    assert not any("WEAK" in r.getMessage() for r in caplog.records)


def test_codex_is_not_registered_elsewhere_without_the_weak_containment(tmp_path):
    assert registered(tmp_path, windows=False) is False


def test_the_weak_containment_registers_codex_elsewhere_and_says_so(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="nexus.codex"):
        assert registered(tmp_path, windows=False, run_weak_containment=True) is True
    assert any("NEXUS_RUN_WEAK_CONTAINMENT=1" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("value", "expected"), [("1", True), ("0", False), ("true", False),
                                                 (None, False)])
def test_the_weak_containment_is_read_from_the_environment(tmp_path, monkeypatch, value,
                                                           expected):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    if value is None:
        monkeypatch.delenv("NEXUS_RUN_WEAK_CONTAINMENT", raising=False)
    else:
        monkeypatch.setenv("NEXUS_RUN_WEAK_CONTAINMENT", value)

    assert Settings.from_env().run_weak_containment is expected
