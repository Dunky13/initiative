"""a provided plug-in follows no initiative

A mandatory plug-in is placed in every initiative there is when it is
installed, and from then on the community's admin decides where it appears,
as for any other install. ``guild_plugins.follows_new_initiatives`` and the
``initiative_roles`` trigger that placed such an install in each new
initiative are dropped, with the shared function the trigger called.

Revision ID: 20261016_0513
Revises: 20261016_0512
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20261016_0513"
down_revision = "20261016_0512"
branch_labels = None
depends_on = None

_TRIGGER = "tr_initiative_roles_place_following_plugins"

_PLACE_FUNCTION = """
CREATE OR REPLACE FUNCTION public.fn_place_following_plugins() RETURNS trigger
    LANGUAGE plpgsql AS $place$
BEGIN
    IF NEW.is_builtin AND NEW.name = 'moderator' THEN
        EXECUTE format(
            'INSERT INTO %I.plugin_placements '
            '(install_id, initiative_id, role_ids, created_at, updated_at) '
            'SELECT a.id, $1, ARRAY[$2]::integer[], now(), now() '
            'FROM %I.guild_plugins a WHERE a.follows_new_initiatives '
            'ON CONFLICT DO NOTHING',
            TG_TABLE_SCHEMA, TG_TABLE_SCHEMA
        ) USING NEW.initiative_id, NEW.id;
    END IF;
    RETURN NULL;
END;
$place$;
"""


def upgrade() -> None:
    apply_to_all_guild_schemas(
        op.get_bind(),
        f"DROP TRIGGER IF EXISTS {_TRIGGER} ON initiative_roles",
        "ALTER TABLE guild_plugins DROP COLUMN IF EXISTS follows_new_initiatives",
    )
    op.execute("DROP FUNCTION IF EXISTS public.fn_place_following_plugins()")


def downgrade() -> None:
    op.execute(_PLACE_FUNCTION)
    apply_to_all_guild_schemas(
        op.get_bind(),
        "ALTER TABLE guild_plugins ADD COLUMN IF NOT EXISTS follows_new_initiatives"
        " boolean NOT NULL DEFAULT false",
        f"CREATE OR REPLACE TRIGGER {_TRIGGER} AFTER INSERT ON initiative_roles"
        " FOR EACH ROW EXECUTE FUNCTION public.fn_place_following_plugins()",
    )
