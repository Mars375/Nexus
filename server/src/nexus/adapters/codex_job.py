"""One running `codex exec` of the Codex adapter: its process, its worktree, the story so far.

Moved out of `codex.py` (spec #186, §8, sizes). A `breach` (an MCP tool called during the run,
§5.4) stops the whole tree at once from the reader thread, like `claude_code_job.Job.take`, and
nothing more is recorded; the adapter closes the run `failed` once the stop is confirmed.
"""

from __future__ import annotations

import subprocess
import threading
import time

from nexus.adapters import codex_git, codex_process
from nexus.adapters.base import RunEvent
from nexus.adapters.codex_translate import Fact, translate_line
from nexus.clock import now

MAX_PROGRESS = 300  # progress facts kept per run; the end is always kept


class Job:
    """One running `codex exec`: its process, its worktree and the story told so far."""

    def __init__(self, tree: codex_git.Worktree, process: subprocess.Popen) -> None:
        self.tree, self.process = tree, process
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
        self.process.wait()
        if self.ended_at is None:  # `_settle` may have seen the exit first
            self.ended_at = time.monotonic()
