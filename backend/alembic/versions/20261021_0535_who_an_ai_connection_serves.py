"""who an AI connection serves

``platform_ai_connections.community_ids``: the communities an operator's
connection serves, and only them. Empty, as every connection starts, it serves
every community no other connection is given to, which is what each did
before.

``guilds.allow_ai``: whether AI features may send a community's content to a
provider at all. Set by its seat under the ``restrictions`` option; true, as
every community starts.

``last_error`` and ``last_error_at`` on ``platform_ai_connections`` and on
every schema's ``guild_ai_connections``: the message code a connection's last
request failed with, and since when. Empty until one fails.

The seat writes its community's answer, so ``app_superadmin`` gets ``UPDATE``
on ``guilds.allow_ai`` beside the switches it already sets. The other columns
are read and written by whoever already reads and writes their tables.

Revision ID: 20261021_0535
Revises: 20261021_0534
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261021_0535"
down_revision = "20261021_0534"
branch_labels = None
depends_on = None

SEAT_FLOOR = "app_superadmin"


def _on_seat_floor(statement: str) -> None:
    """Run ``statement`` if the seat floor exists: the roles are cluster-global,
    and a database restored beside another deployment's may not carry them."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SEAT_FLOOR}') THEN
                EXECUTE '{statement}';
            END IF;
        END
        $$;
        """
    )


def _health() -> list[sa.Column]:
    return [
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.add_column(
        "platform_ai_connections",
        sa.Column(
            "community_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default="{}",
            nullable=False,
        ),
    )
    for column in _health():
        op.add_column("platform_ai_connections", column)
    op.add_column(
        "guilds",
        sa.Column("allow_ai", sa.Boolean(), server_default="true", nullable=False),
    )
    _on_seat_floor(f"GRANT UPDATE (allow_ai) ON public.guilds TO {SEAT_FLOOR}")
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for column in _health():
        op.add_column("guild_ai_connections", column)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
    _on_seat_floor(f"REVOKE UPDATE (allow_ai) ON public.guilds FROM {SEAT_FLOOR}")
    op.drop_column("guilds", "allow_ai")
    for name in ("last_error_at", "last_error", "community_ids"):
        op.drop_column("platform_ai_connections", name)


def _apply_downgrade() -> None:
    for name in ("last_error_at", "last_error"):
        op.drop_column("guild_ai_connections", name)
