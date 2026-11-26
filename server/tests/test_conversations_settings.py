"""Settings of the conversation sources (spec §5.1 rule 1, §6.1): off by default, strict bounds.

A refused value is never repeated in the message (ADR-006). It is proven by equality: two
different bad values give the same message, equal to the module's constant (a substring test
would collide with the bounds: `0` is in `3650`).
"""

from pathlib import Path

import pytest

from nexus import config
from nexus.config import Settings

FIELD_VARIABLE = {
    "conv_poll_seconds": "NEXUS_CONV_POLL_SECONDS",
    "conv_since_days": "NEXUS_CONV_SINCE_DAYS",
    "conv_retention_days": "NEXUS_CONV_RETENTION_DAYS",
}


def message_of(**kwargs) -> str:
    with pytest.raises(ValueError) as exc:
        Settings(data_dir=Path("unused"), **kwargs)
    return str(exc.value)


def env_message(monkeypatch, name: str, value: str) -> str:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError) as exc:
        Settings.from_env()
    return str(exc.value)


def test_every_source_is_disabled_by_default(tmp_path):
    s = Settings(data_dir=tmp_path)

    assert (s.conv_claude_root, s.conv_codex_root, s.conv_hermes_db) == (None, None, None)
    assert (s.conv_poll_seconds, s.conv_since_days, s.conv_retention_days) == (60, 31, 31)
    assert all(
        type(v) is int for v in (s.conv_poll_seconds, s.conv_since_days, s.conv_retention_days)
    )


@pytest.mark.parametrize("value", [None, "", "   "])
def test_from_env_never_falls_back_on_home(monkeypatch, tmp_path, value):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    for name in ("NEXUS_CONV_CLAUDE_ROOT", "NEXUS_CONV_CODEX_ROOT", "NEXUS_CONV_HERMES_DB"):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    s = Settings.from_env()

    assert (s.conv_claude_root, s.conv_codex_root, s.conv_hermes_db) == (None, None, None)
    home = str(Path.home())
    assert not any(home in str(v) for v in vars(s).values() if isinstance(v, Path) and
                   v != s.data_dir)


def test_from_env_reads_each_root(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_CONV_CLAUDE_ROOT", str(tmp_path / "c" / "projects"))
    monkeypatch.setenv("NEXUS_CONV_CODEX_ROOT", str(tmp_path / "x" / "sessions"))
    monkeypatch.setenv("NEXUS_CONV_HERMES_DB", str(tmp_path / "h" / "state.db"))

    s = Settings.from_env()

    assert s.conv_claude_root == tmp_path / "c" / "projects"
    assert s.conv_codex_root == tmp_path / "x" / "sessions"
    assert s.conv_hermes_db == tmp_path / "h" / "state.db"


def test_a_window_longer_than_the_retention_refuses_to_start(tmp_path):
    first = message_of(conv_since_days=40, conv_retention_days=31)
    second = message_of(conv_since_days=3650, conv_retention_days=1)

    assert first == second == config._CONV_WINDOW_MESSAGE
    assert "NEXUS_CONV_SINCE_DAYS" in first and "NEXUS_CONV_RETENTION_DAYS" in first
    Settings(data_dir=tmp_path, conv_since_days=31, conv_retention_days=31)
    Settings(data_dir=tmp_path, conv_since_days=7, conv_retention_days=31)


@pytest.mark.parametrize(
    ("field", "refused", "admitted"),
    [
        ("conv_since_days", (0, -1, 3651), (1,)),
        ("conv_retention_days", (0, -1, 3651), (31, 3650)),
        ("conv_poll_seconds", (9, 0, -1, 3601), (10, 3600)),
    ],
)
def test_bounds_are_enforced_without_echo(tmp_path, field, refused, admitted):
    expected = config._CONV_BOUNDS[field][3]
    messages = {message_of(**{field: value}) for value in (*refused, True, 31.0, "31")}

    assert messages == {expected}
    assert FIELD_VARIABLE[field] in expected
    for value in admitted:
        assert getattr(Settings(data_dir=tmp_path, **{field: value}), field) == value
    # the upper bound of the window, with a retention that admits it
    s = Settings(data_dir=tmp_path, conv_since_days=3650, conv_retention_days=3650)
    assert s.conv_since_days == 3650


@pytest.mark.parametrize("name", ["NEXUS_CONV_SINCE_DAYS", "NEXUS_CONV_POLL_SECONDS"])
def test_a_non_integer_env_value_is_refused_without_echo(monkeypatch, tmp_path, name):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    field = next(f for f, v in FIELD_VARIABLE.items() if v == name)
    values = ("abc", "1.5", "1e3", "1_000", "+31", "٣١", "-4")

    messages = {env_message(monkeypatch, name, value) for value in values}

    assert messages == {config._CONV_BOUNDS[field][3]}


def test_an_empty_numeric_env_value_means_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_CONV_SINCE_DAYS", "")
    assert Settings.from_env().conv_since_days == 31

    monkeypatch.setenv("NEXUS_CONV_SINCE_DAYS", " 45 ")
    monkeypatch.setenv("NEXUS_CONV_RETENTION_DAYS", "45")
    s = Settings.from_env()
    assert (s.conv_since_days, s.conv_retention_days) == (45, 45)
