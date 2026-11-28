"""The `conversations_loop` task of the lifespan (spec §6.1; plan PR 2 §5.8).

One pass at a time (a process lock), in a worker thread. Without any source set, a tick lists
and opens nothing; it still runs the purge, which is how a source switched off is emptied
(plan A13). `stop` raises a flag the pass checks between files, batches and every 200 lines,
then waits for the pass: cancelling the asyncio task does not stop a `to_thread` (plan A14).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from nexus.clock import now as clock_now
from nexus.config import Settings
from nexus.conversations import ingest, retention
from nexus.conversations.cursor_rules import Policy
from nexus.conversations.state import ProcessState

log = logging.getLogger("nexus.conversations")


class Conversations:
    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings
        self.state = ProcessState()
        self.stopping = threading.Event()
        self._lock = threading.Lock()

    @property
    def disabled(self) -> frozenset[str]:
        # PR 2 reads Claude Code only: Codex and Hermes settings are ignored, neither read nor
        # purged, until their readers land (PR 3, PR 6).
        return frozenset() if self.settings.conv_claude_root else frozenset({"claude-code"})

    def tick(self, now: datetime | None = None) -> None:
        with self._lock:
            if self.stopping.is_set():
                return
            self._tick(now or clock_now())

    def _tick(self, now: datetime) -> None:
        now = now.astimezone(UTC)  # Paris time compares by wall clock across a DST change
        settings, state = self.settings, self.state
        if state.rebuild_pending is None:  # a crash may have cut a purge short
            state.rebuild_pending = retention.index_not_empty(self.factory)
            # A checkpoint deferred before a restart leaves purged pages in the WAL.
            wal = settings.db_path.with_name(settings.db_path.name + "-wal")
            state.checkpoint_pending |= wal.exists() and wal.stat().st_size > 0
        if settings.conv_claude_root is not None:
            policy = Policy.at(now, since_days=settings.conv_since_days,
                               retention_days=settings.conv_retention_days)
            state.status[ingest.SOURCE] = ingest.claude_pass(
                self.factory, settings.conv_claude_root, policy, stopping=self.stopping,
                state=state, now=now)
        result = None
        if retention.purge_due(state, now) and not self.stopping.is_set():
            result = retention.purge(
                self.factory, now=now, retention_days=settings.conv_retention_days,
                disabled=self.disabled, state=state, stopping=self.stopping)
        rebuilt = False
        if state.rebuild_pending and not self.stopping.is_set():
            rebuilt = retention.rebuild(self.factory, state)
        checkpointed = None
        if state.checkpoint_pending and not self.stopping.is_set():
            checkpointed = retention.checkpoint(settings.db_path)
            state.checkpoint_pending = not checkpointed
        if result is not None and (result.messages or result.conversations or result.cursors
                                   or not result.complete):
            retention.log_purge(result, rebuilt=rebuilt, checkpointed=checkpointed)

    def stop(self, timeout: float | None) -> bool:
        """Raise the flag and wait for the pass in progress; False if it outlived `timeout`
        (None waits for as long as the pass lasts)."""
        self.stopping.set()
        if not self._lock.acquire(timeout=-1 if timeout is None else timeout):
            return False
        self._lock.release()
        return True


async def loop(conversations: Conversations, poll_seconds: int) -> None:
    """Sleep first, like the backup loop; a failed tick is logged by its class, never traced."""
    while True:
        await asyncio.sleep(poll_seconds)
        try:
            await asyncio.to_thread(conversations.tick)
        except Exception as exc:  # noqa: BLE001 - logged by type only (ADR-006)
            log.error("passe des conversations échouée (%s)", type(exc).__name__)
