"""Migration 20261021_0534 turns a project's calendar into its Gantt, in the
layouts every guild stores and in each person's view of a project, and leaves
My Tasks a table.

Loaded by path and run on a guild the test builds, as
``groupings_migration_test`` runs its revision: rows as the last release wrote
them, up, and down again."""

from __future__ import annotations

import json

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.db.tool_layouts_migration_test import _load
from app.testing import create_guild, create_initiative, create_project, create_user

_PRESETS = {"presets": [{"slug": "mine", "filters": {"assignees": ["me"]}}]}
_PROJECT_VIEW = {
    "layout": "calendar",
    "mode": "week",
    "parts": {"calendar": {"filters": {"tag_ids": [3]}}, "table": {"grouping": []}},
}
_MY_TASKS = {"layout": "calendar", "mode": "month", "parts": {"list": {"grouping": []}}}


async def test_a_project_calendar_becomes_its_gantt_and_comes_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    migration = _load("20261021_0534_a_project_draws_a_gantt")
    scope = f"view:{guild.id}:project:{project.id}"

    async def sql(statement: str, **params):
        return await (await session.connection()).execute(text(statement), params)

    def run(forward: bool):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                migration._rewrite_layouts(forward)
                migration._rewrite_views(forward)

        return apply

    # The project's calendar and the list it opens on, and the Calendar tool's
    # own calendar, which stays one.
    for tool, tool_id, kind, definition in (
        ("project", project.id, "calendar", _PRESETS),
        ("project", project.id, "default", {"kind": "calendar"}),
        ("calendar", None, "calendar", _PRESETS),
    ):
        await sql(
            f"INSERT INTO {schema}.tool_layouts (initiative_id, tool, tool_id, kind,"
            " definition, created_at, updated_at) VALUES (:i, :t, :p, :k,"
            " CAST(:d AS jsonb), now(), now())",
            i=initiative.id,
            t=tool,
            p=tool_id,
            k=kind,
            d=json.dumps(definition),
        )
    for key, value in ((scope, _PROJECT_VIEW), ("view:me:tasks", _MY_TASKS)):
        await sql(
            "INSERT INTO public.user_view_preferences (user_id, scope_key, value,"
            " updated_at) VALUES (:u, :s, CAST(:v AS json), now())",
            u=user.id,
            s=key,
            v=json.dumps(value),
        )

    async def stored() -> tuple[list, dict]:
        layouts = (
            await sql(
                f"SELECT tool, kind, definition FROM {schema}.tool_layouts"
                " ORDER BY tool, kind"
            )
        ).all()
        views = (
            await sql(
                "SELECT scope_key, value FROM public.user_view_preferences"
                " WHERE user_id = :u",
                u=user.id,
            )
        ).all()
        return [tuple(row) for row in layouts], dict(views)

    await session.run_sync(run(True))
    assert await stored() == (
        [
            ("calendar", "calendar", _PRESETS),
            ("project", "default", {"kind": "gantt"}),
            ("project", "gantt", _PRESETS),
        ],
        {
            scope: {
                "layout": "gantt",
                "parts": {
                    "gantt": {"filters": {"tag_ids": [3]}},
                    "table": {"grouping": []},
                },
            },
            "view:me:tasks": {"parts": {"list": {"grouping": []}}},
        },
    )

    # A Gantt's groupings are what a calendar cannot hold.
    await sql(
        f"UPDATE {schema}.tool_layouts SET definition = CAST(:d AS jsonb)"
        " WHERE kind = 'gantt'",
        d=json.dumps({**_PRESETS, "groupings": [{"field": "priority"}]}),
    )
    await session.run_sync(run(False))
    layouts, views = await stored()
    assert layouts == [
        ("calendar", "calendar", _PRESETS),
        ("project", "calendar", _PRESETS),
        ("project", "default", {"kind": "calendar"}),
    ]
    assert views[scope] == {
        key: kept for key, kept in _PROJECT_VIEW.items() if key != "mode"
    }
