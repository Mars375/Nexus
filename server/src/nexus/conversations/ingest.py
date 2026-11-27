"""One pass over the Claude Code sessions (spec §6.1, §6.2, §6.4, §6.6; plan PR 2 §5.6).

The root is checked again at each pass (decision M4 of the PR 1), the files are taken most
recent first under a budget of 8 MiB read and 2 000 messages written per pass, and each file is
opened, read and closed before its lines are parsed and masked (plan A1). Logs carry fixed codes
and counts only: never a path, a slug, a session id, a content, `str(exc)` nor a traceback.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nexus.conversations import jsonl_tail, paths, store
from nexus.conversations.cursor_rules import Plan, Policy, plan, unchanged
from nexus.conversations.jsonl_tail import HEAD_BYTES, Tail, head_bytes, read_tail
from nexus.conversations.masking import ParsedMessage
from nexus.conversations.models import ConversationCursor
from nexus.conversations.parse_claude import parse_line
from nexus.conversations.state import CursorWrite, ProcessState, SessionMeta, SourceStatus

log = logging.getLogger("nexus.conversations")

SOURCE = "claude-code"
READ_BUDGET = 8 << 20
MESSAGE_BUDGET = 2000
BATCH = 500
STOP_CHECK_LINES = 200
DEGRADED_MIN_LINES = 20  # plan A11: below this, half of the lines bad says nothing
# Every fixed code a pass can count (the codes of `paths` come on top).
LINE_CODES = frozenset({
    "utf8", "json", "not_object", "field", "sidechain", "meta", "origin", "tool_result",
    "synthetic", "old", "empty", "oversized",
})
CODES = LINE_CODES | {"foreign_session", "substituted", "file_unreadable", "db_busy",
                      "db_error"}
INCOMPLETE = ("level_dir_unreadable", "file_unreadable")


class _Stop(Exception):
    """The pass stops for this source; `code` says why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _transient(exc: Exception) -> bool:
    text = str(getattr(exc, "orig", exc)).lower()
    return isinstance(exc, OperationalError) and ("locked" in text or "busy" in text)


@dataclass
class _Pass:
    factory: sessionmaker[Session]
    policy: Policy
    stopping: threading.Event
    now: datetime
    read_left: int
    messages_left: int
    status: SourceStatus = field(default_factory=SourceStatus)
    bad: int = 0

    def write(self, external_id: str, meta: SessionMeta | None, messages: list[ParsedMessage],
              cursor: CursorWrite) -> None:
        try:
            store.write_batch(self.factory, source=SOURCE, external_id=external_id,
                              session_meta=meta, messages=messages, cursor=cursor, now=self.now)
        except SQLAlchemyError as exc:
            raise _Stop("db_busy" if _transient(exc) else "db_error") from None
        self.status.messages_written += len(messages)
        self.messages_left -= len(messages)


def _read(candidate: paths.Candidate, cursor: ConversationCursor | None, decided: Plan,
          policy: Policy, budget: int) -> tuple[Tail, str, datetime, bool]:
    """Open, read and close; parsing and masking happen after the descriptor is closed."""
    start, skipping, covered = decided.start, decided.skipping, decided.covered_since
    kept_size = min(HEAD_BYTES, (cursor.size or 0) if cursor is not None else 0)
    head_size = min(HEAD_BYTES, candidate.size)
    with paths.opened(candidate) as fd:
        # One snapshot of the head, taken before the tail: the digest compared and the digest
        # kept describe the same bytes, so a rewrite in place during the read is caught by the
        # next pass instead of being kept as the reference.
        data = head_bytes(fd, max(kept_size, head_size))
        if decided.check_head and cursor is not None:
            kept = hashlib.sha256(data[:kept_size]).hexdigest()
            if kept != cursor.head_sha256:  # replaced in place: read again from 0
                start, skipping, covered = 0, False, policy.retention_start
        tail = read_tail(fd, start=start, end=candidate.size, budget=budget, skipping=skipping)
    return tail, hashlib.sha256(data[:head_size]).hexdigest(), covered, start == 0


