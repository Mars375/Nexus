"""date de dernière utilisation des jetons d'acteur (issue #58)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TS = sa.String(length=40)  # AwareDateTime : ISO-8601 UTC


def upgrade() -> None:
    # Nullable, no backfill: an existing token has no recorded history of use.
    op.add_column("actor_tokens", sa.Column("last_used_at", TS))


def downgrade() -> None:
    op.drop_column("actor_tokens", "last_used_at")
