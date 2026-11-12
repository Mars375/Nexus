"""The command line, the settings file, the instruction and the environment of the child
(spec 2026-11-11, §3.1, §3.2, §3.3, §3.5; tests 13 to 16 and 64)."""

import json
import os
import re

import pytest

from nexus.adapters import claude_code_cli as cli
from nexus.adapters import run_commit
from nexus.runs.rules import RUN_MODELS

SETTINGS = {
    "disableAllHooks": True,
    "permissions": {
        "allow": ["Read", "Glob", "Grep", "Edit", "Write"],
        "deny": [
            "Edit(.git)", "Write(.git)", "Edit(.git/**)", "Write(.git/**)",
            "Edit(**/.git)", "Write(**/.git)", "Edit(**/.git/**)", "Write(**/.git/**)",
        ],
    },
}


# --- 13, 14: the command line ---------------------------------------------------------------------


@pytest.mark.parametrize("model", ["haiku", "sonnet", "opus"])
def test_the_argv_is_exactly_the_one_of_the_spec(model):
    assert cli.argv("/x/claude", model, "/data/claude-code/nx-run-1.settings.json") == [
        "/x/claude", "-p", "--output-format", "stream-json", "--verbose", "--model", model,
        "--restricted", "--strict-mcp-config", "--disable-slash-commands",
        "--no-session-persistence", "--tools", "Read,Edit,Write,Glob,Grep",
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--settings", "/data/claude-code/nx-run-1.settings.json",
    ]


def test_nothing_that_widens_the_session_is_ever_in_the_argv():
    flat = " ".join(cli.argv("claude", "opus", "s.json")).lower()
    for excluded in ("--bare", "dangerously", "bypass", "acceptedits", "--allowedtools",
                     "--disallowedtools", "--fallback-model", "--max-turns", "--max-budget",
                     "--safe-mode", "--worktree", " -w ", "--effort", "bash", "powershell",
                     "webfetch", "--mcp-config", "auto"):
        assert excluded not in flat, excluded


def test_the_brief_is_not_an_argument():
    assert "Fais le travail" not in " ".join(cli.argv("claude", "sonnet", "s.json"))


@pytest.mark.parametrize("model", [
    "fable", "", None, "opus --dangerously-skip-permissions", "Opus", "sonnet[1m]", "best", 3,
])
def test_an_unknown_model_is_refused_before_any_process(model):
    with pytest.raises(ValueError) as error:
        cli.argv("claude", model, "s.json")
    assert "dangerously" not in str(error.value)


def test_the_models_are_the_closed_list_of_the_rules():
    assert cli.MODELS == RUN_MODELS == ("haiku", "sonnet", "opus")


# --- 15: the settings file ------------------------------------------------------------------------


def test_the_settings_file_is_the_constant_of_the_spec(tmp_path):
    path = cli.write_settings(tmp_path / "data" / "claude-code", "nx-run-7")
    assert path.name == "nx-run-7.settings.json" and path.parent.name == "claude-code"
    assert json.loads(path.read_text(encoding="utf-8")) == SETTINGS
    assert cli.SETTINGS == SETTINGS
    assert "Bash" not in path.read_text(encoding="utf-8")


def test_the_settings_file_is_never_written_for_a_strange_reference(tmp_path):
    for bad in ("../nx-run-1", "nx-run-0", "nx-run-1/../x", "x"):
        with pytest.raises(ValueError):
            cli.write_settings(tmp_path, bad)
    assert list(tmp_path.iterdir()) == []


# --- 16: the environment of the child -------------------------------------------------------------

FORBIDDEN = [
    "NEXUS_TOKEN", "NEXUS_DATA_DIR", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_ENTRYPOINT",
    "CODEX_HOME", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_AUTHOR_NAME",
    "GITHUB_TOKEN", "OPENAI_API_KEY",
]
KEPT = ["PATH", "USERPROFILE", "HOME", "SYSTEMROOT", "CLAUDE_CONFIG_DIR",
        "CLAUDE_CODE_GIT_BASH_PATH", "APPDATA"]


def test_the_environment_is_an_allow_list_with_imposed_git_values(tmp_path):
    source = {name: "inherited" for name in FORBIDDEN + KEPT}
    source.update({name.lower(): "inherited" for name in FORBIDDEN})
    gitdir, tree = tmp_path / "repo" / ".git" / "worktrees" / "nx-run-1", tmp_path / "wt"

    env = cli.child_env(source, gitdir=gitdir, worktree=tree)

    names = {name.upper() for name in env}
    assert not names & set(FORBIDDEN) - {"GIT_DIR", "GIT_WORK_TREE"}
    assert not any(n.startswith(("NEXUS_", "ANTHROPIC_")) for n in names)
    assert not any(n.startswith("CLAUDE_CODE_") and n != "CLAUDE_CODE_GIT_BASH_PATH" for n in names)
    assert "CLAUDECODE" not in names and "CODEX_HOME" not in names
    for kept in KEPT:
        assert env[kept] == "inherited"
    assert env["GIT_DIR"] == str(gitdir) and env["GIT_WORK_TREE"] == str(tree)
    assert env["GIT_CONFIG_COUNT"] == "3"
    pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(3)}
    assert pairs == {"core.hooksPath": os.devnull, "core.fsmonitor": "false",
                     "commit.gpgsign": "false"}
    assert env["GIT_EDITOR"] == ":" and env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["DISABLE_AUTOUPDATER"] == "1"


def test_an_inherited_git_variable_never_beats_the_imposed_one(tmp_path):
    env = cli.child_env({"GIT_DIR": "elsewhere", "GIT_CONFIG_COUNT": "9"},
                        gitdir=tmp_path / "g", worktree=tmp_path / "w")
    assert env["GIT_DIR"] == str(tmp_path / "g") and env["GIT_CONFIG_COUNT"] == "3"


def test_the_default_source_is_the_process_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_TOKEN", "nxt_secret")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/somewhere")
    env = cli.child_env(None, gitdir=tmp_path, worktree=tmp_path)
    assert "NEXUS_TOKEN" not in env and env["CLAUDE_CONFIG_DIR"] == "/somewhere"


# --- 64: the instruction --------------------------------------------------------------------------


def test_the_instruction_quotes_the_cap_of_the_commit():
    megabytes = run_commit.MAX_FILE_BYTES // (1024 * 1024)
    assert re.findall(r"(\d+) Mo", cli.INSTRUCTION) == [str(megabytes)]


def test_the_instruction_is_the_text_of_the_spec():
    assert cli.INSTRUCTION == (
        "\n\n---\n"
        "Consigne de Nexus : tu travailles dans un dossier à part, créé pour ce run.\n"
        "Tu peux lire, créer et modifier des fichiers de ce dossier ; tu ne peux lancer aucune "
        "commande\n(ni git, ni tests). Ne touche pas aux dossiers .git et ne crée ni dépôt git, "
        "ni lien, ni fichier\nde plus de 20 Mo : Nexus refuserait alors d'enregistrer le travail.\n"
        "Quand tu as fini, arrête-toi : Nexus enregistre lui-même tes changements dans un commit, "
        "que Loïc\nrelira. Si rien n'est à changer, dis pourquoi dans ta réponse finale.\n"
    )


def test_the_instruction_names_no_run_no_path_and_no_model():
    text = cli.INSTRUCTION.lower()
    for word in ("nx-run", "sonnet", "opus", "haiku", "\\", ":/", "nexus/"):
        assert word not in text
    assert cli.INSTRUCTION.startswith("\n\n---\nConsigne de Nexus")
    assert cli.INSTRUCTION.endswith("\n")
