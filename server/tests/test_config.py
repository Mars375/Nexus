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


def test_from_env_rejects_invalid_values(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_BACKUP_INTERVAL_HOURS", "0")
    with pytest.raises(ValueError):
        Settings.from_env()
