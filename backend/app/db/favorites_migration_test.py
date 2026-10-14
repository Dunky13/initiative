"""Migration 20261013_0509 moves every project star from ``project_favorites``
into ``favorites``, where any tool can be starred, and back. Loaded by path and
run on a guild the test builds, the way ``tool_layouts_migration_test`` runs
its revisions: down to the old shape, rows written as an older release wrote
them, up, and down again."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_queue,
    create_user,
)

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str):
    path = _VERSIONS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_project_stars_move_in_and_come_back(session) -> None:
    """A star on a live, an archived and a trashed project all move across with
    their times; the downgrade puts back the project stars, and only those."""
    user = await create_user(session)
    other = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    live = await create_project(session, initiative, user, name="Live")
    archived = await create_project(session, initiative, user, name="Archived")
    trashed = await create_project(session, initiative, user, name="Trashed")
    queue = await create_queue(session, initiative, user)
    migration = _load("20261013_0509_a_star_for_every_tool")

    def run(step):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                step(bind)

        return apply

    async def sql(statement: str, **params):
        return await (await session.connection()).execute(text(statement), params)

    await sql(
        f"UPDATE {schema}.projects SET archived_at = now() WHERE id = :p", p=archived.id
    )
    await sql(
        f"UPDATE {schema}.projects SET deleted_at = now() WHERE id = :p", p=trashed.id
    )

    # Back to the shape an older release had, with its stars as it wrote them.
    await session.run_sync(run(migration._apply_downgrade))
    for person, project, at in (
        (user.id, live.id, datetime(2026, 1, 1, tzinfo=timezone.utc)),
        (user.id, archived.id, datetime(2026, 2, 1, tzinfo=timezone.utc)),
        (other.id, trashed.id, datetime(2026, 3, 1, tzinfo=timezone.utc)),
    ):
        await sql(
            f"INSERT INTO {schema}.project_favorites (user_id, project_id, created_at)"
            " VALUES (:u, :p, :at)",
            u=person,
            p=project,
            at=at,
        )

    await session.run_sync(run(migration._apply_upgrade))
    rows = (
        await sql(
            f"SELECT user_id, entity_type, entity_id, created_at FROM {schema}.favorites"
            " ORDER BY created_at"
        )
    ).all()
    assert [(r.user_id, r.entity_type, r.entity_id) for r in rows] == [
        (user.id, "project", live.id),
        (user.id, "project", archived.id),
        (other.id, "project", trashed.id),
    ]
    assert rows[0].created_at.month == 1
    gone = (
        await sql("SELECT to_regclass(:t)", t=f"{schema}.project_favorites")
    ).scalar()
    assert gone is None

    # A star on another tool has no place in the old table.
    await sql(
        f"INSERT INTO {schema}.favorites (user_id, entity_type, entity_id, created_at)"
        " VALUES (:u, 'queue', :q, now())",
        u=user.id,
        q=queue.id,
    )
    await session.run_sync(run(migration._apply_downgrade))
    back = (
        await sql(
            f"SELECT user_id, project_id FROM {schema}.project_favorites ORDER BY created_at"
        )
    ).all()
    assert [(r.user_id, r.project_id) for r in back] == [
        (user.id, live.id),
        (user.id, archived.id),
        (other.id, trashed.id),
    ]

    # And up again, to leave the schema as the head has it.
    await session.run_sync(run(migration._apply_upgrade))
