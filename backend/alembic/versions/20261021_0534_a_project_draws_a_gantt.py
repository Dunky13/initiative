"""a project draws a gantt

A project lists its tasks as a table, a board or a Gantt; it no longer has a
calendar of them (the initiative's calendar and My Calendar show its dated
tasks). The Calendar tool keeps its own calendar list.

So in every guild schema a project's calendar layout is its Gantt, keeping
its presets, and a project that opened on its calendar opens on its Gantt.
The kinds a layout may be are rendered at boot from the registry; this
revision restates them only so the rows it rewrites are admitted.

In each person's view of a project (``view:*:project:*`` in
``user_view_preferences``) the calendar they were last in, and the filters
they kept on it, are the Gantt's, and the calendar's month or week is gone. My
Tasks (``view:me:tasks``) is a table only, so its view keeps no layout or
month.

The downgrade turns a project's Gantt back into its calendar. Its groupings,
which a calendar could not hold, are left out.

Revision ID: 20261021_0534
Revises: 20261021_0533
Create Date: 2026-10-21
"""

import json
from typing import Any, Callable

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261021_0534"
down_revision = "20261021_0533"
branch_labels = None
depends_on = None

LAYOUTS = "tool_layouts"
PREFERENCES = "public.user_view_preferences"
PROJECT_VIEWS = "view:%:project:%"
MY_TASKS_VIEW = "view:me:tasks"
CHECK = "ck_tool_layouts_kind"
_OTHER_KINDS = (
    "calendar",
    "task",
    "calendar_event",
    "queue_item",
    "gallery_image",
    "counter",
    "post",
    "default",
)
#: The kinds a layout may be, after and before this revision.
KINDS = {
    True: ("table", "board", "gantt", *_OTHER_KINDS),
    False: ("table", "board", *_OTHER_KINDS),
}
#: What a project's calendar list is now.
RENAMED = {"calendar": "gantt"}
#: What a calendar list could not hold.
_GROUPING_KEYS = ("groupings", "group_by")


def _names(forward: bool) -> dict[str, str]:
    return RENAMED if forward else {new: old for old, new in RENAMED.items()}


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
    names = _names(forward)
    [(old, new)] = names.items()

    def write() -> None:
        op.execute(f"ALTER TABLE {LAYOUTS} DROP CONSTRAINT IF EXISTS {CHECK}")
        if not forward:
            dropped = "".join(f" - '{key}'" for key in _GROUPING_KEYS)
            bind.execute(
                sa.text(
                    f"UPDATE {LAYOUTS} SET definition = definition{dropped} "
                    "WHERE tool = 'project' AND kind = :old"
                ),
                {"old": old},
            )
        bind.execute(
            sa.text(
                f"UPDATE {LAYOUTS} SET kind = :new WHERE tool = 'project' AND kind = :old"
            ),
            {"new": new, "old": old},
        )
        bind.execute(
            sa.text(
                f"UPDATE {LAYOUTS} SET definition = jsonb_set(definition, "
                "'{kind}', to_jsonb(CAST(:new AS text))) "
                "WHERE tool = 'project' AND kind = 'default' "
                "AND definition ->> 'kind' = :old"
            ),
            {"new": new, "old": old},
        )
        kinds = ", ".join(f"'{kind}'" for kind in KINDS[forward])
        op.execute(
            f"ALTER TABLE {LAYOUTS} ADD CONSTRAINT {CHECK} CHECK (kind IN ({kinds}))"
        )

    _unforced(LAYOUTS, write)


def _project_view(value: Any, forward: bool) -> Any:
    if not isinstance(value, dict):
        return value
    names = _names(forward)
    out = {key: kept for key, kept in value.items() if key != "mode"}
    if value.get("layout") in names:
        out["layout"] = names[value["layout"]]
    if isinstance(value.get("parts"), dict):
        out["parts"] = {
            names.get(kind, kind): part for kind, part in value["parts"].items()
        }
    return out


def _my_tasks_view(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {key: kept for key, kept in value.items() if key not in ("layout", "mode")}


def _rewrite_views(forward: bool) -> None:
    bind = op.get_bind()

    def write() -> None:
        rows = bind.execute(
            sa.text(
                f"SELECT user_id, scope_key, value FROM {PREFERENCES} "
                "WHERE scope_key LIKE :projects OR scope_key = :mine"
            ),
            {"projects": PROJECT_VIEWS, "mine": MY_TASKS_VIEW},
        ).all()
        for user_id, scope_key, value in rows:
            if scope_key == MY_TASKS_VIEW:
                # A table was all My Tasks drew before the calendar, too.
                moved = _my_tasks_view(value) if forward else value
            else:
                moved = _project_view(value, forward)
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
