"""The story of a task in order of time (ADR-023, lot E): history, events and runs, merged.

Read-only and bounded: each source is asked only for the `limit + 1` rows before the cursor,
never the whole table. The order is total and stable: instant, then kind (`RANK`), then id, so
two things at the same instant always come in the same order, and a cursor names exactly one
place in it. Pages go from the newest to the oldest; a fact that arrives after a page was read
belongs to a refresh of the first page (newer) or to a later page (older), never twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.orm import Session

from nexus.models import Event, Run, Task, TaskHistory

# At equal instants, from the oldest to the newest in the story: what a person did, the run
# starting, what the agent said, the run ending.
RANK = {"history": 0, "run_started": 1, "event": 2, "run_ended": 3}
LIMIT_DEFAULT = 50
LIMIT_MAX = 200

_CURSOR = re.compile(r"v1\.(?P<at>[0-9TZ:+.\-]{20,40})\.(?P<rank>[0-3])\.(?P<id>[0-9]{1,12})")


class InvalidCursor(ValueError):
    """The received cursor is not one we issued (never echoed back)."""


@dataclass(frozen=True)
class Position:
    """A place in the story: strictly before it is what a page asks for."""

    at: datetime  # UTC
    rank: int
    id: int

    def encode(self) -> str:
        return f"v1.{self.at.astimezone(UTC).isoformat()}.{self.rank}.{self.id}"

    @classmethod
    def decode(cls, raw: str) -> Position:
        match = _CURSOR.fullmatch(raw)
        if match is None:
            raise InvalidCursor
        try:
            at = datetime.fromisoformat(match["at"])
        except ValueError:
            raise InvalidCursor from None
        if at.utcoffset() is None:
            raise InvalidCursor
        return cls(at.astimezone(UTC), int(match["rank"]), int(match["id"]))

    def key(self) -> tuple[datetime, int, int]:
        return (self.at, self.rank, self.id)


@dataclass(frozen=True)
class Entry:
    kind: str  # history | event | run_started | run_ended
    at: datetime
    id: int  # the row id (the run id for the two run milestones)
    data: dict[str, Any]

    @property
    def position(self) -> Position:
        return Position(self.at.astimezone(UTC), RANK[self.kind], self.id)

    @property
    def ref(self) -> str:
        if self.kind in ("run_started", "run_ended"):
            return f"run-{self.id}-{self.kind.removeprefix('run_')}"
        return f"{self.kind}-{self.id}"


def _before(at_col, id_col, rank: int, cursor: Position | None):
    """SQL for "strictly before the cursor" in the order (at, rank, id), for one source."""
    if cursor is None:
        return true()
    if rank < cursor.rank:
        tie = true()
    elif rank == cursor.rank:
        tie = id_col < cursor.id
    else:
        tie = false()
    return or_(at_col < cursor.at, and_(at_col == cursor.at, tie))


def _run_entries(run: Run) -> list[Entry]:
    base = {"run": run.ref, "executor": run.executor, "agent": run.agent}
    entries = [Entry("run_started", run.created_at, run.id, base | {"status": "dispatched"})]
    if run.ended_at is not None:
        entries.append(Entry("run_ended", run.ended_at, run.id, base | {"status": run.status}))
    return entries


def page(
    session: Session, task: Task, *, limit: int = LIMIT_DEFAULT, before: Position | None = None
) -> tuple[list[Entry], Position | None]:
    """Up to `limit` entries before `before`, newest first, and where the next page starts."""
    history = session.scalars(
        select(TaskHistory)
        .where(TaskHistory.task_id == task.id,
               _before(TaskHistory.at, TaskHistory.id, RANK["history"], before))
        .order_by(TaskHistory.at.desc(), TaskHistory.id.desc())
        .limit(limit + 1)
    )
    events = session.scalars(
        select(Event)
        .where(Event.task_id == task.id, _before(Event.at, Event.id, RANK["event"], before))
        .order_by(Event.at.desc(), Event.id.desc())
        .limit(limit + 1)
    )
    entries = [Entry("history", h.at, h.id, {"row": h}) for h in history]
    entries += [Entry("event", e.at, e.id, {"row": e}) for e in events]
    # A task has few runs: all are read, then cut at the cursor like the others.
    for run in session.scalars(select(Run).where(Run.task_id == task.id)):
        entries += [
            e for e in _run_entries(run)
            if before is None or e.position.key() < before.key()
        ]
    entries.sort(key=lambda e: e.position.key(), reverse=True)
    shown = entries[:limit]
    more = len(entries) > limit
    return shown, (shown[-1].position if more and shown else None)
