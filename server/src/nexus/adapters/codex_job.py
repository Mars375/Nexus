"""One running `codex exec` of the Codex adapter: its process, its worktree, the story so far.

Moved out of `codex.py` (spec #186, §8, sizes). A `breach` (an MCP tool called during the run,
§5.4) stops the whole tree at once from the reader thread, like `claude_code_job.Job.take`, and
nothing more is recorded; the adapter closes the run `failed` once the stop is confirmed.

What Nexus needs to commit the run (§1.3) lives here too: the git directory and identity fixed at
the launch, the bytes of the worktree's `.git` file read just after it was made, and whether a
commit was already tried (`commit_attempted`, with its last `outcome`).
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from nexus.adapters import codex_git, codex_process, run_commit
from nexus.adapters.base import RunEvent
from nexus.adapters.codex_translate import Fact, translate_line
from nexus.clock import now

MAX_PROGRESS = 300  # progress facts kept per run; the end is always kept
BRANCH_MOVED = "isolation non respectée : la branche du run a changé pendant le run"
DOTGIT_CHANGED = "isolation non respectée : fichier .git du worktree modifié"


class Job:
    """One running `codex exec`: its process, its worktree and the story told so far."""

    def __init__(
        self, tree: codex_git.Worktree, process: subprocess.Popen, *, gitdir: Path,
        identity: run_commit.Identity, run_ref: str, dotgit: bytes,
    ) -> None:
        self.tree, self.process, self.gitdir = tree, process, gitdir
        self.identity, self.run_ref, self.dotgit = identity, run_ref, dotgit
        self.commit_attempted = False  # `commit_run` was called once: guards skipped from then on
        self.outcome: run_commit.Outcome | None = None  # of the last `commit_run`
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.events: list[RunEvent] = []
        self.progress = 0
        self.opened: set[str] = set()
        self.turn_done = False
        self.failure: str | None = None  # from `turn.failed`: it decides, the latest wins
        self.last_error: str | None = None  # from `error` lines: a cause only when nothing better
        self.breach: str | None = None  # the fixed words of a departure from the isolation
        self.settled = False
        self.settle_lock = threading.Lock()  # one closing attempt at a time
        self.ended_at: float | None = None  # when the process was seen gone, whatever the polling
        self.reader: threading.Thread | None = None

    def add(
        self,
        kind: str,
        subject: str,
        body: str | None = None,
        payload: dict | None = None,
        evidence: list[str] | None = None,
        final: bool = False,
    ) -> None:
        """Append a fact. The closing one (`final`) seals the story: nothing follows it."""
        with self.lock:
            if self.settled:
                return
            self.settled = final
            seq = len(self.events) + 1
            # `seq` in the payload makes two identical progress facts distinct (anti-noise).
            self.events.append(RunEvent(
                seq=seq, at=now(), kind=kind, subject=subject, body=body,
                payload={"seq": seq} | (payload or {}), evidence=evidence or [],
            ))

    def take(self, fact: Fact) -> None:
        if fact.kind == "breach":
            with self.lock:
                first = self.breach is None
                if first:
                    self.breach = fact.body
            if first:
                # At once, not on the next tick: the agent may still be acting. The adapter
                # confirms the stop before it closes the run.
                codex_process.kill_tree(self.process)
            return
        with self.lock:
            if self.breach is not None:
                return  # nothing more is recorded (the output is still drained)
            if fact.kind == "finished":
                self.turn_done = True
                return
            if fact.kind == "failed":
                self.failure = fact.body
                return
            if fact.kind == "error":
                self.last_error = fact.body
                return
            if fact.kind in ("claimed", "working"):
                if fact.kind in self.opened:  # once each: a loop of them would flood
                    return
                self.opened.add(fact.kind)
            elif self.progress >= MAX_PROGRESS:
                return
            else:
                self.progress += 1
        self.add(fact.kind, fact.subject, fact.body)

    def read(self) -> None:
        """Reader thread: translate each line as it comes, keep only the translation."""
        for line in self.process.stdout:
            fact = translate_line(line)
            if fact is not None:
                self.take(fact)
        codex_process.wait_exited(self.process)  # never reaps: `kill_tree` does (POSIX)
        if self.ended_at is None:  # `_settle` may have seen the exit first
            self.ended_at = time.monotonic()

    def tampered(self) -> str | None:
        """The guards of precondition 1 (§1.3, step 5), or None when both hold: the branch still
        at the start commit (read from the repository), the `.git` file of the worktree with the
        bytes read at the launch. Any doubt (git that fails, unreadable file) is a refusal."""
        head = codex_git.git(self.tree.repo, "rev-parse", "--verify", "--quiet",
                             f"refs/heads/{self.tree.branch}")
        if head.returncode != 0 or head.stdout.strip() != self.tree.start:
            return BRANCH_MOVED
        dotgit = self.tree.path / ".git"
        try:
            same = not dotgit.is_symlink() and dotgit.is_file() and (
                dotgit.read_bytes() == self.dotgit)
        except OSError:
            same = False
        return None if same else DOTGIT_CHANGED
