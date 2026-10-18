"""a plug-in's list keeps a row per element

``plugin_metadata.ref``, in every guild schema: which element of a list
field's value a row holds, ``''`` for a value that is not a list's. It joins
the primary key, which becomes ``(install_id, entity_type, entity_id, key,
ref)``. Every value already kept is not a list's, so every row takes ``''``
and nothing is backfilled.

The downgrade deletes every list's elements, which a key of four columns
cannot tell apart, with the table's row security lifted and its user triggers
held while it does, and drops the column.

Revision ID: 20261018_0523
Revises: 20261018_0522
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261018_0523"
down_revision = "20261018_0522"
branch_labels = None
depends_on = None

TABLE = "plugin_metadata"
KEY = f"{TABLE}_pkey"
COLUMNS = ["install_id", "entity_type", "entity_id", "key"]


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("ref", sa.String(length=255), server_default="", nullable=False),
    )
    op.drop_constraint(KEY, TABLE, type_="primary")
    op.create_primary_key(KEY, TABLE, [*COLUMNS, "ref"])


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} DISABLE TRIGGER USER")
    try:
        op.execute(f"DELETE FROM {TABLE} WHERE ref <> ''")
    finally:
        op.execute(f"ALTER TABLE {TABLE} ENABLE TRIGGER USER")
        op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.drop_constraint(KEY, TABLE, type_="primary")
    op.create_primary_key(KEY, TABLE, COLUMNS)
    op.drop_column(TABLE, "ref")
