"""every trash has a purge index

In every guild schema, the nine soft-delete tables that had no ``purge_at``
index get the partial one the other nine have, ``(purge_at) WHERE purge_at IS
NOT NULL``, so the trash purge reads only binned rows.

Revision ID: 20261016_0510
Revises: 20261013_0509
Create Date: 2026-10-16
"""

from alembic import op

from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20261016_0510"
down_revision = "20261013_0509"
branch_labels = None
depends_on = None

_TABLES = (
    "calendars",
    "counter_groups",
    "counters",
    "dashboards",
    "galleries",
    "gallery_images",
    "posts",
    "wiki_pages",
    "wikis",
)


def upgrade() -> None:
    apply_to_all_guild_schemas(
        op.get_bind(),
        *(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_purge ON {table} (purge_at) "
            "WHERE purge_at IS NOT NULL"
            for table in _TABLES
        ),
    )


def downgrade() -> None:
    apply_to_all_guild_schemas(
        op.get_bind(),
        *(f"DROP INDEX IF EXISTS ix_{table}_purge" for table in _TABLES),
    )
