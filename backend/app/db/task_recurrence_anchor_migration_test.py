import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import create_task


async def test_old_tasks_keep_their_existing_continuation_and_consumed_count(
    session, acting_user
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=timezone.utc),
        recurrence_occurrence_count=2,
    )
    later = await create_task(
        session,
        a.project,
        series_id=first.id,
        due_date=datetime(2026, 10, 9, 9, tzinfo=timezone.utc),
        recurrence_carry={"due_date": "2026-10-07T09:00:00+00:00"},
        recurrence_occurrence_count=3,
        recurrence="RRULE:FREQ=WEEKLY\nRDATE:20261007T090000Z",
    )
    without_history = await create_task(
        session,
        a.project,
        series_id=999999,
        due_date=datetime(2026, 10, 8, 9, tzinfo=timezone.utc),
        recurrence="RRULE:FREQ=DAILY;INTERVAL=3;COUNT=4",
        recurrence_occurrence_count=3,
    )
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20261020_0528_fixed_task_recurrence_anchor.py"
    )
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def migrate(sync_session):
        connection = sync_session.connection()
        connection.execute(
            text("SELECT set_config('search_path', :path, true)"),
            {"path": f"guild_{a.guild.id}, public"},
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration._drop()
            migration._add()

    await session.run_sync(migrate)
    rows = (
        await session.exec(
            text("SELECT id, recurrence_anchor, recurrence_anchor_count FROM tasks")
        )
    ).all()
    anchors = {row[0]: (row[1], row[2]) for row in rows}
    assert anchors[later.id] == (datetime(2026, 10, 7, 9, tzinfo=timezone.utc), 3)
    assert anchors[without_history.id] == (
        datetime(2026, 10, 8, 9, tzinfo=timezone.utc),
        3,
    )
    from app.services.tenant.task_series import next_dates

    await session.refresh(
        later, attribute_names=["recurrence_anchor", "recurrence_anchor_count"]
    )
    dates = next_dates(
        later, now=datetime(2026, 10, 10, tzinfo=timezone.utc), user_timezone="UTC"
    )
    assert dates is not None
    assert dates[1] == datetime(2026, 10, 14, 9, tzinfo=timezone.utc)
    await session.refresh(
        without_history,
        attribute_names=["recurrence_anchor", "recurrence_anchor_count"],
    )
    assert (
        next_dates(
            without_history,
            now=datetime(2026, 10, 10, tzinfo=timezone.utc),
            user_timezone="UTC",
        )
        is None
    )
