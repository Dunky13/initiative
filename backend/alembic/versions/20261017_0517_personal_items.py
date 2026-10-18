"""personal items

``personal_items``, in every guild schema: what one member keeps about one
item, one row per ``(user_id, entity_type, entity_id)``. Their last open and
where it came from, a star, a follow, and where they put a project in their own
list. It takes every row of ``recent_views``, ``favorites`` and
``project_orders``, merged on that key, and those three go. Its registry CHECKs
and its policies are rendered from the model and the registries at boot.

The copy reads the three tables with their owner's RLS lifted: their policies
admit a request's reader, and a migration has none. ``personal_items`` is new
and carries neither policies nor triggers until boot, so writing it needs
nothing. The downgrade reads ``personal_items`` and ``projects`` the same way.

Revision ID: 20261017_0517
Revises: 20261017_0516
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261017_0517"
down_revision = "20261017_0516"
branch_labels = None
depends_on = None


def _forced(bind, table: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )


def _lift(bind, tables: tuple[str, ...]) -> list[str]:
    lifted = [table for table in tables if _forced(bind, table)]
    for table in lifted:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    return lifted


def _apply_upgrade(bind) -> None:
    op.create_table(
        "personal_items",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_source", sa.Text(), nullable=True),
        sa.Column("starred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("followed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "entity_type", "entity_id"),
        sa.CheckConstraint(
            "(viewed_at IS NULL) = (view_source IS NULL)",
            name="ck_personal_items_view_source_with_view",
        ),
        sa.CheckConstraint(
            "num_nonnulls(viewed_at, starred_at, followed_at, sort_order) > 0",
            name="ck_personal_items_holds_something",
        ),
    )
    op.create_index(
        "ix_personal_items_entity", "personal_items", ["entity_type", "entity_id"]
    )
    op.create_index(
        "ix_personal_items_user_viewed_at", "personal_items", ["user_id", "viewed_at"]
    )
    _lift(bind, ("recent_views", "favorites", "project_orders"))
    op.execute(
        """
        INSERT INTO personal_items (user_id, entity_type, entity_id, viewed_at,
                                    view_source, starred_at, sort_order)
        SELECT user_id, entity_type, entity_id, max(viewed_at), max(view_source),
               max(starred_at), max(sort_order)
          FROM (
                SELECT user_id, entity_type, entity_id,
                       last_viewed_at AS viewed_at, source AS view_source,
                       NULL::timestamptz AS starred_at,
                       NULL::double precision AS sort_order
                  FROM recent_views
                UNION ALL
                SELECT user_id, entity_type, entity_id, NULL, NULL, created_at, NULL
                  FROM favorites
                UNION ALL
                SELECT user_id, 'project', project_id, NULL, NULL, NULL, sort_order
                  FROM project_orders
               ) kept
         GROUP BY user_id, entity_type, entity_id
        """
    )
    op.drop_table("recent_views")
    op.drop_table("favorites")
    op.drop_table("project_orders")


def _apply_downgrade(bind) -> None:
    op.create_table(
        "recent_views",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="direct"),
        sa.PrimaryKeyConstraint("user_id", "entity_type", "entity_id"),
    )
    op.create_index(
        "ix_recent_views_entity", "recent_views", ["entity_type", "entity_id"]
    )
    op.create_index(
        "ix_recent_views_user_last_viewed_at",
        "recent_views",
        ["user_id", "last_viewed_at"],
    )
    op.create_table(
        "favorites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "entity_type", "entity_id"),
    )
    op.create_table(
        "project_orders",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Float(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )
    lifted = _lift(bind, ("personal_items", "projects"))
    op.execute(
        "INSERT INTO recent_views (user_id, entity_type, entity_id, last_viewed_at,"
        " source) SELECT user_id, entity_type, entity_id, viewed_at, view_source"
        " FROM personal_items WHERE viewed_at IS NOT NULL"
    )
    op.execute(
        "INSERT INTO favorites (user_id, entity_type, entity_id, created_at)"
        " SELECT user_id, entity_type, entity_id, starred_at FROM personal_items"
        " WHERE starred_at IS NOT NULL"
    )
    # Only orders of projects that are still there: the old table's key holds
    # its rows to a project. Follows have nowhere to go.
    op.execute(
        "INSERT INTO project_orders (user_id, project_id, sort_order)"
        " SELECT i.user_id, i.entity_id, i.sort_order FROM personal_items i"
        " JOIN projects p ON p.id = i.entity_id"
        " WHERE i.entity_type = 'project' AND i.sort_order IS NOT NULL"
    )
    op.drop_table("personal_items")
    if "projects" in lifted:
        op.execute("ALTER TABLE projects FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(bind))


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_downgrade(bind))
