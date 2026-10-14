import math

import pytest

from nexus.config import Settings


@pytest.mark.parametrize("hours", [0, -1, math.inf, math.nan])
def test_rejects_invalid_backup_interval(tmp_path, hours):
    with pytest.raises(ValueError, match="NEXUS_BACKUP_INTERVAL_HOURS"):
        Settings(data_dir=tmp_path, backup_interval_hours=hours)


@pytest.mark.parametrize("keep", [0, -3])
def test_rejects_invalid_backup_keep(tmp_path, keep):
    with pytest.raises(ValueError, match="NEXUS_BACKUP_KEEP"):
        Settings(data_dir=tmp_path, backup_keep=keep)


@pytest.mark.parametrize("seconds", [0, -5, math.inf])
def test_rejects_invalid_nodes_refresh(tmp_path, seconds):
    with pytest.raises(ValueError, match="NEXUS_NODES_REFRESH_SECONDS"):
        Settings(data_dir=tmp_path, nodes_refresh_seconds=seconds)


@pytest.mark.parametrize(
    "origin", ["null", "http://x/path", "http://u@x", "http://x?q=1", "x", "http://", "*"]
)
def test_rejects_unsafe_allowed_origins(tmp_path, origin):
    with pytest.raises(ValueError, match="NEXUS_ALLOWED_ORIGINS") as error:
        Settings(data_dir=tmp_path, allowed_origins=frozenset({origin}))
    assert origin not in str(error.value)


@pytest.mark.parametrize(
    "origin", ["tauri://localhost", "http://tauri.localhost", "http://[::1]:5173"]
)
def test_accepts_scheme_host_port_origins(tmp_path, origin):
    settings = Settings(data_dir=tmp_path, allowed_origins=frozenset({origin}))
    assert settings.allowed_origins == {origin}


def test_from_env_rejects_invalid_values(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_BACKUP_INTERVAL_HOURS", "0")
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_accepts_loopback_bind(tmp_path, host):
    assert Settings(data_dir=tmp_path, host=host).host == host


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "::", "192.168.1.5", "100.64.0.1", "helios.ts.net", ""]
)
def test_refuses_a_non_loopback_bind_without_echo(tmp_path, host):
    with pytest.raises(ValueError, match="NEXUS_HOST") as error:
        Settings(data_dir=tmp_path, host=host)
    assert "#57" in str(error.value)
    assert "ticket" not in str(error.value)
    if host:
        assert host not in str(error.value)


def test_the_bind_is_read_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="NEXUS_HOST"):
        Settings.from_env()


@pytest.mark.parametrize(
    "host", ["*", "evil.example/x", "u@x", "x:8765", "http://x", "a b", "-x", ""]
)
def test_rejects_unsafe_allowed_hosts_without_echo(tmp_path, host):
    with pytest.raises(ValueError, match="NEXUS_ALLOWED_HOSTS") as error:
        Settings(data_dir=tmp_path, allowed_hosts=frozenset({host}))
    if host:
        assert host not in str(error.value)


def test_allowed_hosts_are_read_from_the_environment_and_lowercased(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_ALLOWED_HOSTS", " Helios.ts.net , ,100.64.0.1,fd7a::1")
    assert Settings.from_env().allowed_hosts == frozenset(
        {"helios.ts.net", "100.64.0.1", "fd7a::1"}
    )


def test_no_allowed_host_by_default(tmp_path):
    assert Settings(data_dir=tmp_path).allowed_hosts == frozenset()