def _file(run: _Pass, candidate: paths.Candidate, cursor: ConversationCursor | None,
          decided: Plan) -> None:
    try:
        tail, head, covered, from_zero = _read(candidate, cursor, decided, run.policy,
                                               run.read_left)
    except paths.SourceRefused:
        run.status.codes["substituted"] += 1
        return
    except OSError:
        run.status.codes["file_unreadable"] += 1
        return
    status = run.status
    status.files_read += 1
    status.bytes_read += tail.read
    status.reads_from_zero += from_zero
    run.read_left -= tail.read
    if tail.oversized:
        status.codes["oversized"] += tail.oversized

    def cursor_at(offset: int, state: str) -> CursorWrite:
        # Every batch writes the whole identity, intermediate ones included (plan R16).
        return CursorWrite(candidate.path_key, candidate.file_id, candidate.size,
                           candidate.mtime_ns, offset, head, covered, state)

    stem = candidate.path.name.removesuffix(".jsonl")
    meta, pending = SessionMeta(), []
    final = ("skipping" if tail.skipping else "ok" if tail.at_end else "partial", tail.offset)
    for n, line in enumerate(tail.lines, start=1):
        got = parse_line(line.data, at_file_start=line.start == 0, stem=stem,
                         not_before=run.policy.retention_start)
        if got.kind != "ignored" and got.kind != "title":
            status.lines_judged += 1
        if got.reason:
            status.codes[got.reason] += 1
            run.bad += got.kind == "bad"
        if got.kind == "title":
            meta = meta.merge(title=got.title, title_kind=got.title_kind)
        elif got.kind == "message":
            pending.append(got.message)
            meta = meta.merge(workspace=got.workspace, git_branch=got.git_branch)
            status.codes["foreign_session"] += got.session_id_differs
        out_of_messages = len(pending) >= run.messages_left
        stop = n % STOP_CHECK_LINES == 0 and run.stopping.is_set()
        if out_of_messages or stop:
            final = ("partial", line.end)
            break
        if len(pending) >= BATCH:
            run.write(stem, meta, pending, cursor_at(line.end, "partial"))
            meta, pending = SessionMeta(title=meta.title, title_kind=meta.title_kind), []
            if run.stopping.is_set():
                raise _Stop("stopping")
    run.write(stem, meta, pending, cursor_at(final[1], final[0]))
    if run.stopping.is_set():
        raise _Stop("stopping")
    if final[0] == "partial":
        status.state = "partial"


def claude_pass(factory: sessionmaker[Session], configured_root: Path, policy: Policy, *,
                stopping: threading.Event, state: ProcessState, now: datetime,
                read_budget: int = READ_BUDGET,
                message_budget: int = MESSAGE_BUDGET) -> SourceStatus:
    run = _Pass(factory, policy, stopping, now, read_budget, message_budget)
    run.status.last_pass_at = now
    # Only a listing judged complete by this very pass may name the files present (spec §6.6).
    state.listed.pop(SOURCE, None)
    try:
        listing = paths.iter_claude(paths.check_root(configured_root, SOURCE))
    except paths.SourceRefused as exc:
        run.status.state, run.status.code = "unavailable", exc.code
        _log(run.status)
        return run.status
    run.status.codes.update(listing.codes)
    complete = not any(listing.codes[code] for code in INCOMPLETE)
    old: list[paths.Candidate] = []
    try:
        cursors = store.load_cursors(factory, SOURCE)
        for candidate in sorted(listing.candidates, key=lambda c: (-c.mtime_ns, c.path_key)):
            if stopping.is_set():
                raise _Stop("stopping")
            cursor = cursors.get(candidate.path_key)
            decided = plan(cursor, candidate, policy)
            if decided.action == "mark_old":
                if cursor is None or not unchanged(cursor, candidate):
                    old.append(candidate)
            elif decided.action == "read":
                if run.read_left < jsonl_tail.LINE_MAX or run.messages_left <= 0:
                    run.status.state = "partial"  # plan A4: the rest waits for the next pass
                    continue
                _file(run, candidate, cursor, decided)
        store.mark_old(factory, source=SOURCE, candidates=old, now=now)
    except _Stop as stop:
        run.status.state, run.status.code = "interrupted", stop.code
        if stop.code != "stopping":
            run.status.codes[stop.code] += 1
    except SQLAlchemyError as exc:
        run.status.state = "interrupted"
        run.status.code = "db_busy" if _transient(exc) else "db_error"
        run.status.codes[run.status.code] += 1
    judged = run.status.lines_judged
    if run.status.state in ("ok", "partial") and judged >= DEGRADED_MIN_LINES \
            and 2 * run.bad >= judged:  # an interruption keeps its state and its code
        run.status.state = "degraded"
    if complete and run.status.state in ("ok", "partial"):
        _presence(run, listing, state)
    _log(run.status)
    return run.status


def _presence(run: _Pass, listing: paths.Listing, state: ProcessState) -> None:
    present = {c.path.name.removesuffix(".jsonl") for c in listing.candidates}
    absent = state.absent_passes.setdefault(SOURCE, Counter())
    try:
        store.mark_presence(run.factory, source=SOURCE, present=present, absent_passes=absent,
                            now=run.now)
    except SQLAlchemyError as exc:
        run.status.state = "interrupted"
        run.status.code = "db_busy" if _transient(exc) else "db_error"
        run.status.codes[run.status.code] += 1
        return
    state.listed[SOURCE] = frozenset(c.path_key for c in listing.candidates)


def _log(status: SourceStatus) -> None:
    dropped = sum(n for code, n in status.codes.items() if code in LINE_CODES)
    detail = ", ".join(f"{code}={n}" for code, n in sorted(status.codes.items()) if n)
    log.info(
        "conversations %s : état=%s%s, %d fichiers lus, %d messages écrits, %d octets, "
        "%d lignes écartées (%s)", SOURCE, status.state,
        f" ({status.code})" if status.code else "", status.files_read,
        status.messages_written, status.bytes_read, dropped, detail or "aucun code")
