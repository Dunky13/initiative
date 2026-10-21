"""a member brings no AI key

A connection's key is its owner's: the operator's for a platform connection,
the community's for its own. Members configure nothing, so the tables that held
a member's key for a connection and their choice of connection go, in every
guild schema: ``guild_ai_member_keys``, ``ai_member_key_secrets`` beside it,
and ``guild_ai_member_prefs``. Their policies go with them. Nothing is carried:
the keys are destroyed with the tables.

``allow_member_keys`` goes from ``platform_ai_connections`` and from every
schema's ``guild_ai_connections``.

The downgrade restores the empty tables and the columns (``true``, their old
default). What they held is gone.

Revision ID: 20261021_0533
Revises: 20261021_0532
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261021_0533"
down_revision = "20261021_0532"
branch_labels = None
depends_on = None

KEYS = "guild_ai_member_keys"
KEY_SECRETS = "ai_member_key_secrets"
PREFS = "guild_ai_member_prefs"
COLUMN = "allow_member_keys"


def _allow_member_keys() -> sa.Column:
    return sa.Column(COLUMN, sa.Boolean(), server_default="true", nullable=False)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)
    op.drop_column("platform_ai_connections", COLUMN)


def _apply_upgrade() -> None:
    # Named in the schema being walked, never resolved through the search
    # path's fallback to ``public``. Policies go with the tables.
    for table in (KEY_SECRETS, KEYS, PREFS):
        op.execute(
            "DO $$ BEGIN EXECUTE format("
            f"'DROP TABLE IF EXISTS %I.{table}', current_schema()); END $$;"
        )
    op.drop_column("guild_ai_connections", COLUMN)


def downgrade() -> None:
    op.add_column("platform_ai_connections", _allow_member_keys())
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.add_column("guild_ai_connections", _allow_member_keys())
    op.create_table(
        KEYS,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("connection_scope", sa.String(length=20), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "connection_scope",
            "connection_id",
            name="uq_ai_member_key_user_connection",
        ),
    )
    op.create_index(f"ix_{KEYS}_user_id", KEYS, ["user_id"])
    op.create_table(
        KEY_SECRETS,
        sa.Column("key_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("api_key_encrypted", sa.String(length=2000), nullable=False),
        sa.ForeignKeyConstraint(["key_id"], [f"{KEYS}.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("key_id"),
    )
    op.execute(f"ALTER TABLE {KEY_SECRETS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {KEY_SECRETS} FORCE ROW LEVEL SECURITY")
    op.create_table(
        PREFS,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("connection_scope", sa.String(length=20), nullable=True),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{PREFS}_user_id", PREFS, ["user_id"], unique=True)
