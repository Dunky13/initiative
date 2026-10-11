"""demo copies

The demo deployment's one table, ``demo_sandboxes``: communities built for the
pool, and the visitors' copies once claimed, each with the invite that opened
it and the visitor's account. A visitor is a guest of their copy, so a copy
ends when its guest does, or a day after it was claimed.
Empty on every deployment not started with ``DEMO_MODE``.

app_admin-only: RLS enabled and forced with no policies, and the schema's
default grants revoked from the two base roles. The table is new and empty, so
nothing is backfilled.

Revision ID: 20261011_0507
Revises: 20261011_0506
Create Date: 2026-10-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261011_0507"
down_revision = "20261011_0506"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_sandboxes",
        sa.Column("guild_id", sa.Integer(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False, server_default="pooled"),
        sa.Column("invite_id", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("import_job_id", sa.Integer(), nullable=True),
        sa.Column("visitor_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visitor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["invite_id"], ["guild_invites.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "state IN ('pooled', 'live')", name="ck_demo_sandboxes_state"
        ),
    )
    op.create_index("ix_demo_sandboxes_state", "demo_sandboxes", ["state"])
    op.create_index("ix_demo_sandboxes_invite_id", "demo_sandboxes", ["invite_id"])

    if op.get_bind().dialect.name != "postgresql":
        return

    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for statement in (
        "ALTER TABLE public.demo_sandboxes ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.demo_sandboxes FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        f'REVOKE ALL ON TABLE public.demo_sandboxes FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.demo_sandboxes TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("demo_sandboxes")
