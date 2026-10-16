"""installs say whether they follow new initiatives

``plugin_installs`` gains ``follows_new_initiatives``, kept in step with the
install's own row like ``enabled``. Only a mandatory plug-in follows new
initiatives, so an install of a mandatory listing that does not follow is one
the boot backfill has yet to settle: the backfill reads that here and visits
only those communities, and those missing an install.

Nothing is backfilled. Every row starts ``false``, so the first boot visits
each community holding a mandatory install once, as every boot did before,
and records the flag as it settles them.

Revision ID: 20261016_0513
Revises: 20261016_0512
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_0513"
down_revision = "20261016_0512"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plugin_installs",
        sa.Column(
            "follows_new_initiatives",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("plugin_installs", "follows_new_initiatives")
