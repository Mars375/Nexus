"""Tables of the conversation index (spec §4.1, ADR-025; DATA-MODEL §2.7, §2.8).

The index is rebuildable from the sources and never leaves `nexus.db`: each backup copy is
emptied of it (`nexus.backup`). The FTS5 table `conversation_fts` and its shadow tables are
created by migration 0010 in raw SQL; they are not in `Base.metadata`, and `include_object`
hides exactly those five names from `compare_metadata`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.db import AwareDateTime, Base

SOURCES = ("claude-code", "codex", "hermes")
ROLES = ("user", "assistant")
CURSOR_STATES = ("partial", "skipping", "ok", "too_large", "unreadable", "skipped_old")
BODY_MAX = 16000

FTS_TABLE = "conversation_fts"
# The FTS5 table and its four shadow tables: an exact set, never a prefix.
FTS_TABLES = frozenset(
    {FTS_TABLE, *(f"{FTS_TABLE}_{part}" for part in ("data", "idx", "docsize", "config"))}
)
FTS_PROBE = "CREATE VIRTUAL TABLE temp.nexus_fts5_probe USING fts5(x)"
NO_FTS5 = "SQLite sans FTS5"


def include_object(_object, name, type_, _reflected, _compare_to) -> bool:
    """Alembic filter: hide the FTS tables (created in raw SQL), nothing else."""
    return not (type_ == "table" and name in FTS_TABLES)


def require_fts5(connect: Callable[[str], sqlite3.Connection] = sqlite3.connect) -> None:
    """Fail closed when this SQLite has no FTS5, with a fixed message (spec §4.1)."""
    conn = connect(":memory:")
    try:
        conn.execute(FTS_PROBE)
    except sqlite3.OperationalError:
        raise RuntimeError(NO_FTS5) from None
    finally:
        conn.close()


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Conversation(Base):
    """One session read from a source. `nx-conv-<n>` is a handle on this index row, not the
    session's identity: that is `<source>-session:<external_id>` (DATA-MODEL §2.7). A purge
    followed by a new read gives a new handle; AUTOINCREMENT never hands an old one out again.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_conversations_source_external_id"),
        CheckConstraint(f"source IN ({_in_list(SOURCES)})", name="ck_conversations_source"),
        CheckConstraint("length(external_id) BETWEEN 1 AND 128",
                        name="ck_conversations_external_id"),
        Index("ix_conversations_last_message_at", "last_message_at", "id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(128))
    # Hermes: the session's own source (`cli`); NULL for the other sources.
    channel: Mapped[str | None] = mapped_column(String(32))
    # Already masked text (spec §7.1), then cut to the length: nothing in this lot writes it raw.
    title: Mapped[str | None] = mapped_column(String(200))
    workspace: Mapped[str | None] = mapped_column(String(500))
    git_branch: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime)
    last_message_at: Mapped[datetime | None] = mapped_column(AwareDateTime)
    message_count: Mapped[int] = mapped_column(Integer)
    missing_since: Mapped[datetime | None] = mapped_column(AwareDateTime)
    measured_at: Mapped[datetime] = mapped_column(AwareDateTime)

    @property
    def ref(self) -> str:
        return f"nx-conv-{self.id}"


class ConversationMessage(Base):
    """A human message or a model's answer (DATA-MODEL §2.8). `body` is masked text, 1 to 16 000
    characters without NUL (SQLite's `length()` stops at the first NUL), held by the database."""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "external_id",
                         name="uq_conversation_messages_conversation_id_external_id"),
        CheckConstraint(f"role IN ({_in_list(ROLES)})", name="ck_conversation_messages_role"),
        CheckConstraint(
            f"length(body) BETWEEN 1 AND {BODY_MAX} AND instr(body, char(0)) = 0",
            name="ck_conversation_messages_body",
        ),
        Index("ix_conversation_messages_conversation_id_at", "conversation_id", "at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    # Claude `uuid`, Codex `ordinal`, Hermes `messages.id`, all stored as text.
    external_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))
    # No CHECK, as `runs.model`: `loic` only when the source proves it, else `unknown` (ADR-005).
    author: Mapped[str] = mapped_column(String(32))
    at: Mapped[datetime] = mapped_column(AwareDateTime)
    body: Mapped[str] = mapped_column(Text)
    truncated: Mapped[bool] = mapped_column(Boolean)
    redacted: Mapped[bool] = mapped_column(Boolean)
    model: Mapped[str | None] = mapped_column(String(64))

    @property
    def ref(self) -> str:
        return f"nx-msg-{self.id}"


class ConversationCursor(Base):
    """Where the reading of one source file (or Hermes `state.db`) stands; never exposed by the
    API. `path_key` is relative to the root; `file_id` is `"<st_dev>:<st_ino>"` read by
    `os.lstat` (an NTFS file index can exceed SQLite's signed 64-bit integer)."""

    __tablename__ = "conversation_cursors"
    __table_args__ = (
        CheckConstraint(f"source IN ({_in_list(SOURCES)})",
                        name="ck_conversation_cursors_source"),
        CheckConstraint(f"state IN ({_in_list(CURSOR_STATES)})",
                        name="ck_conversation_cursors_state"),
        CheckConstraint("length(path_key) BETWEEN 1 AND 512",
                        name="ck_conversation_cursors_path_key"),
    )

    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    path_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    file_id: Mapped[str | None] = mapped_column(String(64))
    size: Mapped[int | None] = mapped_column(Integer)
    mtime_ns: Mapped[int | None] = mapped_column(Integer)
    # Not `offset`, a reserved word of SQL.
    byte_offset: Mapped[int] = mapped_column(Integer, server_default="0")
    head_sha256: Mapped[str | None] = mapped_column(String(64))
    last_row_id: Mapped[int | None] = mapped_column(Integer)
    window_from_id: Mapped[int | None] = mapped_column(Integer)  # Hermes only
    covered_since: Mapped[datetime | None] = mapped_column(AwareDateTime)  # files only
    session_external_id: Mapped[str | None] = mapped_column(String(128))  # Codex only
    state: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime)
