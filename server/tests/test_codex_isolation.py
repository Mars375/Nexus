"""The launch of a Codex run checks the isolation first, and an MCP call during the run stops it
(spec #186, §2.2, §3, §5.3, §5.4; tests C3 to C8 and C10, and Q5), after the version of Codex
(spec 2026-11-25, B). The real binary never runs."""

import json
import subprocess
import sys
import time

import pytest
from codex_support import (
    OK_LINES,
    THREAD,
    TURN,
    Rig,
    calls,
    git,
    mcp_call,
    run_info,
)

from nexus.adapters import codex_cli, codex_git, codex_process


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


# --- The nominal launch: the version, two control calls, then the run -----------------------------


def test_a_launch_asks_the_version_then_both_controls_in_the_worktree_then_runs(rig):
    r = rig(lines=OK_LINES)
    r.run()

    seen = calls(r.dir)
    assert [c["kind"] for c in seen] == ["version", "mcp_list", "prompt_input", "run"]
    assert seen[0]["args"] == ["--version"]
    assert seen[1]["args"][:3] == ["mcp", "list", "--json"]
    assert seen[2]["args"][:2] == ["debug", "prompt-input"] and seen[2]["args"][-1] == ""
    assert seen[3]["args"][:2] == ["exec", "--json"]
    assert r.home.is_dir()  # created by Nexus when missing


def test_the_controls_and_the_run_get_the_very_same_environment(rig, monkeypatch, tmp_path):
    secret = "ghp_" + "A" * 36
    for name, value in (("NEXUS_TOKEN", "nxt_" + "B" * 30), ("OPENAI_API_KEY", secret),
                        ("CODEX_HOME", str(tmp_path / "loic" / ".codex")),
                        ("GIT_DIR", str(tmp_path / "evil")), ("GIT_INDEX_FILE", "idx"),
                        ("git_work_tree", "w")):
        monkeypatch.setenv(name, value)
    r = rig(lines=OK_LINES)
    spawned = []
    real = codex_process.spawn

    def spy(argv, cwd, env, **kwargs):
        spawned.append((cwd, dict(env), kwargs))
        return real(argv, cwd, env, **kwargs)

    monkeypatch.setattr(codex_process, "spawn", spy)
    r.run()

    # `PWD` is set by the fake's `/bin/sh` launcher to its own folder: the version call runs from
    # the home of Nexus, the others from the worktree. Nexus never passes it (spawned envs below).
    envs = [{k: v for k, v in c["env"].items() if k != "PWD"} for c in calls(r.dir)]
    assert len(envs) == 4 and envs[0] == envs[1] == envs[2] == envs[3]
    assert len(spawned) == 4 and all(env == spawned[0][1] for _, env, _ in spawned)
    assert spawned[0][0] == str(r.data.resolve() / "codex-home")  # the version: no worktree yet
    assert {cwd for cwd, _, _ in spawned[1:]} == {
        str(r.data.resolve() / "worktrees" / "nx-run-1")}
    assert all(kw.get("contain") is True for _, _, kw in spawned)
    env = {k.upper(): v for k, v in envs[3].items()}
    assert not {n for n in env if n.startswith(("NEXUS_", "OPENAI_"))}
    assert env["CODEX_HOME"] == str(r.data.resolve() / "codex-home")
    assert env["GIT_CONFIG_COUNT"] == "2" and env["GIT_TERMINAL_PROMPT"] == "0"
    assert {"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"}.isdisjoint(env)
    assert secret not in json.dumps(envs)


@pytest.mark.skipif(sys.platform != "win32", reason="a `.cmd` launcher exists under Windows only")
def test_through_a_cmd_launcher_the_arguments_arrive_intact(rig):
    r = rig(lines=OK_LINES)
    assert r.bin.suffix == ".cmd"
    r.run()

    seen = calls(r.dir)
    args = seen[3]["args"]
    at = args.index("windows.sandbox=unelevated")
    assert args[at - 1] == "-c"
    assert "-c" in seen[1]["args"] and "windows.sandbox=unelevated" in seen[1]["args"]
    assert seen[2]["args"][-1] == ""  # the empty prompt survives the launcher


# --- C5: the home of Nexus holds nothing that would configure Codex -------------------------------


