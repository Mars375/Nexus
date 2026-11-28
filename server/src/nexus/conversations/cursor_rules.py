"""What to do with one session file this pass (spec §6.1, §6.2; plan PR 2 §5.5): pure.

The rules run in a fixed order; the first that applies decides. "Unchanged" means the same
`size`, `mtime_ns` and `file_id` as the cursor kept. A file is never claimed `ok` with a
`covered_since` more recent than the retention threshold in force: that reads it again from 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from nexus.conversations.models import ConversationCursor
from nexus.conversations.paths import Candidate


@dataclass(frozen=True)
class Policy:
    window_start: datetime  # now - NEXUS_CONV_SINCE_DAYS
    retention_start: datetime  # now - NEXUS_CONV_RETENTION_DAYS

    @classmethod
    def at(cls, now: datetime, *, since_days: int, retention_days: int) -> Policy:
        now = now.astimezone(UTC)  # elapsed time, never wall-clock time across a DST change
        return cls(now - timedelta(days=since_days), now - timedelta(days=retention_days))


@dataclass(frozen=True)
class Plan:
    action: Literal["skip", "mark_old", "read"]
    start: int = 0
    skipping: bool = False
    covered_since: datetime | None = None
    check_head: bool = False  # compare the head digest kept before resuming at `start`


SKIP = Plan("skip")
MARK_OLD = Plan("mark_old")


def mtime_of(candidate: Candidate) -> datetime:
    return datetime.fromtimestamp(candidate.mtime_ns / 1e9, UTC)


def unchanged(cursor: ConversationCursor, candidate: Candidate) -> bool:
    return (cursor.size, cursor.mtime_ns, cursor.file_id) == (
        candidate.size, candidate.mtime_ns, candidate.file_id)


def plan(cursor: ConversationCursor | None, candidate: Candidate, policy: Policy) -> Plan:
    from_zero = Plan("read", covered_since=policy.retention_start)
    if cursor is None or cursor.state == "skipped_old":
        # A future mtime (a clock ahead) is inside the window.
        return MARK_OLD if mtime_of(candidate) < policy.window_start else from_zero
    covered = cursor.covered_since
    # In every state; compared as instants (Paris times compare by wall clock across a DST change).
    if covered is None or covered.astimezone(UTC) > policy.retention_start.astimezone(UTC):
        return from_zero
    if cursor.file_id != candidate.file_id or candidate.size < cursor.byte_offset:
        return from_zero
    same = unchanged(cursor, candidate)
    state = cursor.state
    if same and state in ("ok", "too_large", "unreadable"):
        return SKIP
    if same and state == "skipping" and cursor.byte_offset >= candidate.size:
        return SKIP
    if state == "unreadable":  # judged again once it changes
        return from_zero
    return Plan("read", start=cursor.byte_offset, skipping=state == "skipping",
                covered_since=covered, check_head=True)
