"""Batch writes of the conversation index (spec §6.4, §6.6; plan PR 2 §5.6).

One short transaction per batch, which writes first (legacy transaction mode: a read keeps no
snapshot, and the write lock is taken by the first statement). A batch adds its messages, then
recomputes `message_count`, `started_at` and `last_message_at` from the table, and moves the
cursor, all in the same transaction: a crash between two batches leaves the last committed one,
and the unique keys absorb the next reading. No transaction is open while a file is read.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from nexus.conversations.masking import ParsedMessage
from nexus.conversations.models import Conversation, ConversationCursor, ConversationMessage
from nexus.conversations.paths import Candidate
from nexus.conversations.state import CursorWrite, SessionMeta

ABSENT_PASSES = 2  # complete listings in a row without the session before `missing_since`


def load_cursors(factory: sessionmaker[Session], source: str) -> dict[str, ConversationCursor]:
    with factory() as session:
        rows = session.scalars(
            select(ConversationCursor).where(ConversationCursor.source == source)).all()
        session.expunge_all()
    return {row.path_key: row for row in rows}


def _upsert_cursor(session: Session, source: str, cursor: CursorWrite, now: datetime) -> None:
    values = {
        "file_id": cursor.file_id, "size": cursor.size, "mtime_ns": cursor.mtime_ns,
        "byte_offset": cursor.byte_offset, "head_sha256": cursor.head_sha256,
        "covered_since": cursor.covered_since, "state": cursor.state, "updated_at": now,
    }
    stmt = insert(ConversationCursor).values(source=source, path_key=cursor.path_key, **values)
    session.execute(stmt.on_conflict_do_update(
        index_elements=["source", "path_key"], set_=values))


def _session_fields(current_title: str | None, meta: SessionMeta | None) -> dict:
    if meta is None:
        return {}
    fields = {}
    if meta.title is not None and (meta.title_kind == "custom" or current_title is None):
        fields["title"] = meta.title
    if meta.workspace is not None:
        fields["workspace"] = meta.workspace
    if meta.git_branch is not None:
        fields["git_branch"] = meta.git_branch
    return fields


def write_batch(factory: sessionmaker[Session], *, source: str, external_id: str,
                session_meta: SessionMeta | None, messages: list[ParsedMessage],
                cursor: CursorWrite, now: datetime) -> None:
    with factory.begin() as session:
        if messages:  # a conversation is only born with its first message
            session.execute(insert(Conversation).values(
                source=source, external_id=external_id, message_count=0, measured_at=now,
            ).on_conflict_do_nothing(index_elements=["source", "external_id"]))
        row = session.execute(select(Conversation.id, Conversation.title).where(
            Conversation.source == source, Conversation.external_id == external_id)).first()
        if row is not None:
            conversation_id, title = row
            if messages:
                session.execute(insert(ConversationMessage).values([
                    {"conversation_id": conversation_id, "external_id": m.external_id,
                     "role": m.role, "author": m.author, "at": m.at, "body": m.body,
                     "truncated": m.truncated, "redacted": m.redacted, "model": m.model}
                    for m in messages
                ]).on_conflict_do_nothing(index_elements=["conversation_id", "external_id"]))
            count, first, last = session.execute(select(
                func.count(), func.min(ConversationMessage.at), func.max(ConversationMessage.at),
            ).where(ConversationMessage.conversation_id == conversation_id)).one()
            session.execute(update(Conversation).where(Conversation.id == conversation_id).values(
                message_count=count, started_at=first, last_message_at=last, measured_at=now,
                missing_since=None, **_session_fields(title, session_meta)))
        _upsert_cursor(session, source, cursor, now)


def mark_old(factory: sessionmaker[Session], *, source: str, candidates: Iterable[Candidate],
             now: datetime) -> int:
    """`skipped_old` for files outside the window, never opened; one transaction."""
    candidates = list(candidates)
    if not candidates:
        return 0
    with factory.begin() as session:
        for candidate in candidates:
            values = {"file_id": candidate.file_id, "size": candidate.size,
                      "mtime_ns": candidate.mtime_ns, "byte_offset": 0, "head_sha256": None,
                      "covered_since": None, "state": "skipped_old", "updated_at": now}
            session.execute(insert(ConversationCursor).values(
                source=source, path_key=candidate.path_key, **values,
            ).on_conflict_do_update(index_elements=["source", "path_key"], set_=values))
    return len(candidates)


def mark_presence(factory: sessionmaker[Session], *, source: str, present: set[str],
                  absent_passes: Counter, now: datetime) -> None:
    """After a complete listing: `missing_since` at the second pass without the session, and
    cleared once it is back. Writes only what changes."""
    with factory() as session:
        rows = session.execute(select(
            Conversation.id, Conversation.external_id, Conversation.missing_since,
        ).where(Conversation.source == source)).all()
    back, missing = [], []
    for conversation_id, external_id, missing_since in rows:
        if external_id in present:
            absent_passes.pop(external_id, None)
            if missing_since is not None:
                back.append(conversation_id)
            continue
        absent_passes[external_id] += 1
        if absent_passes[external_id] >= ABSENT_PASSES and missing_since is None:
            missing.append(conversation_id)
    for gone in set(absent_passes) - {row[1] for row in rows}:
        del absent_passes[gone]
    if not (back or missing):
        return
    with factory.begin() as session:
        if back:
            session.execute(update(Conversation).where(Conversation.id.in_(back)).values(
                missing_since=None))
        if missing:
            session.execute(update(Conversation).where(Conversation.id.in_(missing)).values(
                missing_since=now))
