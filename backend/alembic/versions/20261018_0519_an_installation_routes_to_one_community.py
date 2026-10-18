"""an installation routes to one community

``plugin_service_registrations.shared_routes`` says whether one vendor
installation may route to several communities, and is off unless the operator
turns it on. ``plugin_installs.exclusive`` is its negation on each install of the
registration's listing, and ``uq_plugin_installs_exclusive_route`` holds each
route of an exclusive install to one community.

A listing whose installs already share a route keeps sharing it: its
registration is written ``shared_routes`` and its installs not exclusive. Both
tables are FORCEd, so those writes run with FORCE lifted and restored around
them, before the index is made. A route held by an install already reported
removed is released on that install's next status or health result.

Revision ID: 20261018_0519
Revises: 20261018_0518
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "20261018_0519"
down_revision = "20261018_0518"
branch_labels = None
depends_on = None

INDEX = "uq_plugin_installs_exclusive_route"
TABLES = ("plugin_service_registrations", "plugin_installs")

#: The listings whose installs share a route.
SHARING = (
    "SELECT listing_uid FROM public.plugin_installs WHERE hook_route IS NOT NULL"
    " GROUP BY listing_uid, hook_route HAVING count(*) > 1"
)


def upgrade() -> None:
    op.add_column(
        "plugin_service_registrations",
        sa.Column(
            "shared_routes", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "plugin_installs",
        sa.Column("exclusive", sa.Boolean(), nullable=False, server_default="true"),
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "UPDATE public.plugin_service_registrations SET shared_routes = true"
            f" WHERE listing_uid IN ({SHARING})"
        )
        op.execute(
            "UPDATE public.plugin_installs SET exclusive = false"
            f" WHERE listing_uid IN ({SHARING})"
        )
    finally:
        for table in TABLES:
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    op.create_index(
        INDEX,
        "plugin_installs",
        ["listing_uid", "hook_route"],
        unique=True,
        postgresql_where=sa.text("exclusive AND hook_route IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="plugin_installs")
    op.drop_column("plugin_installs", "exclusive")
    op.drop_column("plugin_service_registrations", "shared_routes")
