"""Purge of the conversation index (spec §6.6, with the corrections of plan PR 2 §5.7, §5.9).

The purge removes disabled sources, sessions gone for 24 h and messages older than the
retention, in batches of 500 messages (one short transaction each), so an API writer only waits
for one batch. Each committed batch raises `rebuild_pending`: the FTS is then rebuilt, which is
what really drops the purged terms from its blocks (`optimize` leaves some, depending on the
layout), and the WAL is truncated by a checkpoint with a short busy timeout, retried at every
pass while it is busy. `secure_delete` is on for every connection (`nexus.db.make_engine`).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from nexus.conversations.models import Conversation, ConversationCursor
from nexus.conversations.state import ProcessState, PurgeResult
from nexus.db import AwareDateTime

log = logging.getLogger("nexus.conversations")

MISSING_GRACE = timedelta(hours=24)
PURGE_EVERY = timedelta(hours=24)
BATCH = 500
CHECKPOINT_TIMEOUT = 0.25  # seconds: a reader must not hold the checkpoint (and writers) for 5 s
CODES = frozenset({"db_busy", "db_error", "stopping"})
_REBUILD = "INSERT INTO conversation_fts(conversation_fts) VALUES('rebuild')"
_RECOUNT = text(
    "UPDATE conversations SET "
    "message_count = (SELECT count(*) FROM conversation_messages m "
    "WHERE m.conversation_id = conversations.id), "
    "started_at = (SELECT min(at) FROM conversation_messages m "
    "WHERE m.conversation_id = conversations.id), "
    "last_message_at = (SELECT max(at) FROM conversation_messages m "
    "WHERE m.conversation_id = conversations.id) "
    "WHERE id IN (SELECT value FROM json_each(:ids))"
)


class _Stopped(Exception):
    pass


def purge_due(state: ProcessState, now: datetime) -> bool:
    return (state.last_purge_at is None
            or now.astimezone(UTC) - state.last_purge_at.astimezone(UTC) >= PURGE_EVERY)


def index_not_empty(factory: sessionmaker[Session]) -> bool:
    """Messages left, or FTS segments left: a purge cut short after its last delete leaves an
    empty table but its terms in the FTS blocks (an empty or rebuilt index only holds the rows
    with ids 1 and 10)."""
    with factory() as session:
        return any(session.execute(text(sql)).first() is not None for sql in (
            "SELECT 1 FROM conversation_messages LIMIT 1",
            "SELECT 1 FROM conversation_fts_data WHERE id > 10 LIMIT 1",
        ))


def _delete_messages(factory: sessionmaker[Session], where: str, params: dict,
                     state: ProcessState, stopping: threading.Event, result: PurgeResult) -> None:
    """Delete the messages that `where` selects (on `m` joined to `c`), 500 per transaction."""
    pick = text(
        "SELECT m.id, m.conversation_id FROM conversation_messages m "
        f"JOIN conversations c ON c.id = m.conversation_id WHERE {where} LIMIT {BATCH}")
    while True:
        if stopping.is_set():
            raise _Stopped
        with factory.begin() as session:
            rows = session.execute(pick, params).all()
            if not rows:
                return
            ids = ",".join(str(row[0]) for row in rows)
            touched = sorted({row[1] for row in rows})
            session.execute(text(f"DELETE FROM conversation_messages WHERE id IN ({ids})"))
            session.execute(_RECOUNT, {"ids": str(touched)})
            gone = session.execute(delete(Conversation).where(
                Conversation.id.in_(touched), Conversation.message_count == 0))
        result.messages += len(rows)
        result.conversations += gone.rowcount
        state.rebuild_pending = True  # set by every committed batch (plan A15)


def _drop_source(factory, source: str, state, stopping, result) -> None:
    with factory() as session:  # an empty source costs two SELECTs, no write
        held = any(session.execute(select(model.source).where(model.source == source)
                                   .limit(1)).first() for model in (Conversation,
                                                                    ConversationCursor))
    if not held:
        return
    _delete_messages(factory, "c.source = :source", {"source": source}, state, stopping,
                     result)
    with factory.begin() as session:
        gone = session.execute(delete(Conversation).where(Conversation.source == source))
        cursors = session.execute(delete(ConversationCursor).where(
            ConversationCursor.source == source))
    result.conversations += gone.rowcount
    result.cursors += cursors.rowcount
    state.listed.pop(source, None)
    state.absent_passes.pop(source, None)


def _drop_missing(factory, now: datetime, state, stopping, result) -> None:
    cutoff = now.astimezone(UTC) - MISSING_GRACE
    with factory() as session:
        gone = [row for row in session.execute(select(
            Conversation.id, Conversation.missing_since).where(
            Conversation.missing_since.is_not(None))).all() if row[1] <= cutoff]
    for conversation_id, _ in gone:
        _delete_messages(factory, "c.id = :id", {"id": conversation_id}, state, stopping,
                         result)
        with factory.begin() as session:  # an empty conversation already went with its batch
            result.conversations += session.execute(delete(Conversation).where(
                Conversation.id == conversation_id)).rowcount
    for source, listed in state.listed.items():
        with factory() as session:
            stale = [key for key, updated_at in session.execute(select(
                ConversationCursor.path_key, ConversationCursor.updated_at).where(
                ConversationCursor.source == source)).all()
                if key not in listed and updated_at <= cutoff]
        if stale:
            with factory.begin() as session:
                result.cursors += session.execute(delete(ConversationCursor).where(
                    ConversationCursor.source == source,
                    ConversationCursor.path_key.in_(stale))).rowcount


def _apply_retention(factory, threshold: datetime, state, stopping, result) -> None:
    # `at` is ISO-8601 UTC from AwareDateTime: as a string it sorts as the instant does.
    bound = AwareDateTime().process_bind_param(threshold, None)
    _delete_messages(factory, "m.at < :threshold", {"threshold": bound}, state, stopping,
                     result)
    with factory() as session:
        behind = [(source, key) for source, key, covered in session.execute(select(
            ConversationCursor.source, ConversationCursor.path_key,
            ConversationCursor.covered_since).where(
            ConversationCursor.source != "hermes",
            ConversationCursor.covered_since.is_not(None))).all() if covered < threshold]
    for start in range(0, len(behind), BATCH):
        with factory.begin() as session:
            for source, key in behind[start:start + BATCH]:
                session.execute(update(ConversationCursor).where(
                    ConversationCursor.source == source, ConversationCursor.path_key == key,
                ).values(covered_since=threshold))


def purge(factory: sessionmaker[Session], *, now: datetime, retention_days: int,
          disabled: frozenset[str], state: ProcessState,
          stopping: threading.Event) -> PurgeResult:
    """One purge; `last_purge_at` only moves on a complete one. Never raises a DB error."""
    result = PurgeResult()
    now = now.astimezone(UTC)  # elapsed time, never wall-clock time across a DST change
    try:
        for source in sorted(disabled):
            _drop_source(factory, source, state, stopping, result)
        _drop_missing(factory, now, state, stopping, result)
        _apply_retention(factory, now - timedelta(days=retention_days), state, stopping,
                         result)
    except _Stopped:
        result.complete, result.code = False, "stopping"
    except Exception as exc:  # noqa: BLE001 - logged by fixed code only (ADR-006)
        result.complete, result.code = False, _code(exc)
    if result.complete:
        state.last_purge_at = now
    return result


def _code(exc: Exception) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    return "db_busy" if "locked" in message or "busy" in message else "db_error"


def rebuild(factory: sessionmaker[Session], state: ProcessState) -> bool:
    """Rebuild the FTS from the messages; `rebuild_pending` drops only once it committed."""
    try:
        with factory.begin() as session:
            session.execute(text(_REBUILD))
    except Exception as exc:  # noqa: BLE001
        log.warning("conversations : reconstruction de l'index différée (%s)", _code(exc))
        return False
    state.rebuild_pending = False
    state.checkpoint_pending = True
    return True


def checkpoint(db_path: Path) -> bool:
    """`wal_checkpoint(TRUNCATE)` on its own connection, 0.25 s at most; True once truncated."""
    try:
        conn = sqlite3.connect(db_path, timeout=CHECKPOINT_TIMEOUT)
        try:
            busy, _, _ = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.warning("conversations : point de contrôle différé (%s)",
                    getattr(exc, "sqlite_errorname", type(exc).__name__))
        return False
    return busy == 0


def log_purge(result: PurgeResult, *, rebuilt: bool, checkpointed: bool | None) -> None:
    log.info(
        "conversations : purge de %d messages, %d conversations, %d curseurs, rebuild=%s, "
        "point de contrôle=%s%s", result.messages, result.conversations, result.cursors,
        "oui" if rebuilt else "non",
        "fait" if checkpointed else "en attente" if checkpointed is False else "sans objet",
        "" if result.complete else f", interrompue ({result.code})")
