"""The commit Nexus makes itself at the end of a successful run (spec 2026-11-11, §5.4).

Executor-neutral: this module knows no executor. It depends on `codex_git` (the `Worktree`) and
`codex_process` (the environment allow-list), never on a `claude_code*` module, on `codex.py` or
on `nexus.runs`. It returns an outcome and never raises: every failure is a final outcome, or the
supervisor would retry at every turn.

Preconditions, to be met by every caller:

1. The agent could not write in the git directory of the worktree, nor in the shared one. This is
   what lets step 1 trust a commit found on the branch: it can only be Nexus's own, from an earlier
   pass (server stopped, or an exception between the commit and the event). True for `claude-code`
   (no Bash, `--restricted`); an executor that can commit itself must not use this module as is.
2. No process of the run can write in the worktree any more while it is checked and added.
   Otherwise a junction made between the walk (step 3) and `git add` (step 4) would make git read
   outside, and the index would hold an ordinary file that the mode check cannot see. True for
   `claude-code` (no child process that writes; the commit runs after the process has exited).
   An executor with a shell needs a confirmed stop of the whole process tree, orphans included,
   which `codex_process.kill_tree` does not guarantee on Windows. Step 5 is a partial defence only:
   every added path must be a regular file the walk has seen.

Sequence: 1 proof (a commit already on the branch is the answer); 2 no filter driver in the
configuration; 3 walk of the worktree; 4 `git add -A`; 5 check of the index; 6 `git commit`;
7 proof again. Every git call has the environment and the `-c` options of §4.6, runs under a
per-call timeout, and counts in a total budget, proof reads included.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from nexus.adapters import codex_git, codex_process
from nexus.adapters.run_commit_scan import scan_worktree

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024
COMMIT_BUDGET = 90.0
CALL_TIMEOUT = 30.0
FINAL_RESERVE = 15.0  # of COMMIT_BUDGET: kept so that a written commit is always read back
TIMED_OUT = 124  # returncode of a git that did not answer in time
UNUSABLE = 127  # returncode of a git that could not be started

# Imposed by `run_git` itself, never inherited (`child_env` drops every `GIT_*`).
FORCED_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
    "GIT_ATTR_NOSYSTEM": "1", "GIT_EDITOR": ":",
}
GIT_OPTIONS = (
    "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false",
    "-c", "commit.gpgsign=false", "-c", f"core.attributesFile={os.devnull}",
    "-c", "gc.auto=0", "-c", "maintenance.auto=false",
)
FILTER_KEYS = r"^filter\..*\.(clean|smudge|process)$"
REGULAR_MODES = ("100644", "100755")


@dataclass(frozen=True)
class Identity:  # resolved before launch, pinned for the commit
    name: str
    email: str


@dataclass(frozen=True)
class CommitRequest:
    tree: codex_git.Worktree  # repo, path, branch, start
    gitdir: Path  # <repo>/.git/worktrees/<ref>, checked under the common dir
    identity: Identity
    run_ref: str  # "nx-run-<n>"
    adapter: str  # Adapter.name: "claude-code", later "codex"
    label: str  # human name in the subject: "Claude Code", later "Codex"
    model: str | None  # a model alias already checked by the adapter, or None (no trailer)


@dataclass(frozen=True)
class Committed:
    sha: str


@dataclass(frozen=True)
class NothingToCommit:
    pass


@dataclass(frozen=True)
class Refused:
    motive: str


@dataclass(frozen=True)
class GitFailed:
    step: str
    timed_out: bool = False


Outcome = Committed | NothingToCommit | Refused | GitFailed


class _Stop(Exception):
    def __init__(self, outcome: Outcome):
        super().__init__()
        self.outcome = outcome


def run_git(
    cwd: Path, args: Sequence[str], *, timeout: float,
    extra_env: Mapping[str, str] | None = None, stdin: str | None = None,
) -> subprocess.CompletedProcess:
    """git from `cwd` with the locked-down environment and options of §4.6. A timeout is a
    returncode of 124 and a git that cannot start one of 127: never an exception."""
    env = codex_process.child_env()
    env.update(FORCED_ENV)
    env.update(extra_env or {})
    argv = ["git", *GIT_OPTIONS, *args]
    try:
        return subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False, env=env, input=stdin,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, TIMED_OUT, "", "")
    except OSError:
        return subprocess.CompletedProcess(argv, UNUSABLE, "", "")


# --- before the launch: three checks that raise ValueError ----------------------------------------


def worktree_gitdir(tree: codex_git.Worktree) -> Path:
    """`GIT_DIR` of the worktree, read by git (it may suffix the name) and checked to lie under
    the shared git directory of the repository."""
    done = codex_git.git(tree.path, "rev-parse", "--absolute-git-dir")
    common = codex_git.common_dir(tree.repo)
    if done.returncode != 0 or common is None or not done.stdout.strip():
        raise ValueError("dossier git du worktree illisible")
    gitdir = Path(done.stdout.strip()).resolve()
    try:
        Path(os.path.normcase(gitdir)).relative_to(os.path.normcase(common / "worktrees"))
    except ValueError:
        raise ValueError("dossier git du worktree hors du dépôt") from None
    if gitdir.parent.name != "worktrees":
        raise ValueError("dossier git du worktree hors du dépôt")
    return gitdir


def _sane(value: str) -> bool:
    return bool(value.strip()) and value.isprintable()


def resolve_identity(repo: Path) -> Identity:
    """`user.name` and `user.email` as git finds them for commits in `repo`: the repository's
    configuration, then the global one (through HOME/USERPROFILE); the system one stays off."""
    env = codex_process.child_env()
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    values = []
    for key in ("user.name", "user.email"):
        try:
            done = subprocess.run(
                ["git", "config", "--get", key], cwd=repo, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=CALL_TIMEOUT, check=False, env=env)
        except (OSError, subprocess.TimeoutExpired):
            done = None
        out = done.stdout if done is not None and done.returncode == 0 else ""
        values.append(out[:-1] if out.endswith("\n") else out)
    if not all(_sane(v) for v in values):
        raise ValueError("aucune identité git (user.name, user.email) pour ce dépôt")
    return Identity(values[0], values[1])


def _has_driver(done: subprocess.CompletedProcess) -> bool | None:
    """True when a driver is defined, False when none, None when git could not tell."""
    if done.returncode == 0:
        return bool(done.stdout.strip())
    return False if done.returncode == 1 else None


def check_no_filter_driver(repo: Path, gitdir: Path | None = None) -> None:
    """ValueError if the configuration git reads defines a filter driver (`clean`, `smudge`,
    `process`): a `.gitattributes` written by the agent would make `git add` run it."""
    extra = {"GIT_DIR": str(gitdir)} if gitdir else None
    found = _has_driver(run_git(
        repo, ["config", "--get-regexp", FILTER_KEYS], timeout=CALL_TIMEOUT, extra_env=extra))
    if found is None:
        raise ValueError("configuration git du dépôt illisible")
    if found:
        raise ValueError("la configuration git du dépôt définit un pilote de filtre")


# --- the commit ---------------------------------------------------------------------------------


class CommitSession:
    """The git calls of one commit: the same environment, one budget."""

    def __init__(self, request: CommitRequest, budget: float):
        self.request = request
        self._deadline = time.monotonic() + budget
        self._reserve = budget * FINAL_RESERVE / COMMIT_BUDGET
        who = request.identity
        self._env = {
            "GIT_AUTHOR_NAME": who.name, "GIT_AUTHOR_EMAIL": who.email,
            "GIT_COMMITTER_NAME": who.name, "GIT_COMMITTER_EMAIL": who.email,
        }

    def _limit(self, final: bool) -> float:
        remaining = self._deadline - time.monotonic()
        if final:  # the reserve the earlier steps left, shared by the reads of the last proof
            return min(CALL_TIMEOUT, remaining)
        return min(CALL_TIMEOUT, remaining - self._reserve)

    def git(
        self, step: str, args: Sequence[str], *, in_repo: bool = False, final: bool = False,
        stdin: str | None = None, extra_env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        """From the worktree (its own `GIT_DIR`), or from the repository for the reads."""
        limit = self._limit(final)
        if limit <= 0:
            raise _Stop(GitFailed(step, timed_out=True))
        env = dict(self._env)
        tree = self.request.tree
        if not in_repo:
            env.update(GIT_DIR=str(self.request.gitdir), GIT_WORK_TREE=str(tree.path))
        env.update(extra_env or {})
        done = run_git(tree.repo if in_repo else tree.path, args, timeout=limit,
                       extra_env=env, stdin=stdin)
        if done.returncode == TIMED_OUT:
            raise _Stop(GitFailed(step, timed_out=True))
        return done

    def proof(self, step: str, *, final: bool = False) -> str | None:
        """The three reads of `codex_git.proof`, from the repository, inside the budget."""
        tree = self.request.tree

        def read(*args: str):
            return self.git(step, args, in_repo=True, final=final)

        head = read("rev-parse", "--verify", f"refs/heads/{tree.branch}^{{commit}}")
        if head.returncode != 0:
            return None
        produced = head.stdout.strip()
        if read("merge-base", "--is-ancestor", tree.start, produced).returncode != 0:
            return None
        count = read("rev-list", "--count", f"{tree.start}..{produced}")
        if count.returncode != 0 or not count.stdout.strip().isdigit():
            return None
        return produced if int(count.stdout) >= 1 else None

    def check_filters(self) -> None:
        extra = {"GIT_DIR": str(self.request.gitdir)}
        done = self.git("configuration", ["config", "--get-regexp", FILTER_KEYS],
                        in_repo=True, extra_env=extra)
        found = _has_driver(done)
        if found is None:
            raise _Stop(GitFailed("configuration"))
        if found:
            raise _Stop(Refused("pilote de filtre"))


def _valid(request: CommitRequest) -> bool:
    who = request.identity
    return (
        re.fullmatch(r"nx-run-[1-9][0-9]*", request.run_ref) is not None
        and re.fullmatch(r"[a-z][a-z-]*", request.adapter) is not None
        and 0 < len(request.label) <= 40 and request.label.isprintable()
        and (request.model is None or re.fullmatch(r"[a-z][a-z0-9-]{0,15}", request.model))
        and _sane(who.name) and _sane(who.email)
    )


def _message(request: CommitRequest) -> tuple[str, str]:
    subject = f"{request.run_ref} : travail de {request.label}"
    trailers = [f"Nexus-Run: {request.run_ref}", f"Nexus-Executor: {request.adapter}"]
    if request.model:
        subject += f" ({request.model})"
        trailers.append(f"Nexus-Model: {request.model}")
    return subject, "\n".join(trailers)


def _staged(out: str) -> list[tuple[str, str, str]]:
    """(mode, blob, path) of what the index changes against the start commit; deletions apart."""
    parts = out.split("\0")
    staged = []
    for meta, path in zip(parts[0::2], parts[1::2], strict=False):
        fields = meta.lstrip(":").split(" ")
        if not meta.startswith(":") or len(fields) < 5:
            raise _Stop(GitFailed("index"))
        if fields[1] != "000000":
            staged.append((fields[1], fields[3], path))
    return staged


def _check_files(session: CommitSession, files: dict[str, int], max_bytes: int) -> None:
    """Step 3, last rule: a new file over the cap is refused before git reads it."""
    big = [path for path, size in files.items() if size > max_bytes]
    if not big:
        return
    start = session.request.tree.start
    listed = session.git("walk", ["ls-tree", "-r", "-z", "--name-only", start], in_repo=True)
    if listed.returncode != 0:
        raise _Stop(GitFailed("walk"))
    known = set(listed.stdout.split("\0"))
    if any(path not in known for path in big):
        raise _Stop(Refused("fichier trop gros"))


def _check_index(session: CommitSession, files: dict[str, int], max_bytes: int) -> bool:
    """Step 5; False when the index holds no change (a deletion is one). Raises _Stop on a
    refusal."""
    raw = session.git("index", ["diff-index", "--cached", "--raw", "-z", "--no-renames",
                                session.request.tree.start])
    if raw.returncode != 0:
        raise _Stop(GitFailed("index"))
    staged = _staged(raw.stdout)
    for mode, _blob, _path in staged:
        if mode == "160000":
            raise _Stop(Refused("sous-module ajouté"))
        if mode == "120000":
            raise _Stop(Refused("lien ajouté"))
    if any(path not in files or mode not in REGULAR_MODES for mode, _b, path in staged):
        raise _Stop(Refused("worktree changé pendant le commit"))
    blobs = sorted({blob for _m, blob, _p in staged})
    if blobs:
        sizes = session.git("index", ["cat-file", "--batch-check"], in_repo=True,
                            stdin="".join(f"{blob}\n" for blob in blobs))
        lines = sizes.stdout.splitlines()
        if sizes.returncode != 0 or len(lines) != len(blobs):
            raise _Stop(GitFailed("index"))
        if any(not line.split()[-1].isdigit() or int(line.split()[-1]) > max_bytes
               for line in lines):
            raise _Stop(Refused("fichier trop gros"))
    return bool(raw.stdout)


def _commit(request: CommitRequest, max_bytes: int, budget: float) -> Outcome:
    session = CommitSession(request, budget)
    if (sha := session.proof("preuve")) is not None:
        return Committed(sha)  # an earlier pass of Nexus already committed
    session.check_filters()
    try:
        scan = scan_worktree(request.tree.path)
    except OSError:
        return GitFailed("parcours")
    if scan.refused:
        return Refused(scan.refused)
    _check_files(session, scan.files, max_bytes)
    if session.git("add", ["add", "-A"]).returncode != 0:
        return GitFailed("add")
    if not _check_index(session, scan.files, max_bytes):
        return NothingToCommit()
    subject, trailers = _message(request)
    failure: Outcome = GitFailed("commit")
    try:
        if session.git("commit", ["commit", "-q", "-m", subject, "-m", trailers]).returncode:
            failure = GitFailed("commit")
    except _Stop as stop:
        failure = stop.outcome  # a timeout may have killed git after it wrote the commit
    sha = session.proof("commit", final=True)
    return Committed(sha) if sha is not None else failure


def commit_run(
    request: CommitRequest, *, max_file_bytes: int = MAX_FILE_BYTES, budget: float = COMMIT_BUDGET
) -> Outcome:
    """Commit what the agent wrote in the worktree. Never raises."""
    if not _valid(request):
        return Refused("requête invalide")
    try:
        return _commit(request, max_file_bytes, budget)
    except _Stop as stop:
        return stop.outcome
    except Exception as error:  # a final outcome, or the supervisor would retry for ever
        log.warning("run commit: unexpected %s", type(error).__name__)
        return GitFailed("interne")
