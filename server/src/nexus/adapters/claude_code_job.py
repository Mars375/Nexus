"""One running `claude -p`: its process, its worktree and the story told so far (in memory only).

A reader thread turns each stream-json line into facts as it comes; the raw output is never kept.
The isolation of the session is judged on `system/init`: a breach, or an agent that speaks before
the isolation was proved, is only noted here (and nothing more is recorded); the adapter kills the
tree on its next turn (spec 2026-11-11, §5.3).
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from nexus.adapters import codex_git, run_commit
from nexus.adapters.base import RunEvent
from nexus.adapters.claude_code_translate import Fact, translate_line
from nexus.clock import now

MAX_PROGRESS = 300  # progress facts kept per run; the end is always kept


@dataclass(frozen=True)
class Result:
    """The last `result` line: a success, or a failure with its cause."""

    ok: bool
    cause: str | None = None


class Job:
    def __init__(
        self, tree: codex_git.Worktree, process: subprocess.Popen, *, gitdir: Path,
        identity: run_commit.Identity, run_ref: str, model: str, settings: Path,
    ) -> None:
        self.tree, self.process, self.gitdir = tree, process, gitdir
        self.identity, self.run_ref, self.model, self.settings = identity, run_ref, model, settings
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.events: list[RunEvent] = []
        self.progress = 0
        self.opened: set[str] = set()
        self.isolated = False  # a conform `system/init` was read
        self.breach: str | None = None  # the fixed words of a departure from the isolation
        self.unverified = False  # the isolation could not be proved before the agent worked
        self.result: Result | None = None
        self.settled = False
        self.settle_lock = threading.Lock()  # one closing attempt at a time
        self.ended_at: float | None = None  # when the process was seen gone, whatever the polling
        self.reader: threading.Thread | None = None

    def add(
        self, kind: str, subject: str, body: str | None = None, payload: dict | None = None,
        evidence: list[str] | None = None, final: bool = False,
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

    def stopped_reading(self) -> bool:
        """Once the isolation is in doubt nothing more is recorded (the output is still drained)."""
        return self.breach is not None or self.unverified

    def take(self, fact: Fact) -> None:
        with self.lock:
            if self.stopped_reading():
                return
            if fact.kind == "breach":
                self.breach = fact.body
                return
            if fact.kind == "isolation_unknown":
                self.unverified = True
                return
            if fact.kind in ("working", "progress") and not self.isolated:
                self.unverified = True  # the agent works before its isolation was proved
                return
            if fact.kind == "finished":
                self.result = Result(True)
                return
            if fact.kind == "failed":
                self.result = Result(False, fact.body)
                return
            if fact.kind in ("claimed", "working"):
                if fact.kind in self.opened:  # once each: a loop of them would flood
                    return
                self.opened.add(fact.kind)
                self.isolated = self.isolated or fact.kind == "claimed"
            elif self.progress >= MAX_PROGRESS:
                return
            else:
                self.progress += 1
        self.add(fact.kind, fact.subject, fact.body, fact.payload)

    def read(self) -> None:
        """Reader thread: translate each line as it comes, keep only the translation."""
        for raw in self.process.stdout:
            for fact in translate_line(raw.decode("utf-8", "replace")):
                self.take(fact)
        self.process.wait()
        self.ended_at = time.monotonic()
