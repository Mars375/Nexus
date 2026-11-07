"""table runs : travail confié à un exécutant (ADR-023, lot B)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Frozen copy of nexus.runs.states: a migration never follows later changes of the model.
STATUSES = (
    "dispatched", "running", "blocked", "review", "done", "failed", "cancelled", "unknown",
)
ACTIVE = ("dispatched", "running", "unknown")
TS = sa.String(length=40)  # AwareDateTime : ISO-8601 UTC


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("executor", sa.String(32), nullable=False),
        sa.Column("agent", sa.String(32), nullable=False),
        sa.Column("dispatched_by", sa.String(32), nullable=False),
        sa.Column("client_key", sa.String(128), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("workdir", sa.Text()),
        sa.Column("external_ref", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("native_status", sa.String(64)),
        sa.Column("watch_cursor", sa.Text()),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("ended_at", TS),
        sa.Column("cancel_requested_at", TS),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("dispatched_by", "client_key", name="uq_runs_dispatched_by_client_key"),
        sa.CheckConstraint(f"status IN ({_in_list(STATUSES)})", name="ck_runs_status"),
        sa.CheckConstraint("length(client_key) BETWEEN 1 AND 128", name="ck_runs_client_key"),
    )
    op.create_index("ix_runs_task_id", "runs", ["task_id"])
    op.create_index(
        "uq_runs_one_active_per_agent_task", "runs", ["task_id", "agent"], unique=True,
        sqlite_where=sa.text(f"status IN ({_in_list(ACTIVE)})"),
    )

    op.create_index(
        "uq_runs_one_active_per_executor", "runs", ["executor"], unique=True,
        sqlite_where=sa.text(f"status IN ({_in_list(ACTIVE)})"),
    )


def downgrade() -> None:
    op.drop_index("uq_runs_one_active_per_executor", table_name="runs")
    # Only the runs are lost: tasks and events (which carry the run references) are untouched.
    op.drop_index("uq_runs_one_active_per_agent_task", table_name="runs")
    op.drop_index("ix_runs_task_id", table_name="runs")
    op.drop_table("runs")
