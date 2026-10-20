"""entitlement statements are signed

The issuer now signs each entitlement statement, and this deployment keeps it
exactly as sent and hands that to the plug-in. ``plugin_entitlements`` gains
``statement``, the compact JWS, beside the ``version`` and ``values`` read from
its claims.

A row held before has no signed statement to hand on, so every row is deleted:
the issuer sends the current statements again, and the plug-in can pull once
it has.

Revision ID: 20261016_0514
Revises: 20261016_0513
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_0514"
down_revision = "20261016_0513"
branch_labels = None
depends_on = None

TABLE = "plugin_entitlements"


def upgrade() -> None:
    op.execute(f"DELETE FROM {TABLE}")
    op.add_column(TABLE, sa.Column("statement", sa.Text(), nullable=False))


def downgrade() -> None:
    op.drop_column(TABLE, "statement")