@pytest.mark.parametrize("entry", [
    "AGENTS.md", "agents.md", "AGENTS.override.md", "hooks.json", "config.toml", "x.config.toml",
    "skills/mine/SKILL.md", "rules/a.rules", "plugins/p", "memories/m",
])
def test_a_configured_home_of_nexus_refuses_the_launch(rig, entry):
    r = rig(lines=OK_LINES)
    path = r.home / entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")

    r.refused("CODEX_HOME")
    assert r.kinds() == ["version"]  # refused before any control call in the worktree


@pytest.mark.parametrize("entry", ["rules", "skills"])
def test_a_file_where_a_folder_is_expected_is_refused(rig, entry):
    r = rig(lines=OK_LINES)
    r.home.mkdir(parents=True)
    (r.home / entry).write_text("x", encoding="utf-8")
    r.refused()


def test_the_skills_codex_installs_itself_and_empty_folders_are_fine(rig):
    r = rig(lines=OK_LINES)
    (r.home / "skills" / ".system" / "x").mkdir(parents=True)
    for name in ("rules", "plugins", "memories"):
        (r.home / name).mkdir()
    (r.home / "auth.json").write_text("{}", encoding="utf-8")  # never read by Nexus

    r.run()
    assert r.kinds() == ["version", "mcp_list", "prompt_input", "run"]


