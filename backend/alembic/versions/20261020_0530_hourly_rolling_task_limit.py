"""An optional daily maximum for rolling hourly tasks.

Revision ID: 20261020_0530
Revises: 20261020_0529
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261020_0530"
down_revision = "20261020_0529"
branch_labels = None
depends_on = None


def _add() -> None:
    op.add_column(
        "tasks",
        sa.Column("recurrence_limit", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_tasks_recurrence_limit", "tasks", "recurrence_limit BETWEEN 1 AND 24"
    )


def _drop() -> None:
    op.drop_constraint("ck_tasks_recurrence_limit", "tasks", type_="check")
    op.drop_column("tasks", "recurrence_limit")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
