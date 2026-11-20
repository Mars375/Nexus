"""What the Codex adapter hands to the child, as pure functions (spec #186, §2.2, §2.4, §3.2, §5.2,
§5.5, §5.4; tests C1, C2, C4, C8 and C9). Nothing here starts a process."""

import json
import os
import re
import sys
from pathlib import Path

import pytest
from codex_support import mcp_call

from nexus.adapters import codex_cli
from nexus.adapters.codex_translate import translate_line

BIN, TREE = "C:/x/codex.cmd", "D:/data/worktrees/nx-run-1"

FLAGS = [
    "-c", "skills.include_instructions=false", "-c", "skills.bundled.enabled=false",
    "--disable", "hooks", "--disable", "plugins", "--disable", "remote_plugin",
    "--disable", "apps", "--disable", "memories", "--disable", "browser_use",
    "--disable", "computer_use", "--disable", "in_app_browser", "--disable", "tool_suggest",
    "--disable", "skill_mcp_dependency_install", "--disable", "skill_search",
]

# --- C1, C2: the command line ---------------------------------------------------------------------


def test_the_run_argv_under_windows_is_exactly_the_framed_one():
    assert codex_cli.argv(BIN, TREE, windows=True) == [
        BIN, "exec", "--json", "--sandbox", "workspace-write", "--ephemeral",
        "--ignore-user-config", "--ignore-rules", "-c", "windows.sandbox=unelevated", *FLAGS,
        "--cd", TREE, "-",
    ]


def test_the_run_argv_elsewhere_is_the_same_without_the_windows_sandbox():
    assert codex_cli.argv(BIN, TREE, windows=False) == [
        BIN, "exec", "--json", "--sandbox", "workspace-write", "--ephemeral",
        "--ignore-user-config", "--ignore-rules", *FLAGS, "--cd", TREE, "-",
    ]


def test_the_control_calls_carry_the_same_overrides_as_the_run():
    for windows in (True, False):
        flags = codex_cli.overrides(windows=windows)
        run = codex_cli.argv(BIN, TREE, windows=windows)
        assert run[8:8 + len(flags)] == flags
        assert codex_cli.mcp_list_argv(BIN, windows=windows) == [
            BIN, "mcp", "list", "--json", *flags]
        assert codex_cli.prompt_input_argv(BIN, windows=windows) == [
            BIN, "debug", "prompt-input", *flags, ""]


@pytest.mark.parametrize("windows", [True, False])
def test_no_argument_holds_anything_cmd_exe_would_read_again(windows):
    run = codex_cli.argv(BIN, TREE, windows=windows)
    controls = (codex_cli.mcp_list_argv(BIN, windows=windows)[1:]
                + codex_cli.prompt_input_argv(BIN, windows=windows)[1:-1])
    for arg in [a for a in run[1:] if a != TREE] + controls:
        assert re.fullmatch(r"[A-Za-z0-9_.=-]+", arg), arg


@pytest.mark.parametrize("windows", [True, False])
def test_no_bypass_no_extra_root_no_profile_and_never_the_brief(windows):
    run = codex_cli.argv(BIN, TREE, windows=windows)
    for banned in ("--add-dir", "--dangerously-bypass-approvals-and-sandbox",
                   "--dangerously-bypass-hook-trust", "danger-full-access", "--search", "-p",
                   "--profile", "--skip-git-repo-check"):
        assert banned not in run
    assert run[-1] == "-"  # the brief is read from stdin


# --- C4: the environment of the child -------------------------------------------------------------


def shell_env(tmp_path: Path) -> dict[str, str]:
    secret = "ghp_" + "A" * 36
    return {
        "PATH": "/bin", "SYSTEMROOT": "C:/Windows", "TEMP": str(tmp_path / "t"),
        "NEXUS_TOKEN": "nxt_" + "B" * 30, "OPENAI_API_KEY": secret, "openai_base_url": "x",
        "CODEX_HOME": str(tmp_path / "loic" / ".codex"), "codex_home": "y",
        "GIT_DIR": str(tmp_path / "evil"), "GIT_INDEX_FILE": "i", "git_dir": "z",
        "Git_Config_Count": "9", "GIT_CONFIG_KEY_0": "core.pager", "GITHUB_TOKEN": secret,
    }


def test_the_child_environment_drops_every_secret_and_inherited_git_variable(tmp_path):
    home = tmp_path / "data" / "codex-home"
    env = codex_cli.child_env(shell_env(tmp_path), home)

    upper = {k.upper() for k in env}
    assert not {n for n in upper if n.startswith(("NEXUS_", "OPENAI_", "GITHUB_"))}
    assert [k for k in env if k.upper() == "CODEX_HOME"] == ["CODEX_HOME"]
    assert env["CODEX_HOME"] == str(home)
    assert {k: v for k, v in env.items() if k.upper().startswith("GIT_")} == {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": os.devnull,
        "GIT_CONFIG_KEY_1": "core.fsmonitor", "GIT_CONFIG_VALUE_1": "false",
        "GIT_TERMINAL_PROMPT": "0",
    }
    assert env["PATH"] == "/bin" and env["TEMP"] == str(tmp_path / "t")


