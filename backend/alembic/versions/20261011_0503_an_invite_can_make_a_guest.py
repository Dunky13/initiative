"""an invite can make a guest

- ``guild_invites.guest_days`` and ``guild_invites.guest_role``: an invite
  with them makes its redeemer a guest, with that rung, for that many days.
  Both are set or neither is.
- ``guilds.guest_max_days``: the longest a community lets a guest stay. NULL
  leaves only the deployment's ceiling. The seat writes it, so
  ``app_superadmin`` gets ``UPDATE`` on the column beside the rules it
  already sets.

Revision ID: 20261011_0503
Revises: 20261011_0502
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261011_0503"
down_revision = "20261011_0502"
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


def upgrade() -> None:
    op.add_column(
        "guild_invites",
        sa.Column("guest_days", sa.Integer(), nullable=True),
        schema="public",
    )
    op.add_column(
        "guild_invites",
        sa.Column(
            "guest_role",
            postgresql.ENUM(name="guild_role", create_type=False),
            nullable=True,
        ),
        schema="public",
    )
    op.create_check_constraint(
        "ck_guild_invites_guest_days",
        "guild_invites",
        "guest_days >= 1",
        schema="public",
    )
    op.create_check_constraint(
        "ck_guild_invites_guest_terms",
        "guild_invites",
        "(guest_days IS NULL) = (guest_role IS NULL)",
        schema="public",
    )
    op.add_column(
        "guilds",
        sa.Column("guest_max_days", sa.Integer(), nullable=True),
        schema="public",
    )
    op.create_check_constraint(
        "ck_guilds_guest_max_days",
        "guilds",
        "guest_max_days >= 1",
        schema="public",
    )
    _on_seat_floor(f"GRANT UPDATE (guest_max_days) ON public.guilds TO {SEAT_FLOOR}")


def downgrade() -> None:
    _on_seat_floor(f"REVOKE UPDATE (guest_max_days) ON public.guilds FROM {SEAT_FLOOR}")
    op.drop_constraint("ck_guilds_guest_max_days", "guilds", schema="public")
    op.drop_column("guilds", "guest_max_days", schema="public")
    op.drop_constraint("ck_guild_invites_guest_terms", "guild_invites", schema="public")
    op.drop_constraint("ck_guild_invites_guest_days", "guild_invites", schema="public")
    op.drop_column("guild_invites", "guest_role", schema="public")
    op.drop_column("guild_invites", "guest_days", schema="public")
