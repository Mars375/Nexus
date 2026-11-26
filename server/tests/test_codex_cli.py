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
    "-c", "web_search=disabled",
    "--disable", "hooks", "--disable", "plugins", "--disable", "remote_plugin",
    "--disable", "apps", "--disable", "memories", "--disable", "browser_use",
    "--disable", "computer_use", "--disable", "in_app_browser", "--disable", "tool_suggest",
    "--disable", "skill_mcp_dependency_install", "--disable", "skill_search",
    "--disable", "standalone_web_search",
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
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    assert env["PATH"] == "/bin" and env["TEMP"] == str(tmp_path / "t")


def test_an_inherited_git_config_scope_is_replaced(tmp_path):
    """The git of `codex.exe` reads what `check_no_filter_driver` reads (spec 2026-11-25, A)."""
    shell = {"PATH": "/bin", "GIT_CONFIG_NOSYSTEM": "0", "git_config_global": "x",
             "GIT_CONFIG_GLOBAL": str(tmp_path / "loic.gitconfig")}
    env = codex_cli.child_env(shell, tmp_path / "home")
    scope = {k: v for k, v in env.items() if k.upper() in ("GIT_CONFIG_NOSYSTEM",
                                                           "GIT_CONFIG_GLOBAL")}
    assert scope == {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


# --- B: only a measured version of Codex is launched (spec 2026-11-25) ----------------------------


def answer_version(monkeypatch, output):
    """`_control` replaced: `output` is what it returns (None: a non-zero code or an overrun)."""
    seen = []

    def control(argv_, cwd, env, timeout):
        seen.append((argv_, cwd, env, timeout))
        return output

    monkeypatch.setattr(codex_cli, "_control", control)
    return seen


def test_the_measured_version_is_accepted_through_one_bounded_control_call(monkeypatch, tmp_path):
    seen = answer_version(monkeypatch, "codex-cli 0.167.1\n")
    env = {"CODEX_HOME": str(tmp_path)}
    codex_cli.check_version(BIN, tmp_path, env, timeout=7.0)
    assert seen == [([BIN, "--version"], tmp_path, env, 7.0)]
    assert codex_cli.MEASURED_VERSIONS == frozenset({"codex-cli 0.167.1"})


@pytest.mark.parametrize("output", [
    "codex-cli 0.168.0\n", "codex-cli 0.167.1\nx\n", " codex-cli 0.167.1\n", "codex-cli 0.167.1",
    "codex-cli 0.167.1 \n", "", None,
])
def test_any_other_version_answer_is_refused_in_fixed_words(monkeypatch, tmp_path, output):
    answer_version(monkeypatch, output)
    with pytest.raises(ValueError) as refused:
        codex_cli.check_version(BIN, tmp_path, {})
    assert str(refused.value) == "contrôle d'isolement : version de Codex non relevée"


def test_the_fake_codex_of_the_e2e_prints_a_measured_version():
    """A version change must not break the e2e silently: its fake answers one that is accepted."""
    fake = Path(__file__).parents[2] / "web" / "e2e" / "fake-codex.mjs"
    printed = re.findall(r"answer\('(codex-cli [^']*)'\)", fake.read_text(encoding="utf-8"))
    assert len(printed) == 1 and printed[0] in codex_cli.MEASURED_VERSIONS


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


@pytest.mark.parametrize("name", ["TEMP", "TMP", "TMPDIR"])
@pytest.mark.parametrize("target", ["common_dir", "gitdir", "codex_home"])
def test_a_temporary_directory_inside_a_checked_folder_is_refused(tmp_path, name, target):
    """The other way round (review of PR C): a writable temporary root inside a git directory or
    the home of Nexus would open that part of it to the agent."""
    where = places(tmp_path)
    for inner in (where[target], where[target] / "tmp"):  # equal, then under
        with pytest.raises(ValueError, match="emplacement"):
            codex_cli.check_locations({name: str(inner)}, **where)


def test_before_the_worktree_a_temporary_directory_inside_the_repository_git_is_refused(tmp_path):
    where = places(tmp_path) | {"gitdir": None}  # the first call, before `create_worktree`
    inside = where["common_dir"] / "worktrees" / "nx-run-1"
    with pytest.raises(ValueError, match="emplacement"):
        codex_cli.check_locations({"TEMP": str(inside)}, **where)


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


@pytest.mark.parametrize("value", ["tmp", "../repo/.git", "."])
def test_a_relative_temporary_directory_is_refused(tmp_path, value):
    """Codex would resolve it from the worktree, not from the server's folder (#194)."""
    with pytest.raises(ValueError, match="relatif"):
        codex_cli.check_locations({"TMPDIR": value}, **places(tmp_path))


@pytest.mark.skipif(sys.platform != "win32", reason="a .cmd launcher exists under Windows only")
@pytest.mark.parametrize("char", sorted(codex_cli.CMD_SPECIAL))
def test_under_windows_a_worktree_path_cmd_would_read_again_is_refused(tmp_path, char):
    where = places(tmp_path) | {"worktree": tmp_path / f"da{char}ta" / "worktrees" / "nx-run-1"}
    with pytest.raises(ValueError, match="caractère spécial"):
        codex_cli.check_locations({}, **where)


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
    assert translate_line(json.dumps({"type": "item.completed", "item": {"type": "something_new"}}
                                     )) is None
