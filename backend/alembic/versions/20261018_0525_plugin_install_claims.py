"""plugin install claims

``public.plugin_install_claims``: the values each install holds for its
plug-in's unique settings, the current one and those it was renamed from, one
row each. A unique index on ``(listing_uid, key, value)`` keeps two installs
of a plug-in from holding the same value. A row goes with its install's
``plugin_installs`` row.

RLS enabled and forced, the schema's default grants revoked from the two base
roles, ``app_admin`` granted DML and ``app_guild_base`` INSERT and SELECT (its
read floor SELECT), under the registry's policies for the routed community.
The table is new and empty, so nothing is backfilled.

Revision ID: 20261018_0525
Revises: 20261018_0524
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261018_0525"
down_revision = "20261018_0524"
branch_labels = None
depends_on = None

TABLE = "plugin_install_claims"
INDEX = "uq_plugin_install_claims_value"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("install_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=16), nullable=False),
        sa.Column("listing_uid", sa.String(length=14), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "install_id"],
            ["plugin_installs.guild_id", "plugin_installs.install_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("guild_id", "install_id", "key", "value"),
    )
    op.create_index(INDEX, TABLE, ["listing_uid", "key", "value"], unique=True)

    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        f'REVOKE ALL ON TABLE public.{TABLE} FROM app_guild_base, "{base}"',
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{TABLE} TO app_admin",
        f"GRANT SELECT, INSERT ON TABLE public.{TABLE} TO app_guild_base",
        f"GRANT SELECT ON TABLE public.{TABLE} TO app_guild_base_ro",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
    op.drop_table(TABLE)
