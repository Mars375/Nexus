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


@pytest.mark.parametrize("hosts", [
    ("127.0.0.1",), ("localhost",), ("::1",), ("100.64.0.1",), ("100.127.255.254",),
    ("fd7a:115c:a1e0::1",), ("127.0.0.1", "100.101.102.103"),
])
def test_accepts_bind_lists(tmp_path, hosts):
    settings = Settings(data_dir=tmp_path, hosts=hosts)
    loopback = [h for h in hosts if h in ("127.0.0.1", "localhost", "::1")]
    assert settings.hosts == (tuple(loopback) or ("127.0.0.1",)) + tuple(
        h for h in hosts if h not in loopback
    )


def test_a_lone_tailnet_address_gets_the_loopback(tmp_path):
    settings = Settings(data_dir=tmp_path, hosts=("100.101.102.103",))
    assert settings.hosts == ("127.0.0.1", "100.101.102.103")
    assert settings.loopback_host == "127.0.0.1"
    assert settings.tailnet_host == "100.101.102.103"
    assert settings.host_literals == frozenset({"127.0.0.1", "100.101.102.103"})


def test_ipv6_tailnet_address_is_normalized(tmp_path):
    settings = Settings(data_dir=tmp_path, hosts=("fd7a:115c:a1e0:0:0:0:0:1",))
    assert settings.tailnet_host == "fd7a:115c:a1e0::1"


def test_localhost_is_not_a_host_literal(tmp_path):
    settings = Settings(data_dir=tmp_path, hosts=("LocalHost",))
    assert settings.hosts == ("localhost",)
    assert settings.host_literals == frozenset()
    assert settings.tailnet_host is None


@pytest.mark.parametrize("hosts", [
    ("0.0.0.0",), ("::",), ("",), ("100.63.255.255",), ("100.128.0.0",), ("192.168.1.10",),
    ("10.0.0.1",), ("fd7a:115c:a1e1::1",), ("helios.ts.net",), ("100.64.0.1:8765",),
    ("[fd7a:115c:a1e0::1]",), ("::ffff:100.64.0.1",), ("fe80::1%eth0",), ("１００.64.0.1",),
    ("fd7a:115c:a1e0::1%eth0",), ("100.64.0.1\n",),
    ("100.64.0.1", "100.64.0.2"), ("127.0.0.1", "::1"), ("localhost", "127.0.0.1"),
    ("127.0.0.1", "127.0.0.1"), (),
])
def test_refuses_bind_values_without_echo(tmp_path, hosts):
    with pytest.raises(ValueError, match="NEXUS_HOST") as error:
        Settings(data_dir=tmp_path, hosts=hosts)
    message = str(error.value)
    # The message is fixed text: the same for every refusal, so it cannot repeat a received value.
    with pytest.raises(ValueError) as reference:
        Settings(data_dir=tmp_path, hosts=("0.0.0.0",))
    assert message == str(reference.value)
    for entry in hosts:
        if entry and entry not in reference.value.args[0]:
            assert entry not in message
    assert "#57" not in message
    assert "PR B" not in message


def test_bind_list_is_read_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_HOST", " 127.0.0.1 , 100.101.102.103 ")
    assert Settings.from_env().hosts == ("127.0.0.1", "100.101.102.103")
    monkeypatch.setenv("NEXUS_HOST", "100.64.0.1\n")
    assert Settings.from_env().tailnet_host == "100.64.0.1"
    for bad in ("0.0.0.0", "127.0.0.1,,100.64.0.1"):
        monkeypatch.setenv("NEXUS_HOST", bad)
        with pytest.raises(ValueError, match="NEXUS_HOST"):
            Settings.from_env()


def test_default_bind_is_ipv4_loopback(tmp_path):
    assert Settings(data_dir=tmp_path).hosts == ("127.0.0.1",)


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
