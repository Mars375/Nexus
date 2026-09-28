"""tâches : tasks, task_dependencies, task_comments, task_history

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.String(length=40)  # AwareDateTime : ISO-8601 UTC


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("human_owner", sa.String(length=32), nullable=False),
        sa.Column("lead_agent", sa.String(length=32)),
        sa.Column("collaborators", sa.JSON(), nullable=False),
        sa.Column("next_action", sa.Text()),
        sa.Column("due_at", TS),
        sa.Column("follow_up_at", TS),
        sa.Column("block_cause", sa.Text()),
        sa.Column("block_plan", sa.Text()),
        sa.Column("drop_reason", sa.Text()),
        sa.Column("expected_evidence", sa.Text()),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("operation_role", sa.String(length=16)),
        sa.Column("origin", sa.Text()),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_human_owner", "tasks", ["human_owner"])
    # ADR-004 : au plus une opération principale en cours par humain, garanti par la base.
    op.create_index(
        "uq_tasks_one_main_in_progress", "tasks", ["human_owner"], unique=True,
        sqlite_where=sa.text("status = 'in_progress' AND operation_role = 'main'"),
    )

    op.create_table(
        "task_dependencies",
        sa.Column(
            "task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "task_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("at", TS, nullable=False),
    )
    op.create_index("ix_task_comments_task_id", "task_comments", ["task_id"])

    op.create_table(
        "task_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("at", TS, nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
    )
    op.create_index("ix_task_history_task_id", "task_history", ["task_id"])


def downgrade() -> None:
    op.drop_table("task_history")
    op.drop_table("task_comments")
    op.drop_table("task_dependencies")
    op.drop_table("tasks")
