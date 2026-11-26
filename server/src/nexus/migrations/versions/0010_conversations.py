"""index des conversations : tables, FTS5 à contenu externe et déclencheurs (ADR-025, PR 1)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# Frozen copy of nexus.conversations.models: a migration never follows later changes of the model.
SOURCES = ("claude-code", "codex", "hermes")
ROLES = ("user", "assistant")
CURSOR_STATES = ("partial", "skipping", "ok", "too_large", "unreadable", "skipped_old")
TS = sa.String(length=40)  # AwareDateTime: ISO-8601 UTC
FTS_PROBE = "CREATE VIRTUAL TABLE temp.nexus_fts5_probe USING fts5(x)"
NO_FTS5 = "SQLite sans FTS5"

FTS = (
    "CREATE VIRTUAL TABLE conversation_fts USING fts5("
    "body, content='conversation_messages', content_rowid='id', "
    "tokenize='unicode61 remove_diacritics 2')"
)
TRIGGERS = {
    "conversation_messages_ai": (
        "AFTER INSERT ON conversation_messages BEGIN "
        "INSERT INTO conversation_fts(rowid, body) VALUES (new.id, new.body); END"
    ),
    "conversation_messages_ad": (
        "AFTER DELETE ON conversation_messages BEGIN "
        "INSERT INTO conversation_fts(conversation_fts, rowid, body) "
        "VALUES ('delete', old.id, old.body); END"
    ),
    "conversation_messages_au": (
        "AFTER UPDATE ON conversation_messages BEGIN "
        "INSERT INTO conversation_fts(conversation_fts, rowid, body) "
        "VALUES ('delete', old.id, old.body); "
        "INSERT INTO conversation_fts(rowid, body) VALUES (new.id, new.body); END"
    ),
}


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _require_fts5() -> None:
    # First, before any creation: SQLite DDL is not transactional under Alembic
    # (`transactional_ddl` is False), so a table created before a failure would stay.
    bind = op.get_bind()
    try:
        bind.exec_driver_sql(FTS_PROBE)
    except sa.exc.OperationalError:
        raise RuntimeError(NO_FTS5) from None
    bind.exec_driver_sql("DROP TABLE temp.nexus_fts5_probe")


def upgrade() -> None:
    _require_fts5()
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("channel", sa.String(32)),
        # Masked text (spec §7.1), cut to its length afterwards.
        sa.Column("title", sa.String(200)),
        sa.Column("workspace", sa.String(500)),
        sa.Column("git_branch", sa.String(200)),
        sa.Column("started_at", TS),
        sa.Column("last_message_at", TS),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("missing_since", TS),
        sa.Column("measured_at", TS, nullable=False),
        sa.UniqueConstraint("source", "external_id", name="uq_conversations_source_external_id"),
        sa.CheckConstraint(f"source IN ({_in_list(SOURCES)})", name="ck_conversations_source"),
        sa.CheckConstraint("length(external_id) BETWEEN 1 AND 128",
                           name="ck_conversations_external_id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_conversations_last_message_at", "conversations",
                    ["last_message_at", "id"])
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("author", sa.String(32), nullable=False),  # no CHECK, as runs.model
        sa.Column("at", TS, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("redacted", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(64)),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("conversation_id", "external_id",
                            name="uq_conversation_messages_conversation_id_external_id"),
        sa.CheckConstraint(f"role IN ({_in_list(ROLES)})", name="ck_conversation_messages_role"),
        # `length()` stops at the first NUL: `instr` keeps a NUL from hiding a longer body.
        sa.CheckConstraint("length(body) BETWEEN 1 AND 16000 AND instr(body, char(0)) = 0",
                           name="ck_conversation_messages_body"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_conversation_messages_conversation_id_at", "conversation_messages",
                    ["conversation_id", "at"])
    op.create_table(
        "conversation_cursors",
        sa.Column("source", sa.String(16), primary_key=True),
        sa.Column("path_key", sa.String(512), primary_key=True),
        sa.Column("file_id", sa.String(64)),  # "<st_dev>:<st_ino>", read by os.lstat
        sa.Column("size", sa.Integer()),
        sa.Column("mtime_ns", sa.Integer()),
        sa.Column("byte_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("head_sha256", sa.String(64)),
        sa.Column("last_row_id", sa.Integer()),
        sa.Column("window_from_id", sa.Integer()),
        sa.Column("covered_since", TS),
        sa.Column("session_external_id", sa.String(128)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(f"source IN ({_in_list(SOURCES)})",
                           name="ck_conversation_cursors_source"),
        sa.CheckConstraint(f"state IN ({_in_list(CURSOR_STATES)})",
                           name="ck_conversation_cursors_state"),
        sa.CheckConstraint("length(path_key) BETWEEN 1 AND 512",
                           name="ck_conversation_cursors_path_key"),
    )
    op.execute(FTS)
    for name, body in TRIGGERS.items():
        op.execute(f"CREATE TRIGGER {name} {body}")


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER {name}")
    op.execute("DROP TABLE conversation_fts")  # its shadow tables go with it
    op.drop_index("ix_conversation_messages_conversation_id_at",
                  table_name="conversation_messages")
    op.drop_index("ix_conversations_last_message_at", table_name="conversations")
    # Child before parent: the migration engine has foreign_keys=ON. Other tables are untouched.
    op.drop_table("conversation_cursors")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
