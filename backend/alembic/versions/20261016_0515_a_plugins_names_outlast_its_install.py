"""a plug-in's names outlast its install

Four changes, for a plug-in's place in a community and how it leaves one.

``identity_refs`` names a ``plugin`` sector by the plug-in rather than by the
install: ``sector_plugin`` holds the registration's ``public_id`` beside
``sector_guild_id``, and ``sector_id`` is left to the ``webhook`` sector. The
live-reference index takes the new column, an index serves dropping one
plug-in's references in a guild, and a CHECK keeps the two shapes apart. The
``plugin`` rows already stored named installs; nothing is live, so they are
deleted rather than carried, and every plug-in is given fresh references the
next time it is told about somebody. The table is FORCEd, so the delete runs
with FORCE lifted and restored around it.

``plugin_installs`` gains ``community_status_sent``, the status each install's
plug-in was last told, set once a ``community_status`` hook is answered. An
existing install starts with none, so it is told the current status once.

``plugin_community_hooks`` is new: the community hooks waiting to reach a
plug-in, retried until it answers, by the ``plugin_hooks`` sweep timer. A
routed write appends hooks for its own community (an install, an uninstall) in
its own transaction, so the guild floor holds INSERT and one policy admits the
routed community's rows; it reads nothing back. The system engine owns the
rest. The login role and the platform floor, which the schema default grants
full DML on a new table, are revoked; the seat and install floors take no
default privileges and are granted nothing. Row security is enabled and
forced. It is new and has nothing to carry, so it is created and then locked.

``guilds`` gains ``purge_started_at``: set when a purge has asked the
community's plug-ins to erase what they hold, and the row is deleted once each
has answered or been given up on. NULL for every community today, since no
purge has started under this rule.

Revision ID: 20261016_0515
Revises: 20261016_0514
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20261016_0515"
down_revision = "20261016_0514"
branch_labels = None
depends_on = None

HOOKS = "plugin_community_hooks"

_LIVE_BEFORE = "(entity_type, entity_id, purpose, sector_guild_id, sector_id)"
_LIVE_AFTER = (
    "(entity_type, entity_id, purpose, sector_guild_id, sector_id, sector_plugin)"
)
_PLUGIN_SECTOR_CHECK = (
    "(purpose = 'plugin') = (sector_plugin IS NOT NULL)"
    " AND (purpose <> 'plugin' OR sector_id IS NULL)"
)


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _live_index(columns: str) -> str:
    return (
        "CREATE UNIQUE INDEX ix_identity_refs_live ON public.identity_refs "
        f"{columns} NULLS NOT DISTINCT WHERE retired_at IS NULL"
    )


def _drop_plugin_refs() -> None:
    """Delete the ``plugin`` rows, with FORCE lifted for the write."""
    op.execute("ALTER TABLE public.identity_refs NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM public.identity_refs WHERE purpose = 'plugin'")
    finally:
        op.execute("ALTER TABLE public.identity_refs FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.add_column(
        "identity_refs",
        sa.Column("sector_plugin", sa.String(length=120), nullable=True),
    )
    _drop_plugin_refs()
    op.execute("DROP INDEX IF EXISTS public.ix_identity_refs_live")
    op.execute(_live_index(_LIVE_AFTER))
    op.create_index(
        "ix_identity_refs_sector_plugin",
        "identity_refs",
        ["sector_guild_id", "sector_plugin"],
    )
    op.create_check_constraint(
        "identity_refs_plugin_sector", "identity_refs", _PLUGIN_SECTOR_CHECK
    )

    op.add_column(
        "plugin_installs",
        sa.Column("community_status_sent", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "guilds",
        sa.Column("purge_started_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        HOOKS,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "guild_id",
            sa.Integer(),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_id", sa.String(length=120), nullable=False),
        sa.Column("install_id", sa.Integer(), nullable=True),
        sa.Column("hook", sa.String(length=32), nullable=False),
        sa.Column(
            "body",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_plugin_community_hooks_pending",
        HOOKS,
        ["guild_id", "public_id", "id"],
        postgresql_where=sa.text("done_at IS NULL"),
    )
    op.create_index("ix_plugin_community_hooks_done_at", HOOKS, ["done_at"])
    for statement in (
        f"ALTER TABLE public.{HOOKS} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{HOOKS} FORCE ROW LEVEL SECURITY",
        f'REVOKE ALL ON TABLE public.{HOOKS} FROM app_user, app_guild_base, "{_platform_base()}"',
        f"GRANT INSERT ON TABLE public.{HOOKS} TO app_guild_base",
        f"GRANT USAGE, SELECT ON SEQUENCE public.{HOOKS}_id_seq TO app_guild_base",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{HOOKS} TO app_admin",
        f"GRANT USAGE, SELECT ON SEQUENCE public.{HOOKS}_id_seq TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.{HOOKS} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{HOOKS} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_plugin_community_hooks_done_at", table_name=HOOKS)
    op.drop_index("ix_plugin_community_hooks_pending", table_name=HOOKS)
    op.drop_table(HOOKS)

    op.drop_column("guilds", "purge_started_at")
    op.drop_column("plugin_installs", "community_status_sent")

    # The plug-in rows name no install, so they cannot go back into the old
    # shape; they are deleted, as on the way up.
    _drop_plugin_refs()
    op.drop_constraint("identity_refs_plugin_sector", "identity_refs", type_="check")
    op.drop_index("ix_identity_refs_sector_plugin", table_name="identity_refs")
    op.execute("DROP INDEX IF EXISTS public.ix_identity_refs_live")
    op.execute(_live_index(_LIVE_BEFORE))
    op.drop_column("identity_refs", "sector_plugin")
