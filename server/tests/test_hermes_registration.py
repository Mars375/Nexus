"""Hermes wired into the app: configuration, opt-in registration and served agents (§1, 42-43)."""

import shutil

import pytest
from conftest import ActorClient, tailscale_json
from hermes_support import assignees, created, make_fake_hermes, reply
from runs_support import code_of, dispatch, make_task

from nexus.adapters import hermes
from nexus.adapters.registry import AdapterRegistry
from nexus.app import create_app
from nexus.config import Settings


def settings_for(tmp_path, binary, **extra) -> Settings:
    return Settings(data_dir=tmp_path / "data", hermes_bin=str(binary), **extra)


def good(tmp_path):
    return make_fake_hermes(tmp_path / "fake", assignees=[reply(assignees())],
                            create=[reply(created())])


def test_the_shell_cannot_leak_into_the_suite(monkeypatch):
    # `NEXUS_HERMES_*` exported by Loïc are removed by an autouse fixture of conftest.py.
    assert Settings.from_env().hermes_bin is None
    assert Settings.from_env().hermes_profile == "default"


def test_settings_read_the_hermes_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_HERMES_BIN", "/x/hermes")
    monkeypatch.setenv("NEXUS_HERMES_PROFILE", "helios-2")
    s = Settings.from_env()
    assert s.hermes_bin == "/x/hermes" and s.hermes_profile == "helios-2"


@pytest.mark.parametrize("bad", ["", "Helios", "-x", "a b", "a;b", "x" * 65, "é"])
def test_an_invalid_profile_is_refused_without_echoing_it(tmp_path, bad):
    with pytest.raises(ValueError) as error:
        Settings(data_dir=tmp_path, hermes_profile=bad)
    assert bad not in str(error.value) or bad == ""


def test_nothing_is_registered_without_the_variable_even_if_hermes_is_on_the_path(
        tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: f"/usr/bin/{name}")
    registry = AdapterRegistry()
    assert hermes.register_configured(registry, Settings(data_dir=tmp_path)) is False
    assert registry.get("hermes") is None


def test_a_missing_board_or_profile_registers_nothing(tmp_path):
    cases = {
        "board": [reply(exit=1, stderr="board 'nexus' does not exist")],
        "profile": [reply(assignees("autre"))],
    }
    for name, answers in cases.items():
        binary = make_fake_hermes(tmp_path / name, assignees=answers)
        registry = AdapterRegistry()
        assert hermes.register_configured(registry, settings_for(tmp_path, binary)) is False
    assert hermes.register_configured(
        AdapterRegistry(), settings_for(tmp_path, tmp_path / "absent")) is False


def test_without_a_board_handing_work_to_helios_is_refused(tmp_path):
    binary = make_fake_hermes(tmp_path / "fake", assignees=[reply(exit=1)])
    app = create_app(settings_for(tmp_path, binary), nodes_runner=tailscale_json)
    with ActorClient(app) as client:
        task = make_task(client)
        res = dispatch(client, task, executor="hermes", agent="helios")
        assert (res.status_code, code_of(res)) == (409, "executor_unavailable")


def test_a_registered_adapter_serves_helios_only(tmp_path):
    app = create_app(settings_for(tmp_path, good(tmp_path)), nodes_runner=tailscale_json)
    with ActorClient(app) as client:
        (listed,) = client.get("/api/executors").json()
        assert listed["executor"] == "hermes" and listed["agents"] == ["helios"]
        assert listed["workdirs"] == []

        task = make_task(client)
        res = dispatch(client, task, executor="hermes", agent="mnema")
        assert (res.status_code, code_of(res)) == (409, "executor_unavailable")
        assert client.get("/api/runs/nx-run-1").status_code == 404

        res = dispatch(client, task, executor="hermes", agent="codex")
        assert (res.status_code, code_of(res)) == (409, "agent_not_for_executor")