def test_the_allow_list_is_the_shared_one_without_codex_home():
    assert "CODEX_HOME" not in codex_cli.CODEX_ENV_ALLOW
    assert {"PATH", "TEMP", "TMP", "TMPDIR", "USERPROFILE"} <= codex_cli.CODEX_ENV_ALLOW


# --- C8: where the git directories and the home of Nexus may lie ----------------------------------


def places(tmp_path: Path) -> dict:
    return {
        "common_dir": tmp_path / "repo" / ".git",
        "gitdir": tmp_path / "repo" / ".git" / "worktrees" / "nx-run-1",
        "codex_home": tmp_path / "data" / "codex-home",
        "worktree": tmp_path / "data" / "worktrees" / "nx-run-1",
    }


def test_separate_folders_are_accepted(tmp_path):
    env = {"TEMP": str(tmp_path / "tmp"), "TMP": str(tmp_path / "tmp2")}
    codex_cli.check_locations(env, **places(tmp_path))


@pytest.mark.parametrize("name", ["TEMP", "TMP", "TMPDIR"])
@pytest.mark.parametrize("target", ["common_dir", "gitdir", "codex_home"])
def test_a_checked_folder_under_a_temporary_directory_is_refused(tmp_path, name, target):
    where = places(tmp_path)
    for parent in (where[target], where[target].parent):  # equal, then under
        with pytest.raises(ValueError, match="emplacement"):
            codex_cli.check_locations({name: str(parent)}, **where)


@pytest.mark.parametrize("target", ["common_dir", "gitdir", "codex_home"])
def test_a_checked_folder_inside_the_worktree_is_refused(tmp_path, target):
    where = places(tmp_path)
    where[target] = where["worktree"] / "inner"
    with pytest.raises(ValueError, match="emplacement"):
        codex_cli.check_locations({}, **where)


def test_the_name_of_a_temporary_variable_is_read_whatever_its_case(tmp_path):
    where = places(tmp_path)
    with pytest.raises(ValueError):
        codex_cli.check_locations({"Temp": str(tmp_path / "repo")}, **where)


def test_the_paths_are_compared_resolved(tmp_path):
    where = places(tmp_path)
    (tmp_path / "x").mkdir()
    with pytest.raises(ValueError):
        codex_cli.check_locations({"TMP": str(tmp_path / "x" / ".." / "data")}, **where)


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive paths: Windows only")
def test_under_windows_the_case_does_not_hide_a_temporary_directory(tmp_path):
    where = places(tmp_path)
    with pytest.raises(ValueError):
        codex_cli.check_locations({"TEMP": str(tmp_path / "REPO").upper()}, **where)


def test_an_empty_temporary_variable_is_ignored_and_no_gitdir_is_fine(tmp_path):
    where = places(tmp_path) | {"gitdir": None}
    codex_cli.check_locations({"TEMP": "", "TMP": "   "}, **where)


def test_a_sibling_whose_name_starts_like_the_temporary_directory_is_not_under_it(tmp_path):
    where = places(tmp_path)
    codex_cli.check_locations({"TEMP": str(tmp_path / "rep")}, **where)


@pytest.mark.skipif(sys.platform == "win32", reason="/tmp is a writable root under POSIX only")
def test_under_posix_a_repository_under_slash_tmp_is_refused_whatever_tmpdir(tmp_path):
    where = places(tmp_path) | {"common_dir": Path("/tmp/nexus-repo/.git"), "gitdir": None}
    with pytest.raises(ValueError, match="emplacement"):
        codex_cli.check_locations({"TMPDIR": str(tmp_path / "elsewhere")}, **where)


def test_the_test_folders_are_not_under_the_childs_temporary_directory(tmp_path):
    """The autouse fixture of conftest: a sibling of `tmp_path`, never a parent."""
    temp = Path(os.environ["TEMP"]).resolve()
    assert os.environ["TMP"] == os.environ["TMPDIR"] == os.environ["TEMP"]
    assert not tmp_path.resolve().is_relative_to(temp)
    assert not temp.is_relative_to(tmp_path.resolve())


# --- C9: an MCP tool call during the run is a breach ----------------------------------------------


@pytest.mark.parametrize("event", ["item.started", "item.completed"])
def test_an_mcp_tool_call_is_a_breach_in_fixed_words(event):
    secret = "ghp_" + "A" * 36
    fact = translate_line(mcp_call(event, server=f"srv-{secret}", tool=f"tool-{secret}"))

    assert fact is not None and fact.kind == "breach"
    assert fact.body == "isolation non respectée : outil MCP appelé"
    assert secret not in json.dumps([fact.kind, fact.subject, fact.body])
    assert "srv" not in fact.body and "tool-" not in fact.body


def test_other_started_items_and_unknown_types_still_say_nothing():
    for item in ({"type": "agent_message", "text": "x"}, {"type": "something_new"}):
        assert translate_line(json.dumps({"type": "item.started", "item": item})) is None
    assert translate_line(json.dumps({"type": "item.completed", "item": {"type": "web_search"}}
                                     )) is None
