"""jetons d'acteur : empreintes SHA-256 des jetons porteurs (ADR-020)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.String(length=40)  # AwareDateTime : ISO-8601 UTC

# Frozen copy of nexus.actors.ACTORS at this revision: a migration never imports live code.
ACTORS = ("loic", "helios", "mnema", "aether", "artemis", "claude", "codex", "orca", "hermes")


def upgrade() -> None:
    # Only the SHA-256 digest is stored, never the token (ADR-020, D2). No backfill.
    op.create_table(
        "actor_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        sa.UniqueConstraint("token_hash", name="uq_actor_tokens_token_hash"),
        sa.CheckConstraint(
            "actor IN (" + ", ".join(f"'{a}'" for a in ACTORS) + ")",
            name="ck_actor_tokens_actor",
        ),
        sa.CheckConstraint("length(label) BETWEEN 1 AND 64", name="ck_actor_tokens_label"),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_actor_tokens_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("actor_tokens")
