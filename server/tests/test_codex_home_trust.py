"""The trust entry `codex exec` writes in the home of Nexus is accepted, nothing else is, and a
`.codex` at the root of the main repository is refused before the worktree (spec 2026-11-23,
addendum to #186: §4, tests T1 to T7). The real binary never runs."""

import logging
import os
import shutil
import sys
import traceback

import pytest
from codex_support import (
    LAUNCH_KINDS,
    OK_LINES,
    Rig,
    calls,
    git,
    make_repo,
    run_info,
    trust_home,
    trust_key,
)

from nexus.adapters import codex_git

REFUSED = "CODEX_HOME de Nexus configuré : lancement refusé"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


def entry(path, level='"trusted"') -> str:
    """One trust table, as Codex writes it (M1), for `path`."""
    return f"[projects.{trust_key(path)}]\ntrust_level = {level}\n"


def write_home(r: Rig, content, name="config.toml"):
    r.home.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8") if isinstance(content, str) else content
    (r.home / name).write_bytes(data)


def launched(r: Rig, n=1, **info):
    r.adapter.dispatch(run_info(n, **info))
    r.adapter.join(f"nx-run-{n}", 20)
    r.adapter.watch(run_info(n, external_ref="x"))


# --- T1: runs one after the other (regression of Q12) ---------------------------------------------


def test_the_entry_the_run_writes_does_not_refuse_the_next_run(rig, tmp_path):
    r = rig(lines=OK_LINES, actions=[trust_home(tmp_path / "repo")])
    r.run(1)
    written = (r.home / "config.toml").read_text(encoding="utf-8")
    assert written == entry(r.repo)  # the bytes of M1, written by the fake `exec`

    r.run(2)
    assert r.kinds() == LAUNCH_KINDS * 2


# --- T2: the entries of configured repositories are accepted --------------------------------------


@pytest.mark.parametrize("level", ['"trusted"', '"untrusted"'])
def test_a_trust_entry_of_the_configured_repository_is_accepted(rig, level):
    r = rig(lines=OK_LINES)
    write_home(r, entry(r.repo, level))
    r.run()
    assert r.kinds() == LAUNCH_KINDS


def test_entries_of_two_configured_repositories_are_accepted(rig, tmp_path):
    r = rig(lines=OK_LINES)
    other = make_repo(tmp_path / "autre dépôt")
    r.adapter.workdirs = [r.repo, other]
    write_home(r, entry(r.repo) + entry(other, '"untrusted"'))
    launched(r, workdir=str(r.repo))
    assert r.kinds() == LAUNCH_KINDS


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive paths: Windows only")
def test_a_key_in_another_case_names_the_same_repository_under_windows(rig):
    r = rig(lines=OK_LINES)
    write_home(r, f"[projects.{trust_key(r.repo).upper()}]\ntrust_level = \"trusted\"\n")
    r.run()
    assert r.kinds() == LAUNCH_KINDS


# --- T3: anything else in `config.toml` refuses the launch before any control call ----------------


def deep(r):
    return entry(r.repo) + "x = " + "[" * 20000 + "]" * 20000 + "\n"


CASES = {
    "pas du toml": lambda r: "x",
    "toml cassé": lambda r: entry(r.repo).replace("]\n", "\n", 1),
    "marque d'ordre": lambda r: b"\xef\xbb\xbf" + entry(r.repo).encode("utf-8"),
    "table en double": lambda r: entry(r.repo) * 2,
    "clé en double": lambda r: entry(r.repo) + 'trust_level = "trusted"\n',
    "projects vide": lambda r: "[projects]\n",
    "autre clé": lambda r: entry(r.repo) + 'model = "x"\n',
    "valeur yes": lambda r: entry(r.repo, '"yes"'),
    "valeur true": lambda r: entry(r.repo, "true"),
    "table mcp": lambda r: entry(r.repo) + '[mcp_servers.x]\ncommand = "x"\n',
    "clé de premier niveau": lambda r: 'model = "x"\n' + entry(r.repo),
    "clé du worktree": lambda r: entry(r.data / "worktrees" / "nx-run-1"),
    "clé d'un parent": lambda r: entry(r.repo.parent),
    "dossier non configuré": lambda r: entry(r.repo.parent / "autre"),
    "à côté d'une clé valide": lambda r: entry(r.repo) + entry(r.repo.parent / "autre"),
    "plus de 64 Kio": lambda r: entry(r.repo) + "# " + "x" * 65536 + "\n",
    "pas de l'UTF-8": lambda r: entry(r.repo).encode("utf-8") + b"# \xff\n",
    "imbrication profonde": deep,
}


