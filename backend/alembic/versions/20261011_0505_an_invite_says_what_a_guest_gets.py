"""an invite says what a guest gets

``guest_invite_grants``, in every guild schema: the initiatives and items a
guest invite gives whoever redeems it. Its CHECKs and policies are rendered
from the model and the registry at boot.

Revision ID: 20261011_0505
Revises: 20261011_0504
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261011_0505"
down_revision = "20261011_0504"
branch_labels = None
depends_on = None


def _create() -> None:
    op.create_table(
        "guest_invite_grants",
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invite_id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guest_invite_grants_invite_id", "guest_invite_grants", ["invite_id"]
    )


def _drop() -> None:
    op.drop_table("guest_invite_grants")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _create)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
