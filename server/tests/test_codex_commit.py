"""Nexus commits for Codex at the end of a run (spec #186, §1, §2.3, §7; tests D1 to D13). The real
binary never runs: the fake writes files, and Nexus is the one that commits."""

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from codex_support import (
    FAILED,
    OK_LINES,
    THREAD,
    TURN,
    calls,
    fail_closing_once,
    git,
    make_fake_codex,
    make_repo,
    run_info,
    write,
)
from process_support import detach_spec, grandchild_pid, read_beat
from run_commit_support import isolate_home

from nexus.adapters import codex_cli, codex_process, run_commit
from nexus.adapters.codex import CodexAdapter
from nexus.adapters.codex_git import clean_env
from nexus.adapters.codex_job import BRANCH_MOVED, DOTGIT_CHANGED


class Rig:
    def __init__(self, tmp_path: Path, monkeypatch, **scenario):
        self.dir = tmp_path / "fake"
        self.bin = make_fake_codex(self.dir, **scenario)
        self.repo = make_repo(tmp_path / "repo")
        self.data = tmp_path / "data"
        self.adapter = CodexAdapter(str(self.bin), [self.repo], self.data, max_seconds=600)
        self.commits: list[run_commit.Outcome] = []
        real = run_commit.commit_run

        def spy(*args, **kwargs):
            outcome = real(*args, **kwargs)
            self.commits.append(outcome)
            return outcome

        monkeypatch.setattr(run_commit, "commit_run", spy)

    @property
    def worktree(self) -> Path:
        return self.data / "worktrees" / "nx-run-1"

    def run(self, **kwargs):
        self.adapter.dispatch(run_info(1, **kwargs))
        self.adapter.join("nx-run-1", 20)

    def watch(self):
        return self.adapter.watch(run_info(1, external_ref="x"))

    def last(self):
        return self.watch().events[-1]

    def head(self) -> str:
        return git(self.repo, "rev-parse", "refs/heads/nexus/nx-run-1")

    def start(self) -> str:
        return git(self.repo, "rev-parse", "HEAD")

    def show(self, name: str) -> str:
        """A file of the run's commit, read as bytes (the text git prints is not UTF-8 here)."""
        done = subprocess.run(["git", "show", f"{self.head()}:{name}"], cwd=self.repo,
                              capture_output=True, check=True, env=clean_env())
        return done.stdout.decode("utf-8")

    def log(self, fmt: str) -> str:
        return git(self.repo, "log", "-1", f"--format={fmt}", "refs/heads/nexus/nx-run-1")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return lambda **scenario: Rig(tmp_path, monkeypatch, **scenario)


# --- D1, D2: the commit of Nexus, or nothing to commit -------------------------------------------


def test_a_finished_turn_is_committed_by_nexus(rig):
    r = rig(lines=OK_LINES, actions=[write("été/ça.txt", "é è à ç « »\n")])
    r.run(brief="Le brief")

    last = r.last()

    assert last.kind == "done" and last.subject == "Codex a terminé ; Nexus a commité"
    assert last.evidence == [f"commit:{r.head()[:12]}"]
    assert r.log("%s") == "nx-run-1 : travail de Codex"
    body = r.log("%b")
    assert "Nexus-Run: nx-run-1" in body and "Nexus-Executor: codex" in body
    assert "Nexus-Model" not in body
    assert r.log("%an|%ae|%cn|%ce") == "|".join(["Codex Test", "codex-test@example.invalid"] * 2)
    assert r.show("été/ça.txt") == "é è à ç « »\n"
    assert git(r.repo, "rev-list", "--count", f"{r.start()}..{r.head()}") == "1"
    stdin = (r.dir / "stdin.txt").read_bytes()
    assert stdin == ("Le brief" + codex_cli.INSTRUCTION).encode("utf-8")


def test_a_turn_that_changed_nothing_ends_in_review(rig):
    r = rig(lines=OK_LINES)
    r.run()

    last = r.last()

    assert last.kind == "review" and last.subject == "Codex a terminé sans changement"
    assert last.body == "aucun fichier modifié : à relire"
    assert last.evidence == ["branch:nexus/nx-run-1"] and r.head() == r.start()
    assert [type(o) for o in r.commits] == [run_commit.NothingToCommit]


# --- D3, D4: the guards of precondition 1 ---------------------------------------------------------


def test_an_agent_that_committed_anyway_fails_the_run_without_a_commit_of_nexus(rig):
    r = rig(lines=OK_LINES, commit=True)
    r.run()

    last = r.last()

    assert last.kind == "failed" and last.subject == "Isolation de la session non respectée"
    assert last.payload["cause"] == BRANCH_MOVED
    assert last.evidence == ["branch:nexus/nx-run-1"]
    assert r.commits == []  # `commit_run` never called
    assert r.head() != r.start() and r.log("%s") == "work"  # the agent's commit stays for Loïc


