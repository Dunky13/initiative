"""subscription notices

``subscription_notices``, in every guild schema: which transactions of the
change log the people subscribed to what they changed have been told about.
Its policies are rendered from the registry at boot.

Revision ID: 20261018_0519
Revises: 20261018_0518
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261018_0519"
down_revision = "20261018_0518"
branch_labels = None
depends_on = None


def _apply_upgrade() -> None:
    op.create_table(
        "subscription_notices",
        sa.Column("txn_id", sa.BigInteger(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("txn_id"),
    )


def _apply_downgrade() -> None:
    op.drop_table("subscription_notices")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
