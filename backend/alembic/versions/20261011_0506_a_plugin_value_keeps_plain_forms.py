"""a plug-in's value keeps the plain forms it is compared by

``plugin_metadata.text_form`` and ``number_form``, in every guild schema: the
words a reader sees of a value, and the number it compares as, written with
the value, so a task list filters by a plug-in field without reading JSON per
row.

Values already kept are given their forms here, worked out as the service
works them out as of this revision. The table's row security is lifted while
they are written, and restored.

The downgrade drops the two columns.

Revision ID: 20261011_0506
Revises: 20261011_0505
Create Date: 2026-10-11
"""

import math
from datetime import date, datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261011_0506"
down_revision = "20261011_0505"
branch_labels = None
depends_on = None


def _epoch(text: str) -> Optional[float]:
    try:
        if len(text) == 10:
            day = date.fromisoformat(text)
            moment = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        else:
            moment = datetime.fromisoformat(text)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return moment.timestamp()


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _forms(value: Any) -> tuple[Optional[str], Optional[float]]:
    if isinstance(value, bool):
        return None, 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return None, _number(value)
    if isinstance(value, str):
        return (value or None), _epoch(value)
    if isinstance(value, dict):
        words = next(
            (
                value[name]
                for name in ("text", "url")
                if isinstance(value.get(name), str) and value[name]
            ),
            None,
        )
        part, whole = _number(value.get("value")), _number(value.get("max"))
        return words, part / whole if part is not None and whole else None
    return None, None


def _fill() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT install_id, entity_type, entity_id, key, value FROM plugin_metadata"
        )
    ).all()
    for install_id, entity_type, entity_id, key, value in rows:
        text_form, number_form = _forms(value)
        if text_form is None and number_form is None:
            continue
        bind.execute(
            sa.text(
                "UPDATE plugin_metadata SET text_form = :text, number_form = :number "
                "WHERE install_id = :install AND entity_type = :type "
                "AND entity_id = :entity AND key = :key"
            ),
            {
                "text": text_form,
                "number": number_form,
                "install": install_id,
                "type": entity_type,
                "entity": entity_id,
                "key": key,
            },
        )


def _add() -> None:
    op.add_column("plugin_metadata", sa.Column("text_form", sa.Text(), nullable=True))
    op.add_column(
        "plugin_metadata", sa.Column("number_form", sa.Float(), nullable=True)
    )
    op.execute("ALTER TABLE plugin_metadata NO FORCE ROW LEVEL SECURITY")
    try:
        _fill()
    finally:
        op.execute("ALTER TABLE plugin_metadata FORCE ROW LEVEL SECURITY")


def _drop() -> None:
    op.execute(
        "ALTER TABLE plugin_metadata DROP COLUMN IF EXISTS number_form, "
        "DROP COLUMN IF EXISTS text_form"
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
