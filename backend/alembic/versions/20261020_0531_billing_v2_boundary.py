"""billing v2: versioned community state and the change log

- ``guild_administration.billing_version``: which version of billing's state
  a community holds. A write at a version no newer is answered with it and
  changes nothing. The billing role reads and writes it beside the caps.
- ``billing_changes``: the log billing reads by cursor. It's written only by
  ``public.billing_change_row``, a definer function owned by the NOLOGIN role
  ``app_billing_log``, from the triggers below in the transaction that changed the fact,
  and from the system engine for a community's stored bytes. No request role
  holds a privilege on it, so a row means the fact happened. Each row carries
  its transaction's id, ``pg_current_xact_id()``, so the log can be served
  only up to the oldest transaction still running and a late commit is never
  skipped.
- The triggers:
  - ``guilds``: created (with its name), renamed, deleted, restored,
    suspended, unsuspended, purged;
  - ``guild_memberships``: the community's member and guest counts, once per
    community a statement touches;
  - ``plugin_installs``: a plug-in installed or uninstalled;
  - ``plugin_usage``: a meter's running total for the month.
  Each writes nothing unless ``public.billing_managed()``.
- The system engine burns envelope ``jti`` values, so ``app_admin`` may
  insert into ``billing_jti_blocklist``.

Revision ID: 20261020_0531
Revises: 20261020_0530
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20261020_0531"
down_revision = "20261020_0530"
branch_labels = None
depends_on = None

#: The channel a written row is announced on, at commit.
CHANNEL = "billing_changes"
#: The role that owns the writer and the triggers: it may insert into the log
#: and read just what they read, whoever's transaction calls them (the
#: ``app_dm_reader`` pattern, 0223). Not BYPASSRLS: its read policies are
#: registered in ``app.db.public_rls``.
WRITER = "app_billing_log"

_WRITER_GRANTS = (
    "GRANT SELECT (id) ON TABLE public.guilds TO {r}",
    "GRANT SELECT (guild_id, guest_until) ON TABLE public.guild_memberships TO {r}",
    "GRANT SELECT (ref, entity_type, entity_id, purpose, sector_guild_id, sector_id,"
    " sector_plugin, retired_at) ON TABLE public.identity_refs TO {r}",
    "GRANT INSERT ON TABLE public.billing_changes TO {r}",
    "GRANT EXECUTE ON FUNCTION public.billing_managed() TO {r}",
)

_WRITER_POLICIES = (
    ("guilds", "billing_log_read", "true"),
    ("guild_memberships", "billing_log_read", "true"),
    (
        "identity_refs",
        "billing_log_read_refs",
        "purpose = 'billing' AND entity_type = 'guild'",
    ),
)


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


_CHANGE_ROW = f"""
CREATE OR REPLACE FUNCTION public.billing_change_row(
    p_guild integer, p_kind text, p_data jsonb
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
DECLARE v_ref text;
BEGIN
    IF NOT public.billing_managed() THEN
        RETURN;
    END IF;
    -- The community's billing reference, while it has one: a purge removes
    -- the references after the row, and this is the last chance to read it.
    SELECT ref INTO v_ref FROM public.identity_refs
     WHERE entity_type = 'guild' AND entity_id = p_guild AND purpose = 'billing'
       AND sector_guild_id IS NULL AND sector_id IS NULL AND sector_plugin IS NULL
       AND retired_at IS NULL;
    INSERT INTO public.billing_changes (xid, guild_id, kind, community_ref, data)
    VALUES ((pg_current_xact_id()::text)::bigint, p_guild, p_kind, v_ref,
            coalesce(p_data, '{{}}'::jsonb));
    PERFORM pg_notify('{CHANNEL}', '');
END $fn$;
"""

_GUILDS = """
CREATE OR REPLACE FUNCTION public.billing_guild_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM public.billing_change_row(
            NEW.id, 'community.created',
            -- Who made it; the change log serves its first superadmin as the
            -- owner when it has one (they differ when staff made it for
            -- somebody).
            jsonb_build_object('name', NEW.name)
            || CASE WHEN NEW.created_by IS NULL THEN '{}'::jsonb
                    ELSE jsonb_build_object('owner_user_id', NEW.created_by) END);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM public.billing_change_row(OLD.id, 'community.purged', NULL);
    ELSIF TG_ARGV[0] = 'name' THEN
        PERFORM public.billing_change_row(
            NEW.id, 'community.renamed', jsonb_build_object('name', NEW.name));
    ELSE
        IF OLD.status = 'deleted' AND NEW.status <> 'deleted' THEN
            PERFORM public.billing_change_row(NEW.id, 'community.restored', NULL);
        END IF;
        IF OLD.status = 'suspended' AND NEW.status NOT IN ('suspended', 'deleted') THEN
            PERFORM public.billing_change_row(NEW.id, 'community.unsuspended', NULL);
        END IF;
        IF NEW.status = 'deleted' AND OLD.status <> 'deleted' THEN
            PERFORM public.billing_change_row(NEW.id, 'community.deleted', NULL);
        END IF;
        IF NEW.status = 'suspended' AND OLD.status <> 'suspended' THEN
            PERFORM public.billing_change_row(NEW.id, 'community.suspended', NULL);
        END IF;
    END IF;
    RETURN NULL;
END $fn$;
"""

_MEMBERS_OF = """
CREATE OR REPLACE FUNCTION public.billing_members_of(p_guild integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
BEGIN
    -- A community going in this transaction is told as purged instead.
    IF NOT EXISTS (SELECT 1 FROM public.guilds WHERE id = p_guild) THEN
        RETURN;
    END IF;
    PERFORM public.billing_change_row(
        p_guild, 'community.members',
        jsonb_build_object(
            'members', (SELECT count(*) FROM public.guild_memberships
                         WHERE guild_id = p_guild AND guest_until IS NULL),
            'guests', (SELECT count(*) FROM public.guild_memberships
                        WHERE guild_id = p_guild AND guest_until > now())));
END $fn$;
"""

_MEMBERSHIPS = """
CREATE OR REPLACE FUNCTION public.billing_memberships_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
DECLARE g integer;
BEGIN
    IF NOT public.billing_managed() THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'INSERT' THEN
        FOR g IN SELECT DISTINCT guild_id FROM new_rows ORDER BY 1 LOOP
            PERFORM public.billing_members_of(g);
        END LOOP;
    ELSIF TG_OP = 'DELETE' THEN
        FOR g IN SELECT DISTINCT guild_id FROM old_rows ORDER BY 1 LOOP
            PERFORM public.billing_members_of(g);
        END LOOP;
    ELSE
        -- Only a change that moves a count: a guest made a member, or a
        -- guest's time changed. A role change moves neither.
        FOR g IN
            SELECT DISTINCT n.guild_id FROM new_rows n
              JOIN old_rows o ON o.guild_id = n.guild_id AND o.user_id = n.user_id
             WHERE o.guest_until IS DISTINCT FROM n.guest_until
             ORDER BY 1
        LOOP
            PERFORM public.billing_members_of(g);
        END LOOP;
    END IF;
    RETURN NULL;
END $fn$;
"""

_INSTALLS = """
CREATE OR REPLACE FUNCTION public.billing_install_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM public.billing_change_row(
            NEW.guild_id, 'plugin.installed',
            jsonb_build_object('listing_uid', NEW.listing_uid));
    ELSIF EXISTS (SELECT 1 FROM public.guilds WHERE id = OLD.guild_id) THEN
        PERFORM public.billing_change_row(
            OLD.guild_id, 'plugin.uninstalled',
            jsonb_build_object('listing_uid', OLD.listing_uid));
    END IF;
    RETURN NULL;
END $fn$;
"""

_USAGE = """
CREATE OR REPLACE FUNCTION public.billing_usage_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.quantity = NEW.quantity THEN
        RETURN NULL;
    END IF;
    PERFORM public.billing_change_row(
        NEW.guild_id, 'plugin.usage',
        jsonb_build_object('listing_uid', NEW.listing_uid, 'meter', NEW.meter,
                           'period', NEW.period, 'quantity', NEW.quantity));
    RETURN NULL;
END $fn$;
"""

_FUNCTIONS = (
    "billing_change_row(integer, text, jsonb)",
    "billing_guild_changed()",
    "billing_members_of(integer)",
    "billing_memberships_changed()",
    "billing_install_changed()",
    "billing_usage_changed()",
)

_TRIGGERS = (
    (
        "billing_guild_lifecycle",
        "guilds",
        "AFTER INSERT OR DELETE ON public.guilds FOR EACH ROW",
        "billing_guild_changed()",
    ),
    (
        "billing_guild_status",
        "guilds",
        "AFTER UPDATE OF status ON public.guilds FOR EACH ROW"
        " WHEN (OLD.status IS DISTINCT FROM NEW.status)",
        "billing_guild_changed('status')",
    ),
    (
        "billing_guild_name",
        "guilds",
        "AFTER UPDATE OF name ON public.guilds FOR EACH ROW"
        " WHEN (OLD.name IS DISTINCT FROM NEW.name)",
        "billing_guild_changed('name')",
    ),
    (
        "billing_memberships_insert",
        "guild_memberships",
        "AFTER INSERT ON public.guild_memberships"
        " REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT",
        "billing_memberships_changed()",
    ),
    (
        "billing_memberships_delete",
        "guild_memberships",
        "AFTER DELETE ON public.guild_memberships"
        " REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT",
        "billing_memberships_changed()",
    ),
    (
        "billing_memberships_update",
        "guild_memberships",
        "AFTER UPDATE ON public.guild_memberships"
        " REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT",
        "billing_memberships_changed()",
    ),
    (
        "billing_plugin_installs",
        "plugin_installs",
        "AFTER INSERT OR DELETE ON public.plugin_installs FOR EACH ROW",
        "billing_install_changed()",
    ),
    (
        "billing_plugin_usage",
        "plugin_usage",
        "AFTER INSERT OR UPDATE OF quantity ON public.plugin_usage FOR EACH ROW",
        "billing_usage_changed()",
    ),
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.guild_administration "
        "ADD COLUMN billing_version bigint NOT NULL DEFAULT 0"
    )
    op.execute(
        "GRANT SELECT (billing_version), UPDATE (billing_version) "
        f'ON public.guild_administration TO "{_billing_role()}"'
    )

    op.create_table(
        "billing_changes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("xid", sa.BigInteger(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("community_ref", sa.String(128), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="public",
    )
    op.create_index(
        "ix_billing_changes_xid_id", "billing_changes", ["xid", "id"], schema="public"
    )
    op.create_index(
        "ix_billing_changes_occurred_at",
        "billing_changes",
        ["occurred_at"],
        schema="public",
    )
    # The schema default gives the routed floors DML on a new table; this one
    # is the system engine's alone.
    base = f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"'
    op.execute(
        "REVOKE ALL ON TABLE public.billing_changes"
        f" FROM PUBLIC, app_guild_base, {base}, app_user"
    )
    # Served, and pruned, on the system engine. Written only by the definer
    # function below.
    op.execute("GRANT SELECT, DELETE ON TABLE public.billing_changes TO app_admin")
    op.execute("GRANT INSERT ON TABLE public.billing_jti_blocklist TO app_admin")

    writer = f'"{WRITER}"'
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{WRITER}') THEN
                CREATE ROLE {writer} NOLOGIN;
            END IF;
        END $$;
        """
    )
    # Migrations run as ``app_provisioner``, not as a superuser, and handing
    # an object to a role means being able to become it.
    op.execute(f"GRANT {writer} TO CURRENT_USER WITH INHERIT TRUE, SET TRUE")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {writer}")
    for grant in _WRITER_GRANTS:
        op.execute(grant.format(r=writer))
    for table, policy, using in _WRITER_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
        op.execute(
            f"CREATE POLICY {policy} ON public.{table} "
            f"AS PERMISSIVE FOR SELECT TO {writer} USING ({using})"
        )

    for body in (_CHANGE_ROW, _GUILDS, _MEMBERS_OF, _MEMBERSHIPS, _INSTALLS, _USAGE):
        op.execute(body)
    # Ownership can only be handed to a role that may create in the schema.
    # Given for the assignment and taken straight back.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {writer}")
    for signature in _FUNCTIONS:
        op.execute(f"ALTER FUNCTION public.{signature} OWNER TO {writer}")
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {writer}")
    # The one direct caller: the system engine's coalesced storage report.
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.billing_change_row(integer, text, jsonb)"
        " TO app_admin"
    )
    for name, _table, when, function in _TRIGGERS:
        op.execute(f"CREATE TRIGGER {name} {when} EXECUTE FUNCTION public.{function}")


def downgrade() -> None:
    for name, table, _when, _function in _TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name} ON public.{table}")
    for signature in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
    for table, policy, _using in _WRITER_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
    for grant in _WRITER_GRANTS:
        op.execute(
            grant.format(r=f'"{WRITER}"')
            .replace("GRANT ", "REVOKE ", 1)
            .replace(" TO ", " FROM ")
        )
    op.execute("REVOKE INSERT ON TABLE public.billing_jti_blocklist FROM app_admin")
    op.drop_table("billing_changes", schema="public")
    op.execute(
        "REVOKE SELECT (billing_version), UPDATE (billing_version) "
        f'ON public.guild_administration FROM "{_billing_role()}"'
    )
    op.execute("ALTER TABLE public.guild_administration DROP COLUMN billing_version")