@pytest.mark.parametrize("action", ["rewrite_dotgit", "delete_dotgit"])
def test_a_dotgit_file_rewritten_or_removed_fails_the_run(rig, tmp_path, action):
    r = rig(lines=OK_LINES, actions=[{"do": action, "to": str(tmp_path / "ailleurs")}, write()])
    r.run()

    last = r.last()

    assert last.kind == "failed" and last.payload["cause"] == DOTGIT_CHANGED
    assert r.commits == [] and r.head() == r.start()


def test_a_dotgit_file_that_became_a_folder_fails_the_run(rig):
    r = rig(lines=OK_LINES, actions=[write()])
    r.run()
    (r.worktree / ".git").unlink()
    (r.worktree / ".git").mkdir()

    assert r.last().payload["cause"] == DOTGIT_CHANGED
    assert r.commits == [] and r.head() == r.start()


def test_a_branch_that_cannot_be_read_is_a_refusal(rig, monkeypatch):
    r = rig(lines=OK_LINES, actions=[write()])
    r.run()
    git(r.repo, "update-ref", "-d", "refs/heads/nexus/nx-run-1")  # gone: never committed again

    assert r.last().payload["cause"] == BRANCH_MOVED
    assert r.commits == []


# --- D5, D15: one commit, whatever is lost between it and its event ----------------------------


def test_a_closing_event_lost_after_the_commit_is_recovered_with_the_same_commit(rig):
    r = rig(lines=OK_LINES, actions=[write()])
    r.run()
    job = r.adapter._job("nx-run-1")
    lost = fail_closing_once(job)

    with pytest.raises(RuntimeError):
        r.watch()
    assert lost == ["done"] and job.commit_attempted and not job.settled
    head = r.head()

    last = r.last()

    assert last.kind == "done" and last.evidence == [f"commit:{head[:12]}"]
    assert r.head() == head and git(r.repo, "rev-list", "--count", f"{r.start()}..{head}") == "1"
    assert [type(o) for o in r.commits] == [run_commit.Committed] * 2  # step 1: the same sha


def test_the_maximum_duration_after_a_commit_still_ends_done(rig):
    r = rig(lines=OK_LINES, actions=[write()])
    r.run()
    job = r.adapter._job("nx-run-1")
    fail_closing_once(job)
    with pytest.raises(RuntimeError):
        r.watch()
    r.adapter.max_seconds = 0  # over at the next turn

    result = r.watch()

    assert result.events[-1].kind == "done"
    assert all(e.subject != "Durée maximale dépassée" for e in result.events)
    assert git(r.repo, "rev-list", "--count", f"{r.start()}..{r.head()}") == "1"


# --- D6: the whole tree is stopped before the commit ---------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="job object: Windows only")
def test_a_background_writer_is_stopped_before_the_commit(rig, tmp_path):
    spec = detach_spec(tmp_path / "gc")
    r_dir = tmp_path / "data" / "worktrees" / "nx-run-1"
    spec["beat"] = str(r_dir / "late.txt")  # rewritten every 50 ms, inside the worktree
    r = rig(lines=OK_LINES, actions=[write()], detach=spec)
    try:
        r.adapter.dispatch(run_info(1))
        job = r.adapter._job("nx-run-1")
        grandchild_pid(spec)
        deadline = time.monotonic() + 20
        while not codex_process.exited(job.process) and time.monotonic() < deadline:
            time.sleep(0.02)

        last = r.last()

        assert last.kind == "done", last.payload
        frozen = read_beat(spec)
        time.sleep(0.3)
        assert read_beat(spec) == frozen  # nothing writes any more
        assert r.show("late.txt") == frozen
    finally:
        r.adapter.close()


def test_an_unconfirmed_stop_before_the_commit_keeps_the_run_open(rig, monkeypatch):
    r = rig(lines=OK_LINES, actions=[write()])
    r.run()
    real = codex_process.kill_tree
    monkeypatch.setattr(codex_process, "kill_tree", lambda *a, **k: False)

    with pytest.raises(RuntimeError, match="non confirmé"):
        r.watch()
    assert r.commits == [] and r.head() == r.start()
    assert not r.adapter._job("nx-run-1").settled

    monkeypatch.setattr(codex_process, "kill_tree", real)
    assert r.last().kind == "done"  # tried again on the next turn


# --- D7, D8: what `run_commit` refuses or ignores goes through the adapter -----------------------


