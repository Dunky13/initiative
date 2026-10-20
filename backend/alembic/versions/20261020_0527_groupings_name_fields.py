"""groupings name fields

A project list's groupings name the field of a task they group by, as the
field registry names it, rather than one of five ids of their own: ``date``
is ``date_group``, ``tags`` is ``tag_ids``, ``status`` is ``task_status_id``
and ``assignees`` is ``assignee_ids``; ``priority`` and ``property:<id>`` are
already the field's name. The date window's groups are keyed by its bucket
(``0`` … ``4``) rather than by the key the browser gave each.

So in every guild schema each list layout's ``groupings`` and ``group_by``
say so, and in each person's view of a project (``view:*:project:*`` in
``user_view_preferences``) the table columns a grouping is drawn by, which
the view keeps its grouping, sort and column choices by, are named for the
field: ``tags group`` (and the older ``tag group``) is ``tag_ids group``.

A view that keeps an empty grouping no longer keeps one, so the list starts
grouped as its layout says. Nearly all of those were the table's own state on
a device, which 0.76 copied into the view as though its reader had picked
"not grouped".

The downgrade names them as they were. A grouping by a field the five ids
had no name for, and a date's bucket, are left out.

Revision ID: 20261020_0527
Revises: 20261019_0526
Create Date: 2026-10-20
"""

import json
from typing import Any, Callable, Optional

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261020_0527"
down_revision = "20261019_0526"
branch_labels = None
depends_on = None

LAYOUTS = "tool_layouts"
PREFERENCES = "public.user_view_preferences"
VIEW_SCOPES = "view:%:project:%"

#: A grouping's id at the last revision, and the field it names now.
FIELDS = {
    "date": "date_group",
    "tags": "tag_ids",
    "status": "task_status_id",
    "priority": "priority",
    "assignees": "assignee_ids",
}
#: The date window's groups, by the browser's key and by the bucket's.
DATE_KEYS = {
    "0_overdue": "0",
    "1_today": "1",
    "2_this_week": "2",
    "3_this_month": "3",
    "4_later": "4",
}
PROPERTY = "property:"
#: A grouping's table column, named for the grouping.
SUFFIX = " group"


def _field(old: Any, forward: bool) -> Optional[str]:
    """A grouping's field in the other naming, or ``None`` where it has none."""
    if not isinstance(old, str):
        return None
    if old.startswith(PROPERTY):
        return old
    names = FIELDS if forward else {new: old for old, new in FIELDS.items()}
    return names.get(old)


def _layout(definition: dict, forward: bool) -> dict:
    keys = DATE_KEYS if forward else {new: old for old, new in DATE_KEYS.items()}
    date = "date" if forward else "date_group"
    out = dict(definition)
    if isinstance(definition.get("groupings"), list):
        groupings = []
        for grouping in definition["groupings"]:
            field = _field(grouping.get("field"), forward)
            if field is None or (not forward and grouping.get("bucket")):
                continue
            moved = {**grouping, "field": field}
            if grouping.get("field") == date:
                moved["hidden"] = [
                    keys.get(key, key) for key in grouping.get("hidden", [])
                ]
            groupings.append(moved)
        out["groupings"] = groupings
    if "group_by" in definition:
        field = _field(definition["group_by"], forward)
        offered = {grouping["field"] for grouping in out.get("groupings") or ()}
        if field is None or ("groupings" in out and field not in offered):
            out.pop("group_by")
        else:
            out["group_by"] = field
    return out


def _column(column: Any, forward: bool) -> Any:
    """A table column the view keeps, named for the grouping it draws."""
    if not isinstance(column, str) or not column.endswith(SUFFIX):
        return column
    grouping = column.removesuffix(SUFFIX)
    if forward and grouping == "tag":
        grouping = "tags"
    field = _field(grouping, forward)
    return f"{field}{SUFFIX}" if field is not None else column


def _part(part: Any, forward: bool) -> Any:
    if not isinstance(part, dict):
        return part
    out = dict(part)
    if forward and part.get("grouping") == []:
        del out["grouping"]
    elif isinstance(part.get("grouping"), list):
        out["grouping"] = [_column(column, forward) for column in part["grouping"]]
    if isinstance(part.get("sorting"), list):
        out["sorting"] = [
            {**entry, "id": _column(entry.get("id"), forward)}
            if isinstance(entry, dict)
            else entry
            for entry in part["sorting"]
        ]
    if isinstance(part.get("columns"), dict):
        out["columns"] = {
            _column(column, forward): shown for column, shown in part["columns"].items()
        }
    return out


def _view(value: Any, forward: bool) -> Any:
    if not isinstance(value, dict) or not isinstance(value.get("parts"), dict):
        return value
    return {
        **value,
        "parts": {kind: _part(part, forward) for kind, part in value["parts"].items()},
    }


def _forced(table: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        )
        .scalar()
    )


def _unforced(table: str, write: Callable[[], None]) -> None:
    """Run ``write`` with the owner's row security lifted on ``table`` and its
    user triggers held, both restored after."""
    forced = _forced(table)
    if forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        write()
    finally:
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
        if forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _rewrite_layouts(forward: bool) -> None:
    bind = op.get_bind()

    def write() -> None:
        rows = bind.execute(
            sa.text(
                f"SELECT id, definition FROM {LAYOUTS} "
                "WHERE definition ? 'groupings' OR definition ? 'group_by'"
            )
        ).all()
        for row_id, definition in rows:
            moved = _layout(definition, forward)
            if moved != definition:
                bind.execute(
                    sa.text(
                        f"UPDATE {LAYOUTS} SET definition = CAST(:d AS jsonb) "
                        "WHERE id = :id"
                    ),
                    {"d": json.dumps(moved), "id": row_id},
                )

    _unforced(LAYOUTS, write)


def _rewrite_views(forward: bool) -> None:
    bind = op.get_bind()

    def write() -> None:
        rows = bind.execute(
            sa.text(
                f"SELECT user_id, scope_key, value FROM {PREFERENCES} "
                "WHERE scope_key LIKE :scopes"
            ),
            {"scopes": VIEW_SCOPES},
        ).all()
        for user_id, scope_key, value in rows:
            moved = _view(value, forward)
            if moved != value:
                bind.execute(
                    sa.text(
                        f"UPDATE {PREFERENCES} SET value = CAST(:v AS json) "
                        "WHERE user_id = :u AND scope_key = :s"
                    ),
                    {"v": json.dumps(moved), "u": user_id, "s": scope_key},
                )

    _unforced(PREFERENCES, write)


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), lambda: _rewrite_layouts(True))
    _rewrite_views(True)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), lambda: _rewrite_layouts(False))
    _rewrite_views(False)
