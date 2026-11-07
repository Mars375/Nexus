"""Codex wired into the app: configuration, registration, a whole run, and #168."""

import os
import subprocess
from pathlib import Path

import pytest
from codex_support import OK_LINES, make_fake_codex, make_repo
from conftest import ActorClient, tailscale_json
from runs_support import FakeAdapter, code_of, dispatch, events_of, make_task, register, tick
from sqlalchemy.exc import OperationalError

from nexus.adapters import codex
from nexus.adapters.registry import AdapterRegistry
from nexus.app import create_app
from nexus.config import Settings
from nexus.models import Run
from nexus.runs import supervisor


def settings_for(tmp_path, binary, repos, **extra) -> Settings:
    return Settings(data_dir=tmp_path / "data", codex_bin=str(binary),
                    run_workdirs=tuple(repos), **extra)


def test_settings_read_the_codex_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_CODEX_BIN", "/x/codex")
    both = os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")])
    monkeypatch.setenv("NEXUS_RUN_WORKDIRS", both)
    monkeypatch.setenv("NEXUS_RUN_MAX_MINUTES", "5")

    s = Settings.from_env()

    assert s.codex_bin == "/x/codex" and s.run_max_minutes == 5
    assert s.run_workdirs == (tmp_path / "a", tmp_path / "b")
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, run_max_minutes=0)


def test_nothing_is_registered_without_a_valid_binary_and_a_repository(tmp_path):
    binary = make_fake_codex(tmp_path / "fake", lines=[])
    repo = make_repo(tmp_path / "repo")
    for s in [
        Settings(data_dir=tmp_path),                                     # nothing configured
        settings_for(tmp_path, binary, []),                               # no repository
        settings_for(tmp_path, tmp_path / "missing", [repo]),             # no binary
        settings_for(tmp_path, binary, [tmp_path / "not-a-repo"]),        # not a repository
    ]:
        registry = AdapterRegistry()
        assert codex.register_configured(registry, s) is False
        assert registry.get("codex") is None


def test_a_valid_configuration_registers_the_adapter(tmp_path):
    binary = make_fake_codex(tmp_path / "fake", lines=[])
    repo = make_repo(tmp_path / "repo")
    registry = AdapterRegistry()

    assert codex.register_configured(registry, settings_for(tmp_path, binary, [repo])) is True
    assert registry.get("codex").name == "codex"


def test_the_default_app_has_no_adapter(client):
    assert client.app.state.adapters.executors() == []


def test_the_guard_refuses_to_start_the_real_binary():
    with pytest.raises(AssertionError, match="real codex"):
        subprocess.Popen(["codex", "--version"])
    with pytest.raises(AssertionError, match="real codex"):
        subprocess.run([str(Path("somewhere") / "codex.exe"), "exec"])


def test_a_whole_run_through_the_supervisor(tmp_path):
    binary = make_fake_codex(tmp_path / "fake", lines=OK_LINES, commit=True)
    repo = make_repo(tmp_path / "repo")
    app = create_app(settings_for(tmp_path, binary, [repo]), nodes_runner=tailscale_json)
    with ActorClient(app) as client:
        task = make_task(client)
        res = dispatch(client, task, workdir=str(repo))
        assert res.status_code == 201, res.text

        tick(client)  # launches
        adapter = client.app.state.adapters.get("codex")
        adapter.join("nx-run-1", 20)
        tick(client)  # reads the end

        run = client.get("/api/runs/nx-run-1").json()
        assert run["status"] == "done" and run["external_ref"]
        got = events_of(client, task)
        assert [e["kind"] for e in got][0:2] == ["claimed", "working"]
        assert got[-1]["kind"] == "done" and got[-1]["evidence"][0].startswith("commit:")
        assert {e["origin"] for e in got} == {"codex"}
        assert client.get(f"/api/tasks/{task}").json()["status"] == "done"
        assert "RAW-OUTPUT" not in str([e["body"] for e in got])


def test_without_a_registered_adapter_the_dispatch_is_still_refused(client):
    task = make_task(client)
    assert code_of(dispatch(client, task)) == "executor_unavailable"


# --- #168: the reference received from dispatch is never lost ---------------------------------


def test_a_reference_whose_write_fails_is_used_to_stop_the_work(client, monkeypatch):
    adapter = register(client)
    task = make_task(client)
    dispatch(client, task)
    real = supervisor._finish

    def failing(factory, run, **changes):
        if changes.get("external_ref"):
            raise OperationalError("UPDATE", {}, Exception("disk I/O error"))
        return real(factory, run, **changes)

    monkeypatch.setattr(supervisor, "_finish", failing)

    tick(client)

    assert adapter.cancel_refs == ["ext-1"]  # the executor was stopped with the received ref
    with client.app.state.sessionmaker() as session:
        assert session.get(Run, 1).status == "failed"
    assert isinstance(adapter, FakeAdapter)
