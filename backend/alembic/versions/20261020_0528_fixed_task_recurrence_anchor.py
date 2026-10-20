"""A fixed task series retains its original recurrence phase.

Backfill from each current task's effective carried due/start and consumed
count, preserving its existing continuation. Even a surviving original task
does not reveal later intentional rule or due-date edits, so inferring phase
from that row would undo legitimate changes. Historical phase already lost
before this migration cannot be reconstructed. Legacy counters included extra
dates, so their consumed COUNT is retained conservatively rather than guessed.

Revision ID: 20261020_0528
Revises: 20261019_0526
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261020_0528"
down_revision = "20261019_0526"
branch_labels = None
depends_on = None


def _add() -> None:
    op.add_column("tasks", sa.Column("recurrence_anchor", sa.DateTime(timezone=True)))
    op.add_column(
        "tasks",
        sa.Column(
            "recurrence_anchor_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    # FORCE binds the provisioning owner too. Hold it and user triggers only
    # for this transactional backfill; the savepoint keeps restoration SQL
    # executable after an error while preserving the original failure.
    op.execute("ALTER TABLE tasks NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tasks DISABLE TRIGGER USER")
    try:
        with op.get_bind().begin_nested():
            op.execute(
                """
                UPDATE tasks AS task
                SET recurrence_anchor = COALESCE(
                    (task.recurrence_carry ->> 'due_date')::timestamptz,
                    task.due_date, task.start_date
                ),
                recurrence_anchor_count = task.recurrence_occurrence_count
                WHERE task.recurrence IS NOT NULL AND task.recurrence_strategy = 'fixed'
                """
            )
    finally:
        op.execute("ALTER TABLE tasks ENABLE TRIGGER USER")
        op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")


def _drop() -> None:
    op.drop_column("tasks", "recurrence_anchor_count")
    op.drop_column("tasks", "recurrence_anchor")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