def test_a_home_of_nexus_that_is_a_file_is_refused(rig):
    r = rig(lines=OK_LINES)
    r.data.mkdir(parents=True)
    r.home.write_text("x", encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        r.dispatch()
    assert "run" not in r.kinds()


# --- Q5: a project configuration of Codex in the repository ---------------------------------------


def test_a_repository_with_a_codex_folder_at_its_root_is_refused(rig):
    r = rig(lines=OK_LINES)
    (r.repo / ".codex").mkdir()
    (r.repo / ".codex" / "config.toml").write_text("[mcp_servers.x]\n", encoding="utf-8")
    git(r.repo, "add", ".codex")
    git(r.repo, "commit", "-q", "-m", "projet")

    r.refused(".codex")


# --- B: a version of Codex that was not measured (spec 2026-11-25) --------------------------------


@pytest.mark.parametrize("scenario", [
    {"version": "codex-cli 0.168.0\n"}, {"version": "codex-cli 0.167.1\nx\n"},
    {"version": ""}, {"version_exit": 1}, {"version_hang": True},
])
def test_a_version_that_was_not_measured_refuses_the_launch_before_the_worktree(rig, scenario):
    r = rig(lines=OK_LINES, **scenario)
    r.refused("version de Codex non relevée")  # no `nexus/` branch, no worktree folder
    assert r.kinds() == ["version"]  # neither `mcp list` nor `exec`


def test_a_version_call_whose_stop_is_not_confirmed_leaves_nothing_behind(rig, monkeypatch):
    r = rig(lines=OK_LINES)
    tries = never_stopped(monkeypatch, version=True)
    with pytest.raises(codex_cli.ControlNotStopped):
        r.dispatch()
    assert len(tries) == codex_cli.STOP_ATTEMPTS and r.kinds() == ["version"]
    assert not (r.data / "worktrees" / "nx-run-1").exists()
    assert git(r.repo, "branch", "--list", "nexus/*") == ""


# --- C6, C7: the answers of the control calls -----------------------------------------------------


@pytest.mark.parametrize("scenario", [
    {"mcp_list": json.dumps([{"name": "x"}])}, {"mcp_list": ""}, {"mcp_list": "pas du json"},
    {"mcp_list": "{}"}, {"mcp_list": "[]", "mcp_list_exit": 1}, {"mcp_list_hang": True},
])
def test_an_mcp_list_that_is_not_exactly_empty_refuses_the_launch(rig, scenario):
    r = rig(lines=OK_LINES, **scenario)
    r.refused("mcp")
    assert r.kinds() == ["version", "mcp_list"]


@pytest.mark.parametrize("scenario", [
    {"prompt_input": json.dumps([{"text": "<skills_instructions> a"}])},
    {"prompt_input": json.dumps([{"text": "x\n### Skill roots\n| a |"}])},
    {"prompt_input": json.dumps([{"text": "<skills_instructions>"}], ensure_ascii=True)
        .replace("<", "\\u003c")},
    {"prompt_input": "pas du json"}, {"prompt_input": ""},
    {"prompt_input_exit": 2}, {"prompt_input_hang": True},
])
def test_a_prompt_input_with_skills_or_unreadable_refuses_the_launch(rig, scenario):
    r = rig(lines=OK_LINES, **scenario)
    r.refused("prompt-input")
    assert r.kinds() == ["version", "mcp_list", "prompt_input"]


def test_a_marker_hidden_behind_a_json_escape_is_still_found(rig):
    escaped = json.dumps([{"text": "<skills_instructions>"}]).replace("<", "\\u003c")
    assert "<skills_instructions>" not in escaped and "\\u003c" in escaped
    r = rig(lines=OK_LINES, prompt_input=escaped)
    r.refused("prompt-input")


def test_a_hung_control_call_is_stopped_within_its_limit(rig):
    r = rig(lines=OK_LINES, mcp_list_hang=True)
    start = time.monotonic()
    r.refused("mcp")
    assert time.monotonic() - start < 15


def never_stopped(monkeypatch, *, version: bool = False):
    """The stop of the control calls in the worktree (or, with `version`, of the version call
    only) stays unconfirmed; the processes are still killed. The attempts, returned."""
    real_spawn, real_kill, targets, tries = codex_process.spawn, codex_process.kill_tree, [], []

    def spawn(argv, *args, **kwargs):
        process = real_spawn(argv, *args, **kwargs)
        if kwargs.get("stdin") == subprocess.DEVNULL and (argv[-1] == "--version") == version:
            targets.append(process)
        return process

    def kill_tree(process, *args, **kwargs):
        done = real_kill(process)
        if any(process is target for target in targets):
            tries.append(process)
            return False
        return done

    monkeypatch.setattr(codex_process, "spawn", spawn)
    monkeypatch.setattr(codex_process, "kill_tree", kill_tree)
    return tries


def test_a_control_call_whose_stop_is_not_confirmed_refuses_the_launch(rig, monkeypatch):
    """Tried again, then refused; the worktree stays (the call may still run there)."""
    r = rig(lines=OK_LINES)
    tries = never_stopped(monkeypatch)
    with pytest.raises(codex_cli.ControlNotStopped):
        r.dispatch()
    assert len(tries) == codex_cli.STOP_ATTEMPTS
    assert "run" not in r.kinds() and (r.data / "worktrees" / "nx-run-1").exists()



def unreadable_controls(monkeypatch):
    """The control calls in the worktree fail to be read (`communicate` raises); the version call
    and git are untouched."""
    real = codex_process.spawn

    def spawn(argv, *args, **kwargs):
        process = real(argv, *args, **kwargs)
        if kwargs.get("stdin") == subprocess.DEVNULL and argv[-1] != "--version":

            def broken(*a, **k):
                raise OSError("lecture impossible")

            process.communicate = broken
        return process

    monkeypatch.setattr(codex_process, "spawn", spawn)


def test_a_failed_read_with_an_unconfirmed_stop_still_keeps_the_worktree(rig, monkeypatch):
    """`communicate` raising does not hide an unconfirmed stop (#194, CodeRabbit)."""
    r = rig(lines=OK_LINES)
    unreadable_controls(monkeypatch)
    tries = never_stopped(monkeypatch)
    with pytest.raises(codex_cli.ControlNotStopped):
        r.dispatch()
    assert len(tries) == codex_cli.STOP_ATTEMPTS
    assert "run" not in r.kinds() and (r.data / "worktrees" / "nx-run-1").exists()


def test_a_failed_read_with_a_confirmed_stop_undoes_the_launch(rig, monkeypatch):
    r = rig(lines=OK_LINES)

    made, real = [], codex_git.create_worktree
    monkeypatch.setattr(codex_git, "create_worktree",
                        lambda *a, **k: made.append(1) or real(*a, **k))
    unreadable_controls(monkeypatch)
    with pytest.raises(OSError, match="lecture"):
        r.dispatch()
    assert made == [1]  # past the version: the worktree existed, then was undone
    assert not (r.data / "worktrees" / "nx-run-1").exists()
    assert git(r.repo, "branch", "--list", "nexus/*") == ""


# --- C8: locations, checked before any worktree exists --------------------------------------------


@pytest.fixture
def no_worktree(monkeypatch):
    """A refusal of location comes before `create_worktree`, not after it (then undone)."""
    def never(*args, **kwargs):
        raise AssertionError("create_worktree called despite a refused location")

    monkeypatch.setattr(codex_git, "create_worktree", never)


def test_a_repository_under_the_childs_temporary_directory_is_refused(
    rig, no_worktree, monkeypatch, tmp_path
):
    r = rig(lines=OK_LINES)
    monkeypatch.setenv("TEMP", str(tmp_path))
    r.refused("emplacement")
    assert r.kinds() == []


def test_a_temporary_directory_inside_the_repository_git_is_refused(rig, no_worktree, monkeypatch):
    r = rig(lines=OK_LINES)
    monkeypatch.setenv("TMP", str(r.repo / ".git" / "tmp"))
    r.refused("emplacement")
    assert r.kinds() == []


def test_the_home_of_nexus_under_tmpdir_is_refused(rig, no_worktree, monkeypatch):
    r = rig(lines=OK_LINES)
    monkeypatch.setenv("TMPDIR", str(r.data))
    r.refused("emplacement")


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive paths: Windows only")
def test_a_temporary_directory_in_another_case_is_still_refused(
    rig, no_worktree, monkeypatch, tmp_path
):
    r = rig(lines=OK_LINES)
    monkeypatch.setenv("TMP", str(tmp_path / "repo").upper())
    r.refused("emplacement")


def test_an_empty_or_absent_temporary_variable_is_ignored(rig, monkeypatch):
    r = rig(lines=OK_LINES)
    monkeypatch.setenv("TEMP", "")
    monkeypatch.delenv("TMP")
    r.run()
    assert r.kinds() == ["version", "mcp_list", "prompt_input", "run"]


# --- C10: an MCP tool call during the run stops it at once ----------------------------------------


@pytest.mark.parametrize("event", ["item.started", "item.completed"])
def test_an_mcp_call_kills_the_tree_and_fails_the_run(rig, event):
    r = rig(lines=[THREAD, TURN, mcp_call(event), mcp_call(event, tool="x")], hang=True)
    r.dispatch()
    r.adapter.join("nx-run-1", 20)  # the reader ends once the tree is killed, not at the limit

    assert r.adapter.is_finished("nx-run-1")
    result = r.adapter.watch(run_info(1, external_ref="x"))
    last = result.events[-1]
    assert last.kind == "failed" and last.subject == "Isolation de la session non respectée"
    assert last.payload["cause"] == "isolation non respectée : outil MCP appelé"
    assert [e.kind for e in result.events] == ["claimed", "working", "failed"]


def test_nothing_is_recorded_after_the_breach(rig):
    r = rig(lines=[THREAD, mcp_call(), TURN, OK_LINES[2]], hang=True)
    result = r.run()
    assert [e.kind for e in result.events] == ["claimed", "failed"]


def test_a_finished_turn_after_an_mcp_call_is_never_done(rig):
    r = rig(lines=[THREAD, TURN, mcp_call(), OK_LINES[-1]], commit=True)
    last = r.run().events[-1]
    assert last.kind == "failed" and "outil MCP" in last.payload["cause"]


def test_an_unconfirmed_stop_after_a_breach_keeps_the_run_open(rig, monkeypatch):
    r = rig(lines=[THREAD, TURN, mcp_call()], hang=True)
    real = codex_process.kill_tree
    try:
        r.dispatch()
        monkeypatch.setattr(codex_process, "kill_tree", lambda *a, **k: False)
        job = r.adapter._job("nx-run-1")
        deadline = time.monotonic() + 20
        while job.breach is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert job.breach is not None
        with pytest.raises(RuntimeError):
            r.adapter.watch(run_info(1, external_ref="x"))
        assert not job.settled
    finally:
        monkeypatch.setattr(codex_process, "kill_tree", real)
    last = r.adapter.watch(run_info(1, external_ref="x")).events[-1]
    assert last.kind == "failed" and "outil MCP" in last.payload["cause"]


def test_every_spawn_of_a_launch_is_contained_and_the_controls_read_no_stdin(rig, monkeypatch):
    r = rig(lines=OK_LINES)
    seen = []
    real = codex_process.spawn
    monkeypatch.setattr(codex_process, "spawn",
                        lambda *a, **k: seen.append(k) or real(*a, **k))
    r.run()
    assert len(seen) == 4 and all(k.get("contain") is True for k in seen)
    assert all(k.get("stdin") == subprocess.DEVNULL for k in seen[:3])
