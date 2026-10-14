"""a star for every tool

``favorites``, in every guild schema: one member's star on one tool, any tool,
as ``(user_id, entity_type, entity_id)`` — the shape ``recent_views`` has.
Every project star moves in from ``project_favorites``, which goes. Its CHECK
and policies are rendered from the model and the registry at boot.

The copy reads ``project_favorites`` with its owner's RLS lifted: its policies
admit a request's reader, and a migration has none. ``favorites`` is new and
carries neither policies nor triggers until boot, so writing it needs nothing.
The downgrade reads ``favorites`` and ``projects`` the same way.

Revision ID: 20261013_0509
Revises: 20261011_0508
Create Date: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261013_0509"
down_revision = "20261011_0508"
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


def _apply_upgrade(bind) -> None:
    op.create_table(
        "favorites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "entity_type", "entity_id"),
    )
    if _forced(bind, "project_favorites"):
        op.execute("ALTER TABLE project_favorites NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO favorites (user_id, entity_type, entity_id, created_at) "
        "SELECT user_id, 'project', project_id, created_at FROM project_favorites"
    )
    op.drop_table("project_favorites")


def _apply_downgrade(bind) -> None:
    op.create_table(
        "project_favorites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )
    lifted = [table for table in ("favorites", "projects") if _forced(bind, table)]
    for table in lifted:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    # Only stars on projects that are still there: the old table's key holds
    # its rows to a project.
    op.execute(
        "INSERT INTO project_favorites (user_id, project_id, created_at) "
        "SELECT f.user_id, f.entity_id, f.created_at FROM favorites f "
        "JOIN projects p ON p.id = f.entity_id WHERE f.entity_type = 'project'"
    )
    op.drop_table("favorites")
    if "projects" in lifted:
        op.execute("ALTER TABLE projects FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(bind))


def downgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, lambda: _apply_downgrade(bind))
