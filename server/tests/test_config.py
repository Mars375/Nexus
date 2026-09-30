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
