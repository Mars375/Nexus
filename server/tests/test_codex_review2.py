"""Second hardening of the Codex adapter (review of #170): shutdown, server repo, limits."""

import subprocess
from pathlib import Path

import pytest
from codex_support import OK_LINES, THREAD, TURN, git, make_fake_codex, make_repo, run_info
from conftest import ActorClient, tailscale_json
from runs_support import dispatch, make_task, register, tick
from sqlalchemy.exc import OperationalError

from nexus.adapters import codex, codex_git
from nexus.adapters.codex import CodexAdapter
from nexus.adapters.registry import AdapterRegistry
from nexus.app import create_app
from nexus.config import Settings
from nexus.models import Run
from nexus.runs import supervisor


def adapter_for(tmp_path, **scenario):
    binary = make_fake_codex(tmp_path / "fake", **scenario)
    repo = make_repo(tmp_path / "repo")
    return CodexAdapter(str(binary), [repo], tmp_path / "data"), repo, binary


# --- The server's own repository, through any of its worktrees --------------------------------


def linked_worktree(repo: Path, where: Path) -> Path:
    git(repo, "worktree", "add", "-q", "-b", "other", str(where))
    return where


def test_a_worktree_of_the_servers_repository_is_refused(tmp_path, monkeypatch):
    server = make_repo(tmp_path / "server")
    other = linked_worktree(server, tmp_path / "server-wt")
    monkeypatch.setattr(codex_git, "server_common_dir", lambda: codex_git.common_dir(server))

    with pytest.raises(ValueError):
        codex_git.choose_repo([other], str(other))
    with pytest.raises(ValueError):
        codex_git.choose_repo([server], None)


def test_the_servers_repository_alone_registers_nothing(tmp_path, monkeypatch):
    server = make_repo(tmp_path / "server")
    binary = make_fake_codex(tmp_path / "fake", lines=[])
    monkeypatch.setattr(codex_git, "server_common_dir", lambda: codex_git.common_dir(server))
    registry = AdapterRegistry()
    settings = Settings(data_dir=tmp_path / "d", codex_bin=str(binary), run_workdirs=(server,))

    assert codex.register_configured(registry, settings) is False


def test_a_missing_git_leaves_codex_unavailable_instead_of_breaking_startup(tmp_path, monkeypatch):
    binary = make_fake_codex(tmp_path / "fake", lines=[])
    repo = make_repo(tmp_path / "repo")

    def no_git(argv, **kwargs):
        if argv and argv[0] == "git":
            raise FileNotFoundError
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", no_git)
    settings = Settings(data_dir=tmp_path / "d", codex_bin=str(binary), run_workdirs=(repo,))

    assert codex.register_configured(AdapterRegistry(), settings) is False


# --- Paths, probe, configuration ---------------------------------------------------------------


def test_a_relative_data_directory_still_gives_a_usable_worktree(tmp_path, monkeypatch):
    binary = make_fake_codex(tmp_path / "fake", lines=OK_LINES)
    repo = make_repo(tmp_path / "repo")
    monkeypatch.chdir(tmp_path)
    adapter = CodexAdapter(str(binary), [repo], Path("data"))

    adapter.dispatch(run_info(1))
    adapter.join("nx-run-1", 20)

    assert (tmp_path / "data" / "worktrees" / "nx-run-1").is_dir()
    assert adapter.watch(run_info(1, external_ref="x")).events[-1].kind in ("review", "done")


def test_the_probe_does_not_capture_the_output(tmp_path, monkeypatch):
    adapter, _, _ = adapter_for(tmp_path, lines=[])
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert adapter.probe() is True
    assert seen["stdout"] is subprocess.DEVNULL and seen["stderr"] is subprocess.DEVNULL
    assert not seen.get("capture_output")


def test_a_duration_that_is_not_finite_in_seconds_is_refused(tmp_path):
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, run_max_minutes=1e308)


def test_finished_jobs_are_not_kept_forever(tmp_path):
    adapter, _, _ = adapter_for(tmp_path, lines=OK_LINES)
    adapter.keep_finished = 1
    for n in (1, 2, 3):
        adapter.dispatch(run_info(n))
        adapter.join(f"nx-run-{n}", 20)
        adapter.watch(run_info(n, external_ref="x"))  # settles it
    adapter.dispatch(run_info(4))

    assert len(adapter._jobs) <= 3  # the last finished one and the running one, not all four


# --- Shutdown and restart ----------------------------------------------------------------------


def test_closing_the_adapter_stops_its_processes_and_a_restart_can_then_cancel(tmp_path):
    adapter, repo, binary = adapter_for(tmp_path, lines=[THREAD, TURN], hang=True)
    adapter.dispatch(run_info(1))
    assert not adapter.is_finished("nx-run-1")

    adapter.close()

    assert adapter.is_finished("nx-run-1")
    reborn = CodexAdapter(str(binary), [repo], tmp_path / "data")  # a new process of the server
    reborn.cancel(run_info(1, external_ref="nexus/nx-run-1"))  # confirmed stopped: no error


def test_cancelling_after_a_crash_does_not_claim_a_stop_it_cannot_confirm(tmp_path):
    adapter, repo, binary = adapter_for(tmp_path, lines=[])
    reborn = CodexAdapter(str(binary), [repo], tmp_path / "data")

    with pytest.raises(RuntimeError):
        reborn.cancel(run_info(7, external_ref="nexus/nx-run-7"))
    reborn.cancel(run_info(8))  # never launched: nothing to stop


def test_the_server_shutdown_stops_codex_processes(tmp_path):
    binary = make_fake_codex(tmp_path / "fake", lines=[THREAD, TURN], hang=True)
    repo = make_repo(tmp_path / "repo")
    settings = Settings(data_dir=tmp_path / "data", codex_bin=str(binary), run_workdirs=(repo,))
    with ActorClient(create_app(settings, nodes_runner=tailscale_json)) as client:
        dispatch(client, make_task(client), workdir=str(repo))
        tick(client)
        adapter = client.app.state.adapters.get("codex")
        assert not adapter.is_finished("nx-run-1")

    assert adapter.is_finished("nx-run-1")


# --- #168 follow-up: a reference that cannot be written and a stop that fails --------------------


def test_a_failed_stop_after_a_lost_reference_does_not_free_the_executor(client, monkeypatch):
    adapter = register(client)
    adapter.fail_cancel = True
    dispatch(client, make_task(client))
    real = supervisor._finish

    def failing(factory, run, **changes):
        if changes.get("external_ref"):
            raise OperationalError("UPDATE", {}, Exception("disk I/O error"))
        return real(factory, run, **changes)

    monkeypatch.setattr(supervisor, "_finish", failing)

    tick(client)

    with client.app.state.sessionmaker() as session:
        assert session.get(Run, 1).status != "failed"  # still held: the work may be running
