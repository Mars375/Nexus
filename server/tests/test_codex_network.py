"""The network probe of a Codex run under Windows (#207, spec 2026-11-26, §4 and §5): MXC strict,
the same sandbox pair for the controls and the run, and a probe that fails closed. The probe's
command is never run: the fake `codex` replays the answer of the scenario."""

import json
import logging
import socket
import sys
import time

import pytest
from codex_support import LAUNCH_KINDS, OK_LINES, Rig, calls, make_fake_codex

from nexus.adapters import codex_cli, codex_network, codex_process

TREE = "D:/data/worktrees/nx-run-1"
PY = "C:/nexus/server/.venv/Scripts/python.exe"
SANDBOX = ["-c", "windows.sandbox=mxc", "-c", "sandbox_workspace_write.network_access=false"]
REFUSED = "le réseau du bac à sable n'est pas coupé"

# --- The command line and the probe's code --------------------------------------------------------


def test_the_sandbox_pair_is_mxc_strict_and_pins_the_network_off():
    assert list(codex_cli.WINDOWS_SANDBOX) == SANDBOX
    flags = codex_cli.overrides(windows=True)
    assert flags[:4] == SANDBOX
    joined = " ".join(flags + codex_network.probe_argv("codex", TREE, PY))
    assert "unelevated" not in joined and "prefer_mxc" not in joined and "elevated" not in joined


@pytest.mark.parametrize("windows", [True, False])
def test_the_approval_policy_is_pinned_to_never_for_the_run_and_the_controls(windows):
    for argv in (codex_cli.argv("codex", TREE, windows=windows),
                 codex_cli.mcp_list_argv("codex", windows=windows),
                 codex_cli.prompt_input_argv("codex", windows=windows)):
        at = argv.index("approval_policy=never")
        assert argv[at - 1] == "-c"


def test_the_probe_argv_is_exactly_the_framed_one():
    assert codex_network.probe_argv("C:/x/codex.cmd", TREE, PY) == [
        "C:/x/codex.cmd", "sandbox", "-C", TREE, "-P", ":workspace", *SANDBOX,
        "--", PY, "-I", "-c", codex_network.PROBE,
    ]


def test_the_probe_crosses_a_cmd_launcher_as_one_quoted_line():
    """One physical line, quoted by `list2cmdline` (a space), and nothing `cmd.exe` would read
    again even inside quotes: no `"`, `%`, `!`, `^`, `&`, `|`, `<`, `>`."""
    probe = codex_network.PROBE
    assert "\n" not in probe and "\r" not in probe and " " in probe
    assert not set(probe) & set('"%!^&|<>')


def test_the_probe_only_targets_test_net_and_prints_the_windows_error(monkeypatch, capsys):
    seen = []

    def refused(address, timeout):
        seen.append((address, timeout))
        error = PermissionError(13, "refusé")
        error.winerror = 10013
        raise error

    monkeypatch.setattr(socket, "create_connection", refused)
    exec(codex_network.PROBE, {})  # the very code handed to the sandbox, with a stubbed socket
    assert seen == [(("192.0.2.1", 443), 3)]
    assert capsys.readouterr().out == "ERR 10013\n"


def test_a_connection_that_goes_through_prints_something_else(monkeypatch, capsys):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: None)
    exec(codex_network.PROBE, {})
    assert capsys.readouterr().out == "CONNECTE\n"


# --- The probe against the fake: only `ERR 10013` and code 0 pass --------------------------------


def probe(tmp_path, *, timeout=5.0, **scenario):
    fake = make_fake_codex(tmp_path / "fake", **scenario)
    tree = tmp_path / "tree"
    tree.mkdir(exist_ok=True)
    env = codex_process.child_env()
    codex_network.check_network_cut(str(fake), tree, env, timeout=timeout)
    return fake, tree


def test_err_10013_passes_and_the_arguments_arrive_intact(tmp_path):
    fake, tree = probe(tmp_path)
    seen = calls(fake.parent)
    assert [c["kind"] for c in seen] == ["sandbox"]
    assert seen[0]["args"] == codex_network.probe_argv(str(fake), tree)[1:]
    assert seen[0]["args"][-1] == codex_network.PROBE  # through the `.cmd` launcher on Windows


