"""In-memory state of the conversation readers, shared by `ingest`, `retention` and `loop`.

Nothing here is persisted (plan PR 2, A3): a restart resets the absence counters and the purge
clock, which only delays a deletion. `SourceStatus` is what the PR 4 will expose; it carries
fixed codes and counts, never a path, a session id or a content.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SourceStatus:
    # ok | partial (work left for the next pass) | degraded | unavailable | interrupted
    state: str = "ok"
    last_pass_at: datetime | None = None
    code: str | None = None  # the refusal or interruption code, when there is one
    files_read: int = 0
    messages_written: int = 0
    bytes_read: int = 0
    lines_judged: int = 0
    reads_from_zero: int = 0
    codes: Counter = field(default_factory=Counter)  # fixed codes -> count


@dataclass
class ProcessState:
    status: dict[str, SourceStatus] = field(default_factory=dict)
    # source -> external_id -> complete passes in a row without the session
    absent_passes: dict[str, Counter] = field(default_factory=dict)
    # source -> path keys of the last complete listing (None: no complete listing yet)
    listed: dict[str, frozenset[str]] = field(default_factory=dict)
    last_purge_at: datetime | None = None
    # None until the first tick looks at the index: a crash may have cut a purge short.
    rebuild_pending: bool | None = None
    checkpoint_pending: bool = False


@dataclass(frozen=True)
class SessionMeta:
    """Session fields carried by a batch; already masked and cut by `masking`."""

    title: str | None = None
    title_kind: str | None = None  # "custom" | "ai"
    workspace: str | None = None
    git_branch: str | None = None

    def merge(self, *, title: str | None = None, title_kind: str | None = None,
              workspace: str | None = None, git_branch: str | None = None) -> SessionMeta:
        """A custom title always wins; an AI title only fills an empty one."""
        replace = title is not None and (title_kind == "custom" or self.title is None)
        return SessionMeta(
            title if replace else self.title,
            title_kind if replace else self.title_kind,
            workspace or self.workspace,
            git_branch or self.git_branch,
        )


@dataclass(frozen=True)
class CursorWrite:
    path_key: str
    file_id: str
    size: int
    mtime_ns: int
    byte_offset: int
    head_sha256: str
    covered_since: datetime
    state: str


@dataclass
class PurgeResult:
    messages: int = 0
    conversations: int = 0
    cursors: int = 0
    complete: bool = True
    code: str | None = None
