"""a change names the tool that governs it

``event_outbox.dac_tool`` and ``dac_id``, in every guild schema: the tool
instance whose sharing governs a change, stamped by the capture trigger the way
a search entry carries its pair. The change log's read policy, rendered at
boot, then asks a person's sharing on it as well as their initiative.

Changes already in the log (at most the retention window) are stamped here: the
resource itself when it is a tool, else the outermost tool among its parents.
The tool tables are listed as of this revision. The table's row security is
lifted while they are written, and restored.

The downgrade drops the two columns, and the policies rendered on them with
them; the next boot renders the read policy the older revision expects.

Revision ID: 20261011_0502
Revises: 20261011_0501
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261011_0502"
down_revision = "20261011_0501"
branch_labels = None
depends_on = None

#: Each tool's table and the tool it is, as of this revision.
TOOL_TABLES = (
    "('projects', 'project'), ('files', 'file'), ('queues', 'queue'), "
    "('counter_groups', 'counter_group'), ('calendars', 'calendar'), "
    "('dashboards', 'dashboard'), ('posts', 'post'), ('galleries', 'gallery'), "
    "('wikis', 'wiki')"
)


def _add() -> None:
    op.add_column("event_outbox", sa.Column("dac_tool", sa.Text(), nullable=True))
    op.add_column("event_outbox", sa.Column("dac_id", sa.Integer(), nullable=True))
    op.execute("ALTER TABLE event_outbox NO FORCE ROW LEVEL SECURITY")
    try:
        _stamp()
    finally:
        op.execute("ALTER TABLE event_outbox FORCE ROW LEVEL SECURITY")


def _stamp() -> None:
    op.execute(
        f"""
        UPDATE event_outbox o SET dac_tool = g.tool, dac_id = g.rid
          FROM (
                SELECT DISTINCT ON (e.id) e.id, m.tool, x.rid
                  FROM event_outbox e
                  CROSS JOIN LATERAL (
                        SELECT e.resource_type AS type, e.resource_id AS rid,
                               0::bigint AS ord
                        UNION ALL
                        SELECT p ->> 'type', (p ->> 'id')::integer, q.ord
                          FROM jsonb_array_elements(e.parents)
                               WITH ORDINALITY AS q(p, ord)
                  ) x
                  JOIN (VALUES {TOOL_TABLES}) AS m(tbl, tool) ON m.tbl = x.type
                 ORDER BY e.id, x.ord DESC
               ) g
         WHERE g.id = o.id
        """
    )


def _drop() -> None:
    # The policies rendered on the columns go with them; the next boot renders
    # what the older revision expects.
    op.execute(
        "ALTER TABLE event_outbox DROP COLUMN IF EXISTS dac_id CASCADE, "
        "DROP COLUMN IF EXISTS dac_tool CASCADE"
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