@pytest.mark.parametrize("scenario", [
    {"sandbox": "CONNECTE\n"},
    {"sandbox": "ERR None\n"},  # the timeout of `unelevated` (3 s measured)
    {"sandbox": "ERR 10061\n"},
    {"sandbox": ""},
    {"sandbox": "ERR 10013"},
    {"sandbox": " ERR 10013\n"},
    {"sandbox": "ERR 10013\nERR 10013\n"},
    {"sandbox": "ERR 10013\nautre ligne\n"},
    {"sandbox": "ERR 10013\n", "sandbox_exit": 1},
    {"sandbox": "error: MXC indisponible\n", "sandbox_exit": 1},  # MXC missing: no fallback
])
def test_anything_but_err_10013_refuses_the_launch_in_fixed_words(tmp_path, scenario):
    with pytest.raises(ValueError, match=REFUSED) as caught:
        probe(tmp_path, **scenario)
    assert str(caught.value) == f"contrôle réseau : {REFUSED}"
    seen = calls(tmp_path / "fake")
    assert [c["kind"] for c in seen] == ["sandbox"]  # tried once, never again with another engine
    assert "unelevated" not in json.dumps([c["args"] for c in seen])


def test_a_probe_that_overruns_its_limit_is_stopped_and_refused(tmp_path):
    start = time.monotonic()
    with pytest.raises(ValueError, match=REFUSED):
        probe(tmp_path, timeout=1.0, sandbox_hang=True)
    assert time.monotonic() - start < 15


def test_a_probe_whose_stop_is_not_confirmed_keeps_the_worktree(tmp_path, monkeypatch):
    tries, real = [], codex_process.kill_tree

    def kill_tree(process, *args, **kwargs):
        real(process)
        tries.append(process)
        return False

    monkeypatch.setattr(codex_process, "kill_tree", kill_tree)
    with pytest.raises(codex_cli.ControlNotStopped):
        probe(tmp_path)
    assert len(tries) == codex_cli.STOP_ATTEMPTS


@pytest.mark.skipif(sys.platform != "win32", reason="a `.cmd` launcher exists under Windows only")
@pytest.mark.parametrize("char", sorted(codex_cli.CMD_SPECIAL))
def test_an_interpreter_path_cmd_would_read_again_is_refused_before_any_call(tmp_path, char):
    fake = make_fake_codex(tmp_path / "fake")
    with pytest.raises(ValueError, match="caractère spécial"):
        codex_network.check_network_cut(str(fake), tmp_path, {}, python=f"C:/py{char}/python.exe")
    assert calls(fake.parent) == []


def test_the_output_of_the_probe_is_never_logged_nor_told(tmp_path, caplog):
    marker = "SORTIE-DE-LA-SONDE-" + "Z" * 12
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError) as caught:
            probe(tmp_path, sandbox=marker + "\n")
    assert marker not in str(caught.value) and caught.value.__context__ is None
    assert not any(marker in r.getMessage() for r in caplog.records)


# --- The launch: the probe runs after the controls, before the run, under Windows only -----------

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the probe is Windows only")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


@windows_only
def test_a_launch_probes_the_network_in_the_worktree_then_runs(rig):
    r = rig(lines=OK_LINES)
    r.run()
    seen = calls(r.dir)
    assert [c["kind"] for c in seen] == LAUNCH_KINDS
    tree = r.data.resolve() / "worktrees" / "nx-run-1"
    sandbox, run = seen[3], seen[4]
    assert sandbox["args"] == codex_network.probe_argv(str(r.bin), tree)[1:]
    for call in (seen[1], seen[2], run):  # the controls and `exec` get the same pair
        assert call["args"][call["args"].index("windows.sandbox=mxc") + 2:][:1] == [
            "sandbox_workspace_write.network_access=false"]
        assert "approval_policy=never" in call["args"]


@windows_only
@pytest.mark.parametrize("scenario", [
    {"sandbox": "CONNECTE\n"}, {"sandbox": "", "sandbox_exit": 1}, {"sandbox_hang": True},
])
def test_a_network_not_cut_refuses_the_launch_without_any_model(rig, scenario):
    r = rig(lines=OK_LINES, **scenario)
    r.refused(REFUSED)  # no `exec`, no worktree, no `nexus/` branch left
    assert r.kinds() == ["version", "mcp_list", "prompt_input", "sandbox"]


def test_outside_windows_there_is_neither_probe_nor_sandbox_pair(rig, monkeypatch):
    run = codex_cli.argv("codex", TREE, windows=False)
    assert "windows.sandbox=mxc" not in run and "sandbox" not in run
    if sys.platform != "win32":
        r = rig(lines=OK_LINES)
        r.run()
        assert r.kinds() == LAUNCH_KINDS == ["version", "mcp_list", "prompt_input", "run"]
