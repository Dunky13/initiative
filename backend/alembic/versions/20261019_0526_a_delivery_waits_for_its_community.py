"""a delivery waits for its community

``plugin_hook_deliveries``, in every guild schema, keeps a vendor delivery
until the community's delivery sweep has mapped or forwarded it: its body
and the vendor's headers, the value it was routed by, when it was received,
how many times its work failed and until when a visit holds it. A row whose
body is gone is done. The rows already there recorded accepted deliveries,
which have no body, so nothing is backfilled.

Revision ID: 20261019_0526
Revises: 20261018_0525
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261019_0526"
down_revision = "20261018_0525"
branch_labels = None
depends_on = None

TABLE = "plugin_hook_deliveries"
COLUMNS = (
    sa.Column(
        "received_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.Column("body", sa.LargeBinary(), nullable=True),
    sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("route", sa.String(length=200), nullable=True),
    sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    sa.Column("taken_until", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for column in COLUMNS:
        op.add_column(TABLE, column)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column(TABLE, column.name)
