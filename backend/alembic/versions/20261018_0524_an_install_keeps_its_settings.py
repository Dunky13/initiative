"""an install keeps its settings

``guild_plugins.settings`` and ``guild_plugins.setting_aliases``, in every
guild schema: the value of each setting the install's pinned definition
declares, by key, and each unique setting's earlier values, newest first. Both
start empty, so nothing is backfilled.

Revision ID: 20261018_0524
Revises: 20261018_0523
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261018_0524"
down_revision = "20261018_0523"
branch_labels = None
depends_on = None

TABLE = "guild_plugins"
COLUMNS = ("settings", "setting_aliases")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for column in COLUMNS:
        op.add_column(
            TABLE,
            sa.Column(
                column,
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="{}",
                nullable=False,
            ),
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column(TABLE, column)
