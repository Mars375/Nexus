"""modèle d'un run : colonne runs.model (ADR-023, addendum du 2026-11-11, lot H)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Native ALTER TABLE ... ADD COLUMN, deliberately not batch mode (same method as 0006): batch
    # rebuilds the table. Nullable and without default: runs created before this migration, and
    # runs of executors that serve no model, keep NULL. The closed list lives in
    # `runs.rules.RUN_MODELS`, not in a CHECK (SQLite would need a table rebuild).
    op.add_column("runs", sa.Column("model", sa.String(16)))


def downgrade() -> None:
    op.drop_column("runs", "model")
