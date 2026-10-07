"""approbations : état de décision des demandes adressées à un humain

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TS = sa.String(length=40)  # AwareDateTime : ISO-8601 UTC


def upgrade() -> None:
    # No backfill (ADR-019, D6): asks published before this migration get no approval.
    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("ask_kind", sa.String(length=16), nullable=False),
        sa.Column("expires_at", TS),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("response_event_id", sa.Integer(), sa.ForeignKey("events.id")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("request_event_id", name="uq_approvals_request_event_id"),
        sa.UniqueConstraint("response_event_id", name="uq_approvals_response_event_id"),
    )
    op.create_index("ix_approvals_status", "approvals", ["status"])


def downgrade() -> None:
    op.drop_table("approvals")
