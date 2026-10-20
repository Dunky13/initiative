"""plugin entitlements

A listing's terms come from the package that serves it, and a community's
statement and usage for a plug-in are kept here:

* ``marketplace_listings`` gains ``access`` (NULL, ``open`` or ``entitled``),
  ``meters`` and ``mandatory``, written only from the registry's ``package``
  role under the shipped root. A CHECK holds them to the two shapes terms take.
* ``plugin_entitlements``: the current statement per (community, listing).
* ``plugin_usage``: the latest reported total per (community, listing, meter,
  month).
* ``plugin_service_registrations`` loses ``reference_sectors`` and
  ``root_is_builtin``, which only the retired reference-sector channel read.

Both new tables are app_admin-only: RLS enabled and forced with no policies,
and the schema's default grants revoked from the two base roles. They are new
and empty, so nothing is backfilled.

Revision ID: 20261016_0512
Revises: 20261016_0511
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20261016_0512"
down_revision = "20261016_0511"
branch_labels = None
depends_on = None

LISTINGS = "marketplace_listings"
REGISTRATIONS = "plugin_service_registrations"

TERMS_CHECK = (
    "(access IS NULL AND NOT mandatory AND cardinality(meters) = 0)"
    " OR (access = 'entitled' AND NOT mandatory AND cardinality(meters) = 0)"
    " OR (access = 'open' AND mandatory)"
)


def upgrade() -> None:
    # --- a listing's package terms -------------------------------------------
    op.add_column(LISTINGS, sa.Column("access", sa.String(16), nullable=True))
    op.add_column(
        LISTINGS,
        sa.Column(
            "meters",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        LISTINGS,
        sa.Column("mandatory", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_check_constraint(
        "ck_marketplace_listings_package_terms", LISTINGS, TERMS_CHECK
    )

    # --- what the retired reference-sector channel read -----------------------
    op.drop_column(REGISTRATIONS, "reference_sectors")
    op.drop_column(REGISTRATIONS, "root_is_builtin")

    # --- statements and usage ----------------------------------------------------
    op.create_table(
        "plugin_entitlements",
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("listing_uid", sa.String(14), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("values", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id", "listing_uid"),
        sa.CheckConstraint("version >= 1", name="ck_plugin_entitlements_version"),
        sa.CheckConstraint(
            "jsonb_typeof(\"values\") = 'object'",
            name="ck_plugin_entitlements_values_object",
        ),
    )
    op.create_table(
        "plugin_usage",
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("listing_uid", sa.String(14), nullable=False),
        sa.Column("meter", sa.String(64), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guild_id", "listing_uid", "meter", "period"),
        sa.CheckConstraint("quantity >= 0", name="ck_plugin_usage_quantity"),
        sa.CheckConstraint(
            "period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_plugin_usage_period"
        ),
        sa.CheckConstraint(
            "meter ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_plugin_usage_meter"
        ),
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for table in ("plugin_entitlements", "plugin_usage"):
        for statement in (
            f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
            # The public schema default-grants platform_base + app_guild_base full
            # DML on every new table; both come straight back off.
            f'REVOKE ALL ON TABLE public.{table} FROM app_guild_base, "{base}"',
            f"GRANT SELECT, INSERT, UPDATE ON TABLE public.{table} TO app_admin",
        ):
            op.execute(statement)


def downgrade() -> None:
    op.drop_table("plugin_usage")
    op.drop_table("plugin_entitlements")
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "root_is_builtin", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "reference_sectors",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.drop_constraint("ck_marketplace_listings_package_terms", LISTINGS)
    op.drop_column(LISTINGS, "mandatory")
    op.drop_column(LISTINGS, "meters")
    op.drop_column(LISTINGS, "access")
