"""initial : table app_meta

Revision ID: 0001
Revises:
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_meta",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )
    op.execute(
        "INSERT INTO app_meta (key, value) "
        "VALUES ('created_at', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
    )


def downgrade() -> None:
    op.drop_table("app_meta")
