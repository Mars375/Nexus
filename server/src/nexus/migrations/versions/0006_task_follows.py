"""lien « suite de » : colonne tasks.follows_id vers une tâche terminée (ADR-022)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Native ALTER TABLE ... ADD COLUMN, deliberately not batch mode: batch copies the table and
    # drops the old one, which with foreign keys on deletes the rows of task_dependencies,
    # task_comments and task_history (ON DELETE CASCADE). `inline_references=True` is required:
    # without it Alembic refuses a foreign key on an added SQLite column. Every row gets NULL
    # (no backfill: nothing says which task a past one corrected); done tasks become read-only
    # by the rule alone. The model declares the key without `ondelete`, which SQLAlchemy cannot
    # read back from a column-level reference (see models.Task.follows_id).
    op.add_column(
        "tasks",
        sa.Column("follows_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        inline_references=True,
    )
    op.create_index("ix_tasks_follows_id", "tasks", ["follows_id"])


def downgrade() -> None:
    # The index first: SQLite refuses to drop an indexed column. The links are lost; tasks,
    # dependencies, comments, history and events are untouched.
    op.drop_index("ix_tasks_follows_id", table_name="tasks")
    op.drop_column("tasks", "follows_id")
