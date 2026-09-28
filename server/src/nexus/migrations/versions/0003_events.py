"""événements des agents : events

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.String(length=40)  # AwareDateTime : ISO-8601 UTC


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("actor_event_id", sa.String(length=128), nullable=False),
        sa.Column("at", TS, nullable=False),
        sa.Column("received_at", TS, nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("run_ref", sa.String(length=128)),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("requested_kind", sa.String(length=16)),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("needs", sa.JSON(), nullable=False),
        sa.Column("redacted", sa.JSON(), nullable=False),
        sa.Column("effects", sa.JSON(), nullable=False),
        sa.UniqueConstraint("actor", "actor_event_id", name="uq_events_actor_event_id"),
    )
    op.create_index("ix_events_actor", "events", ["actor"])
    op.create_index("ix_events_task_id", "events", ["task_id"])
    op.create_index("ix_events_kind", "events", ["kind"])


def downgrade() -> None:
    op.drop_table("events")