@pytest.mark.parametrize(("action", "motive"), [
    ({"do": "nested_repo"}, "dépôt git imbriqué"),
    ({"do": "gitfile"}, "dépôt git imbriqué"),
    ({"do": "junction"}, "lien ou point de jonction"),
    ({"do": "big_file", "path": "gros.bin", "size": 2048}, "fichier trop gros"),
])
def test_what_run_commit_refuses_fails_the_run(rig, tmp_path, action, motive):
    outside = tmp_path / "outside"
    outside.mkdir()
    r = rig(lines=OK_LINES, actions=[write(), {**action, "to": str(outside)}])
    r.adapter.max_file_bytes = 1024
    r.run()

    last = r.last()

    assert last.kind == "failed" and last.subject == "Commit refusé par Nexus"
    assert last.payload["cause"] == f"commit refusé par Nexus : {motive}"
    assert last.evidence == ["branch:nexus/nx-run-1"] and r.head() == r.start()


def test_a_filter_driver_added_during_the_run_is_refused(rig):
    r = rig(lines=OK_LINES, actions=[write(), {"do": "attributes"}])
    r.run()
    git(r.repo, "config", "filter.witness.clean", "cat")  # after the launch checked it

    last = r.last()

    assert last.payload["cause"] == "commit refusé par Nexus : pilote de filtre"
    assert r.head() == r.start()


def test_everything_ignored_ends_in_review(rig):
    r = rig(lines=OK_LINES, actions=[{"do": "ignore_all"}, write("nouveau.txt")])
    r.run()

    assert r.last().kind == "review" and r.head() == r.start()


# --- D9: no commit after a failed turn ----------------------------------------------------------


@pytest.mark.parametrize(("lines", "code"), [
    ([THREAD, TURN, FAILED], 1), (OK_LINES, 1), ([THREAD, TURN], 0),
])
def test_a_failed_turn_commits_nothing(rig, lines, code):
    r = rig(lines=lines, actions=[write()], exit=code)
    r.run()

    last = r.last()

    assert last.kind == "failed" and last.subject == "Codex a échoué"
    assert r.commits == [] and r.head() == r.start() and (r.worktree / "a.txt").exists()


def test_the_maximum_duration_commits_nothing(rig):
    r = rig(lines=[THREAD, TURN], actions=[write()], hang=True)
    r.adapter.dispatch(run_info(1))
    deadline = time.monotonic() + 20
    while not (r.worktree / "a.txt").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    r.adapter.max_seconds = 0

    last = r.last()

    assert last.kind == "failed" and last.subject == "Durée maximale dépassée"
    assert r.commits == [] and r.head() == r.start() and (r.worktree / "a.txt").exists()


# --- D11: what can fail comes before the worktree ------------------------------------------------


def refused_before_anything(r, match):
    with pytest.raises(ValueError, match=match):
        r.adapter.dispatch(run_info(1))
    assert calls(r.dir) == []  # no control call, no run
    assert not r.worktree.exists() and git(r.repo, "branch", "--list", "nexus/*") == ""


def test_a_repository_without_a_git_identity_launches_nothing(rig, tmp_path, monkeypatch):
    r = rig(lines=OK_LINES)
    isolate_home(monkeypatch, tmp_path / "home")  # no global identity either
    git(r.repo, "config", "--unset", "user.name")
    git(r.repo, "config", "--unset", "user.email")

    refused_before_anything(r, "identité git")


def test_a_filter_driver_in_the_repository_launches_nothing(rig):
    r = rig(lines=OK_LINES)
    git(r.repo, "config", "filter.witness.smudge", "cat")

    refused_before_anything(r, "pilote de filtre")


# --- D12: the instruction ------------------------------------------------------------------------


def test_the_instruction_is_the_one_of_the_spec():
    megabytes = run_commit.MAX_FILE_BYTES // (1024 * 1024)
    assert re.findall(r"(\d+) Mo", codex_cli.INSTRUCTION) == [str(megabytes)]
    assert codex_cli.INSTRUCTION == (
        "\n\n---\nConsigne de Nexus : tu travailles dans un dossier à part, créé pour ce run.\n"
        "Ne lance ni `git commit`, ni `git add`, ni aucune commande qui écrit dans git : Nexus "
        "enregistre\nlui-même tes changements dans un commit, que Loïc relira, quand ton tour se "
        "termine sans erreur.\nTu peux lire l'état du dépôt (`git status`, `git diff`, "
        "`git log`).\nNe touche pas au fichier .git de ce dossier et ne crée ni dépôt git, ni "
        "lien (lien symbolique,\npoint de jonction, lien physique), ni fichier de plus de 20 Mo : "
        "Nexus refuserait alors\nd'enregistrer le travail.\nNe laisse aucun processus tourner en "
        "arrière-plan : Nexus les arrête avant d'enregistrer.\nSi rien n'est à changer, dis "
        "pourquoi dans ta réponse finale.\n"
    )
    assert "nx-run" not in codex_cli.INSTRUCTION and "\\" not in codex_cli.INSTRUCTION