@pytest.mark.parametrize("case", list(CASES))
def test_anything_but_trust_entries_refuses_the_launch(rig, case):
    r = rig(lines=OK_LINES)
    write_home(r, CASES[case](r))
    r.refused(REFUSED)
    assert r.kinds() == ["version"]


def test_a_config_folder_is_refused(rig):
    r = rig(lines=OK_LINES)
    (r.home / "config.toml").mkdir(parents=True)
    r.refused(REFUSED)
    assert r.kinds() == ["version"]


def test_a_config_link_is_refused(rig, tmp_path):
    r = rig(lines=OK_LINES)
    target = tmp_path / "ailleurs.toml"
    target.write_text(entry(r.repo), encoding="utf-8")
    r.home.mkdir(parents=True)
    try:
        os.symlink(target, r.home / "config.toml")
    except OSError:
        pytest.skip("this system creates no symbolic link here")
    r.refused(REFUSED)
    assert r.kinds() == ["version"]


# --- T4: a profile stays refused, whatever it holds -----------------------------------------------


def test_a_profile_holding_a_valid_entry_is_still_refused(rig):
    r = rig(lines=OK_LINES)
    write_home(r, entry(r.repo))
    write_home(r, entry(r.repo), name="x.config.toml")
    r.refused(REFUSED)
    assert r.kinds() == ["version"]


# --- T5, T5 bis: a `.codex` at the root of the main repository, or of the worktree ----------------


@pytest.fixture
def no_worktree(monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("create_worktree called despite a `.codex` in the repository")

    monkeypatch.setattr(codex_git, "create_worktree", never)


def codex_folder(repo):
    (repo / ".codex").mkdir()


def codex_config(repo):
    codex_folder(repo)
    (repo / ".codex" / "config.toml").write_text("[mcp_servers.x]\n", encoding="utf-8")


def codex_file(repo):
    (repo / ".codex").write_bytes(b"")


@pytest.mark.parametrize("make", [codex_folder, codex_config, codex_file])
@pytest.mark.parametrize("home_trusted", [False, True])
def test_an_untracked_codex_entry_of_the_main_repository_is_refused_before_the_worktree(
    rig, no_worktree, make, home_trusted
):
    r = rig(lines=OK_LINES)
    if home_trusted:  # the case where Codex would read it (M7)
        write_home(r, entry(r.repo))
    make(r.repo)
    assert git(r.repo, "ls-files", ".codex") == ""  # not tracked by git

    r.refused(".codex")
    assert r.kinds() == []


def test_a_codex_folder_gone_from_the_main_tree_is_still_refused_in_the_worktree(
    rig, monkeypatch
):
    r = rig(lines=OK_LINES)
    codex_config(r.repo)
    git(r.repo, "add", ".codex")
    git(r.repo, "commit", "-q", "-m", "projet")
    shutil.rmtree(r.repo / ".codex")  # deleted from the disk only: still tracked
    made = []
    real = codex_git.create_worktree
    monkeypatch.setattr(codex_git, "create_worktree",
                        lambda *a, **k: made.append(1) or real(*a, **k))

    r.refused(".codex")
    assert made == [1]  # the repository check passed: the worktree's refused it
    assert r.kinds() == ["version"]


# --- T6: the command lines do not change ----------------------------------------------------------


def test_the_command_lines_are_the_same_with_and_without_a_trust_entry(rig):
    r = rig(lines=OK_LINES)
    r.run(1)
    write_home(r, entry(r.repo))
    r.run(2)

    seen = calls(r.dir)
    assert [c["kind"] for c in seen] == LAUNCH_KINDS * 2
    for first, second in zip(seen[:len(LAUNCH_KINDS)], seen[len(LAUNCH_KINDS):], strict=True):
        assert [a.replace("nx-run-1", "nx-run-2") for a in first["args"]] == second["args"]


# --- T7: the refusal never carries the path nor the content of the file ---------------------------


WITNESS = "temoin-cle-etrangere"


@pytest.mark.parametrize("content", [
    lambda r: entry(r.repo) + entry(r.repo.parent / WITNESS),
    lambda r: f"[projects.{WITNESS}\n",
    lambda r: entry(r.repo.parent / WITNESS) * 2,  # tomllib names a table declared twice
])
def test_the_refusal_copies_neither_the_path_nor_the_content(rig, caplog, content):
    r = rig(lines=OK_LINES)
    write_home(r, content(r))
    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError) as caught:
        r.dispatch()

    assert str(caught.value) == REFUSED
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    told = "".join(traceback.format_exception(caught.value))
    for leak in (WITNESS, str(r.home), str(r.home.resolve())):
        assert leak not in told and leak not in caplog.text
