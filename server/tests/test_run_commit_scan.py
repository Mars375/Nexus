"""What Nexus refuses to commit in a worktree written by an agent (spec 2026-11-11, §5.4 steps
3 to 5; tests 48-52, 55-57, 67, 68). `run_commit` is called directly: no adapter, no fake binary."""

import os
import subprocess
import sys

import pytest
from run_commit_support import Spy, isolate_home, make_dir_link, make_job

from nexus.adapters import codex_git, run_commit, run_commit_scan
from nexus.adapters.run_commit import Committed, NothingToCommit, Refused


@pytest.fixture(autouse=True)
def private_home(monkeypatch, tmp_path):
    isolate_home(monkeypatch, tmp_path / "home")


def untouched(job) -> bool:
    """The index is still the start commit's: nothing was added."""
    return subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=job.tree.path,
        env=codex_git.clean_env()).returncode == 0


# --- 48, 49: a nested repository ------------------------------------------------------------


@pytest.mark.parametrize("name", [".git", ".GIT", ".git."])
def test_a_nested_repository_is_refused_before_git_add(monkeypatch, tmp_path, name):
    job = make_job(tmp_path)
    nested = job.tree.path / "sub" / name
    nested.mkdir(parents=True)
    (nested / "config").write_text("[core]\n\tfsmonitor = touch witness\n", encoding="utf-8")
    job.write("ok.txt")
    spy = Spy(monkeypatch)
    assert run_commit.commit_run(job.request()) == Refused("dépôt git imbriqué")
    assert not spy.called("add")
    assert untouched(job) and job.branch_head() == job.tree.start


