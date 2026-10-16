"""sweeps wait for their timers

``community_timers`` is when a background sweep next has work in a community:
the community, the sweep's name and a time, and nothing else. The write that
makes the work arms it, through triggers in each community's schema, and the
worker visits only the communities whose timers have come due.

``timer_marks``, in every guild schema, is the earliest timer the community
already has waiting per sweep, so a busy community arms once per sweep rather
than once per write.

Every existing community gets one ``reconcile`` timer, spread over the next
hour. Its visit arms whatever the community already has waiting. The rows go
in before row security is turned on: once it is forced, the table's owner is
held to the policies too, and a migration routes into no community.

The request-path floors hold INSERT and nothing else. Its policy admits a row
for the community the request is routed into. The system engine owns the rest.

Revision ID: 20261016_0511
Revises: 20261016_0510
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings
from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20261016_0511"
down_revision = "20261016_0510"
branch_labels = None
depends_on = None


def _appenders() -> tuple[str, ...]:
    """The floors whose writes arm timers."""
    return ("app_guild_base", "plugin_install_base", "guest_base")


def _refused() -> tuple[str, ...]:
    """The floors a new table's schema defaults reach, which hold nothing here.

    Read at apply time, not at import: the platform prefix is a setting, and
    the migrations test swaps it around the chain it runs.
    """
    return ("app_user", f"{settings.PLATFORM_ROLE_PREFIX}platform_base")


def upgrade() -> None:
    op.create_table(
        "community_timers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "community_id",
            sa.Integer(),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_community_timers_due", "community_timers", ["due_at"])

    apply_to_all_guild_schemas(
        op.get_bind(),
        "CREATE TABLE IF NOT EXISTS timer_marks ("
        "kind text NOT NULL PRIMARY KEY, "
        "due_at timestamp with time zone NOT NULL)",
    )

    # Before row security: see the module docstring.
    op.execute(
        "INSERT INTO community_timers (community_id, kind, due_at) "
        "SELECT id, 'reconcile', now() + random() * interval '1 hour' FROM guilds"
    )

    op.execute("ALTER TABLE public.community_timers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.community_timers FORCE ROW LEVEL SECURITY")

    for role in (*_appenders(), *_refused()):
        op.execute(f'REVOKE ALL ON TABLE public.community_timers FROM "{role}"')
    for role in _appenders():
        op.execute(f'GRANT INSERT ON TABLE public.community_timers TO "{role}"')
        op.execute(
            "GRANT USAGE, SELECT ON SEQUENCE public.community_timers_id_seq "
            f'TO "{role}"'
        )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.community_timers "
        "TO app_admin"
    )
    op.execute(
        "GRANT USAGE, SELECT ON SEQUENCE public.community_timers_id_seq TO app_admin"
    )


def downgrade() -> None:
    apply_to_all_guild_schemas(op.get_bind(), "DROP TABLE IF EXISTS timer_marks")
    op.drop_index("ix_community_timers_due", table_name="community_timers")
    op.drop_table("community_timers")
