"""`claude-code` wired into the app: configuration and opt-in registration (spec 2026-11-11, §2;
tests 33 to 37)."""

import shutil
import subprocess
from pathlib import Path

import pytest
from claude_code_support import make_fake_claude
from codex_support import make_repo
from conftest import ActorClient, tailscale_json

from nexus.adapters import claude_code
from nexus.adapters.registry import AdapterRegistry
from nexus.app import create_app
from nexus.config import Settings

SERVER_REPO = Path(__file__).resolve().parents[2]


def settings_for(tmp_path, binary, repos, **extra) -> Settings:
    return Settings(data_dir=tmp_path / "data", claude_bin=str(binary),
                    run_workdirs=tuple(repos), codex_bin=str(tmp_path / "no-codex"), **extra)


def test_the_shell_cannot_leak_into_the_suite():
    # `NEXUS_CLAUDE_BIN` exported by Loïc is removed by an autouse fixture of conftest.py.
    assert Settings.from_env().claude_bin is None


def test_settings_read_the_claude_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_CLAUDE_BIN", "/x/claude")
    assert Settings.from_env().claude_bin == "/x/claude"
    monkeypatch.setenv("NEXUS_CLAUDE_BIN", "")
    assert Settings.from_env().claude_bin is None


# --- 33: no fallback on the PATH ------------------------------------------------------------------


def test_nothing_is_registered_without_the_variable_even_if_claude_is_on_the_path(
        tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "repo")
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: f"/usr/bin/{name}")
    started = []
    real = subprocess.Popen

    class Spy(real):
        def __init__(self, *a, **k):
            started.append(a)
            super().__init__(*a, **k)

    monkeypatch.setattr(subprocess, "Popen", Spy)
    registry = AdapterRegistry()

    settings = Settings(data_dir=tmp_path, run_workdirs=(repo,), codex_bin=str(tmp_path / "x"))
    assert claude_code.register_configured(registry, settings) is False

    assert registry.get("claude") is None and not started


# --- 34: a repository is needed -------------------------------------------------------------------


def test_nothing_is_registered_without_a_usable_repository(tmp_path):
    binary = make_fake_claude(tmp_path / "fake", lines=[])
    repo = make_repo(tmp_path / "repo")
    for s in [
        settings_for(tmp_path, binary, []),                         # no repository
        settings_for(tmp_path, binary, [SERVER_REPO]),              # only the server's own
        settings_for(tmp_path, binary, [tmp_path / "not-a-repo"]),  # not a repository
        settings_for(tmp_path, tmp_path / "missing", [repo]),       # no binary
    ]:
        registry = AdapterRegistry()
        assert claude_code.register_configured(registry, s) is False
        assert registry.get("claude") is None


# --- 35: the probe --------------------------------------------------------------------------------


def test_a_probe_that_fails_or_times_out_registers_nothing(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "repo")
    monkeypatch.setattr(claude_code, "PROBE_TIMEOUT", 0.3)
    for name, scenario in {"exit": {"version_exit": 3}, "slow": {"version_sleep": 5}}.items():
        binary = make_fake_claude(tmp_path / name, lines=[], **scenario)
        registry = AdapterRegistry()
        assert claude_code.register_configured(
            registry, settings_for(tmp_path, binary, [repo])) is False
        assert registry.get("claude") is None


def test_the_probe_only_asks_for_the_version(tmp_path):
    binary = make_fake_claude(tmp_path / "fake", lines=[])
    adapter = claude_code.ClaudeCodeAdapter(str(binary), [], tmp_path)
    assert adapter.probe() is True
    assert not (tmp_path / "fake" / "args.json").exists()  # no model run, no `-p`
    assert claude_code.ClaudeCodeAdapter(str(tmp_path / "missing"), [], tmp_path).probe() is False


# --- 36: registered -------------------------------------------------------------------------------


def test_a_valid_configuration_registers_the_adapter_under_claude(tmp_path):
    binary = make_fake_claude(tmp_path / "fake", lines=[])
    repo = make_repo(tmp_path / "repo")
    registry = AdapterRegistry()

    assert claude_code.register_configured(registry, settings_for(tmp_path, binary, [repo]))

    adapter = registry.get("claude")
    assert adapter.name == "claude-code" and registry.executors() == ["claude"]


def test_the_app_offers_claude_with_its_agent_and_its_three_models(tmp_path):
    binary = make_fake_claude(tmp_path / "fake", lines=[])
    repo = make_repo(tmp_path / "repo")
    app = create_app(settings_for(tmp_path, binary, [repo]), nodes_runner=tailscale_json)
    with ActorClient(app) as client:
        listed = client.get("/api/executors").json()
    (claude,) = listed
    assert claude["executor"] == "claude" and claude["agents"] == ["claude"]
    assert claude["models"] == ["haiku", "sonnet", "opus"]
    assert claude["workdirs"] == [str(repo.resolve())]


def test_the_default_app_offers_no_claude(client):
    assert "claude" not in client.app.state.adapters.executors()


# --- 37: the guard --------------------------------------------------------------------------------


def test_the_guard_refuses_to_start_the_real_binary():
    with pytest.raises(AssertionError, match="real claude"):
        subprocess.Popen(["claude", "--version"])
    with pytest.raises(AssertionError, match="real claude"):
        subprocess.run([str(Path("somewhere") / "claude.exe"), "-p"])