def test_a_gitfile_pointing_outside_the_worktree_is_refused(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("sub/.git", f"gitdir: {job.repo / '.git'}\n")
    spy = Spy(monkeypatch)
    assert run_commit.commit_run(job.request()) == Refused("dépôt git imbriqué")
    assert not spy.called("add") and untouched(job)


def test_the_worktrees_own_dotgit_file_is_not_a_nested_repository(tmp_path):
    job = make_job(tmp_path)
    job.write("ok.txt")
    assert isinstance(run_commit.commit_run(job.request()), Committed)


# --- 50, 51: links, junctions ---------------------------------------------------------------


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_a_link_to_a_folder_outside_is_refused_and_nothing_is_read(monkeypatch, tmp_path, kind):
    job = make_job(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = "CANARY-" + "OUTSIDE" * 3
    (outside / "secret.txt").write_text(canary, encoding="utf-8")
    make_dir_link(kind, job.tree.path / "link", outside)
    job.write("ok.txt")
    spy = Spy(monkeypatch)
    assert run_commit.commit_run(job.request()) == Refused("lien ou point de jonction")
    assert not spy.called("add")
    assert canary.encode() not in job.all_objects()


def test_a_symlink_to_a_file_is_refused(tmp_path):
    job = make_job(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    try:
        os.symlink(target, job.tree.path / "file-link")
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"lien symbolique non créable ici : {type(error).__name__}")
    assert run_commit.commit_run(job.request()) == Refused("lien ou point de jonction")


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_the_walk_does_not_enter_a_link(tmp_path, kind):
    job = make_job(tmp_path)
    outside = tmp_path / "outside"
    (outside / ".git").mkdir(parents=True)
    make_dir_link(kind, job.tree.path / "link", outside)
    # the motive names the link, never the repository behind it: the walk did not go in
    assert run_commit.commit_run(job.request()) == Refused("lien ou point de jonction")


# --- 52: the index check, when the worktree check is bypassed --------------------------------


@pytest.mark.parametrize(("mode", "motive"), [
    ("160000", "sous-module ajouté"), ("120000", "lien ajouté")])
def test_a_link_in_the_index_is_refused_after_add(monkeypatch, tmp_path, mode, motive):
    job = make_job(tmp_path)
    job.write("ok.txt")
    sha = "1" * 40  # a gitlink needs no object
    if mode == "120000":
        sha = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"], cwd=job.repo, input="target", text=True,
            capture_output=True, check=True, env=codex_git.clean_env()).stdout.strip()

    def inject(done, cwd, args, kwargs):
        spy.real(cwd, ["update-index", "--add", "--cacheinfo", f"{mode},{sha},odd"], **kwargs)

    spy = Spy(monkeypatch, after={"add": inject})
    assert run_commit.commit_run(job.request()) == Refused(motive)
    assert not spy.called("commit") and job.branch_head() == job.tree.start


# --- 55: big files ---------------------------------------------------------------------------


def big_job(tmp_path):
    lines = "123456789\n" * 100  # 1000 bytes as a blob, 1100 once checked out in CRLF
    return make_job(tmp_path, {
        ".gitattributes": "converted.txt text eol=crlf\n",
        "converted.txt": lines, "huge.bin": "x" * 2000})


def test_a_new_file_over_the_cap_is_refused_before_git_reads_it(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("big.bin", "x" * 2048)
    spy = Spy(monkeypatch)
    outcome = run_commit.commit_run(job.request(), max_file_bytes=1024)
    assert outcome == Refused("fichier trop gros")
    assert not spy.called("add") and untouched(job)


def test_an_existing_big_file_checked_out_in_crlf_does_not_block(tmp_path):
    job = big_job(tmp_path)
    assert (job.tree.path / "converted.txt").read_bytes().count(b"\r\n") == 100
    job.write("new.txt")
    outcome = run_commit.commit_run(job.request(), max_file_bytes=1024)
    assert isinstance(outcome, Committed)
    assert job.committed_names(outcome.sha) == ["new.txt"]


def test_a_big_existing_file_modified_at_constant_size_is_refused_at_step_5(tmp_path):
    job = big_job(tmp_path)
    job.write("huge.bin", "y" * 2000)
    outcome = run_commit.commit_run(job.request(), max_file_bytes=1024)
    assert outcome == Refused("fichier trop gros")
    assert job.branch_head() == job.tree.start


# --- 56, 57: odd names, an ignore-all file -----------------------------------------------------


def test_files_named_like_options_are_committed_as_files(tmp_path):
    job = make_job(tmp_path)
    job.write("--output=x")
    job.write("-rf")
    outcome = run_commit.commit_run(job.request())
    assert isinstance(outcome, Committed)
    assert job.committed_names(outcome.sha) == ["--output=x", "-rf"]


def test_an_ignore_all_gitignore_gives_nothing_and_commit_is_never_called(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write(".gitignore", "*\n")
    job.write("hidden.txt")
    spy = Spy(monkeypatch)
    assert run_commit.commit_run(job.request()) == NothingToCommit()
    assert not spy.called("commit") and job.branch_head() == job.tree.start


def test_no_change_is_nothing_to_commit(tmp_path):
    job = make_job(tmp_path)
    assert run_commit.commit_run(job.request()) == NothingToCommit()


# --- 67: hard links ----------------------------------------------------------------------------


def test_a_hard_link_is_refused_and_its_content_never_enters_the_repository(
    monkeypatch, tmp_path
):
    job = make_job(tmp_path)
    outside = tmp_path / "outside.txt"
    canary = "CANARY-" + "HARDLINK" * 3
    outside.write_text(canary, encoding="utf-8")
    os.link(outside, job.tree.path / "inside.txt")
    spy = Spy(monkeypatch)
    assert run_commit.commit_run(job.request()) == Refused("lien physique")
    assert not spy.called("add")
    assert canary.encode() not in job.all_objects()


def test_the_link_count_comes_from_lstat_not_from_the_directory_entry(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    inside = job.tree.path / "inside.txt"
    os.link(outside, inside)
    if sys.platform == "win32":
        entry = next(e for e in os.scandir(job.tree.path) if e.name == "inside.txt")
        # directory-listing data: if this ever becomes 2, the comment in the scan is stale
        assert entry.stat(follow_symlinks=False).st_nlink == 0
    seen = []
    real = os.lstat
    monkeypatch.setattr(
        run_commit_scan.os, "lstat", lambda path, *a, **k: seen.append(str(path)) or real(path))
    assert run_commit_scan.scan_worktree(job.tree.path).refused == "lien physique"
    assert str(inside) in seen


# --- 68: the worktree changes between the check and the add ------------------------------------


def test_a_file_appearing_after_the_walk_is_refused(monkeypatch, tmp_path):
    job = make_job(tmp_path)
    job.write("ok.txt")
    Spy(monkeypatch, before={"add": lambda cwd, args, kw: job.write("late.txt")})
    assert run_commit.commit_run(job.request()) == Refused("worktree changé pendant le commit")
    assert job.branch_head() == job.tree.start
