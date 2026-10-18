"""subscriptions are worked out

Whoever made something or is named on it is subscribed to it without a row
saying so, so ``personal_items`` gains ``unsubscribed_at``: the mark that
outlives "never subscribed". And subscribers are told from the change log as
themselves, one batch at a time, so the per-transaction ledger
(``subscription_notices``) and the index its sweep read give way to one row of
progress per community (``subscription_progress``), started where each
community's log stands. Its policies are rendered from the registry at boot.

Conditional where 0519 may or may not have run its shape, so every database
lands on the same one.

Revision ID: 20261018_0521
Revises: 20261018_0520
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

#: Each community's progress starts where its log stands, so nothing already
#: in it is told; the template keeps none, as a new community's starts at its
#: own first change.
_STARTS_NOW = sa.text(
    "INSERT INTO subscription_progress (id, told_xmin)"
    " SELECT 1, pg_snapshot_xmin(pg_current_snapshot())::text::bigint"
    " WHERE current_schema() <> 'guild_template'"
)

revision = "20261018_0521"
down_revision = "20261018_0520"
branch_labels = None
depends_on = None


def _apply_upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS subscription_notices")
    op.execute("DROP INDEX IF EXISTS ix_personal_items_subscribed_at")
    op.add_column(
        "personal_items",
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(
        "ck_personal_items_holds_something", "personal_items", type_="check"
    )
    op.create_check_constraint(
        "ck_personal_items_holds_something",
        "personal_items",
        "num_nonnulls(viewed_at, bookmarked_at, subscribed_at,"
        " unsubscribed_at, sort_order) > 0",
    )
    op.create_check_constraint(
        "ck_personal_items_subscribed_or_not",
        "personal_items",
        "subscribed_at IS NULL OR unsubscribed_at IS NULL",
    )
    op.create_table(
        "subscription_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("told_xmin", sa.BigInteger(), nullable=False),
        sa.Column(
            "told_above",
            postgresql.ARRAY(sa.BigInteger()),
            server_default="{}",
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_subscription_progress_one"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(_STARTS_NOW)


def _apply_downgrade() -> None:
    op.drop_table("subscription_progress")
    op.drop_constraint(
        "ck_personal_items_subscribed_or_not", "personal_items", type_="check"
    )
    # A row that held only an unsubscription goes with the column. The table
    # is FORCE-RLS and the migration role owns it, so the force is lifted for
    # the write.
    op.execute("ALTER TABLE personal_items NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "DELETE FROM personal_items WHERE num_nonnulls(viewed_at,"
            " bookmarked_at, subscribed_at, sort_order) = 0"
        )
    finally:
        op.execute("ALTER TABLE personal_items FORCE ROW LEVEL SECURITY")
    op.drop_constraint(
        "ck_personal_items_holds_something", "personal_items", type_="check"
    )
    op.create_check_constraint(
        "ck_personal_items_holds_something",
        "personal_items",
        "num_nonnulls(viewed_at, bookmarked_at, subscribed_at, sort_order) > 0",
    )
    op.drop_column("personal_items", "unsubscribed_at")
    op.create_index(
        "ix_personal_items_subscribed_at",
        "personal_items",
        ["subscribed_at"],
        postgresql_where=sa.text("subscribed_at IS NOT NULL"),
    )
    op.create_table(
        "subscription_notices",
        sa.Column("txn_id", sa.BigInteger(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("txn_id"),
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
