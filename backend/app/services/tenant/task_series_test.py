import json
from datetime import datetime, timezone

import pytest

from app.core.messages import TaskMessages
from app.testing import create_task


@pytest.mark.parametrize("operation", ["complete", "skip"])
@pytest.mark.parametrize(
    ("rule", "expected_dates"),
    [
        ("RRULE:FREQ=WEEKLY\nRDATE:20261007T090000Z", [7, 12, 19]),
        ("RRULE:FREQ=WEEKLY;COUNT=3\nRDATE:20261007T090000Z", [7, 12, 19]),
        (
            "RRULE:FREQ=DAILY;INTERVAL=3\nRDATE:20261007T090000Z\n"
            "EXDATE:20261008T090000Z",
            [7, 11, 14],
        ),
    ],
)
async def test_fixed_task_keeps_its_phase_after_an_extra_date(
    client, session, acting_user, operation, rule, expected_dates
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=timezone.utc),
        recurrence=rule,
    )
    task_id = first.id
    for day in expected_dates:
        if operation == "skip":
            response = await client.post(
                a.g(f"/tasks/{task_id}/skip"), headers=a.headers
            )
            assert response.status_code == 200, response.text
            current = response.json()
        else:
            response = await client.patch(
                a.g(f"/tasks/{task_id}"),
                headers=a.headers,
                json={"status_category": "done"},
            )
            assert response.status_code == 200, response.text
            conditions = json.dumps(
                [{"field": "project_id", "op": "eq", "value": a.project.id}]
            )
            response = await client.get(
                a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
            )
            assert response.status_code == 200, response.text
            (current,) = [row for row in response.json()["items"] if row["recurrence"]]
            task_id = current["id"]
        assert datetime.fromisoformat(current["due_date"]) == datetime(
            2026, 10, day, 9, tzinfo=timezone.utc
        )


@pytest.mark.parametrize("operation", ["complete", "skip"])
async def test_zero_date_span_survives_the_next_task(
    client, session, acting_user, operation
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    due = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    first = await create_task(
        session, a.project, start_date=due, due_date=due, recurrence="RRULE:FREQ=DAILY"
    )
    if operation == "skip":
        response = await client.post(a.g(f"/tasks/{first.id}/skip"), headers=a.headers)
        assert response.status_code == 200, response.text
        current = response.json()
    else:
        response = await client.patch(
            a.g(f"/tasks/{first.id}"),
            headers=a.headers,
            json={"status_category": "done"},
        )
        assert response.status_code == 200, response.text
        conditions = json.dumps(
            [{"field": "project_id", "op": "eq", "value": a.project.id}]
        )
        response = await client.get(
            a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        (current,) = [row for row in response.json()["items"] if row["recurrence"]]
    assert current["start_date"] == current["due_date"]
    assert datetime.fromisoformat(current["due_date"]) == datetime(
        2026, 10, 6, 9, tzinfo=timezone.utc
    )


async def test_resubmitting_unchanged_repeat_keeps_phase_and_calendar_projection(
    client, session, acting_user
):
    from app.schemas.tenant.task import TaskListRead
    from app.services.tenant.task_queries import projected_occurrences

    a = await acting_user(guild_role="member", initiative=True, project=True)
    rule = "RRULE:FREQ=WEEKLY;COUNT=3\nRDATE:20261007T090000Z,20261101T090000Z"
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=timezone.utc),
        recurrence=rule,
    )
    response = await client.post(a.g(f"/tasks/{first.id}/skip"), headers=a.headers)
    assert response.status_code == 200, response.text
    response = await client.patch(
        a.g(f"/tasks/{first.id}"),
        headers=a.headers,
        json={"title": "Renamed", "recurrence": rule, "recurrence_strategy": "fixed"},
    )
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["recurrence_anchor"]) == datetime(
        2026, 10, 5, 9, tzinfo=timezone.utc
    )
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )
    assert response.status_code == 200, response.text
    current = TaskListRead.model_validate(response.json()["items"][0])
    _, projected = projected_occurrences(
        [current],
        datetime(2026, 10, 8, tzinfo=timezone.utc),
        datetime(2026, 11, 2, tzinfo=timezone.utc),
    )
    assert [row.due_date for row in projected] == [
        datetime(2026, 10, 12, 9, tzinfo=timezone.utc),
        datetime(2026, 10, 19, 9, tzinfo=timezone.utc),
        datetime(2026, 11, 1, 9, tzinfo=timezone.utc),
    ]
    response = await client.post(a.g(f"/tasks/{first.id}/skip"), headers=a.headers)
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["due_date"]) == datetime(
        2026, 10, 12, 9, tzinfo=timezone.utc
    )


async def test_retained_anchor_does_not_restart_a_consumed_count(
    client, session, acting_user
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    due = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    task = await create_task(
        session,
        a.project,
        due_date=due,
        recurrence="RRULE:FREQ=DAILY;COUNT=3",
        recurrence_occurrence_count=2,
        recurrence_anchor=due,
        recurrence_anchor_count=2,
    )
    response = await client.post(a.g(f"/tasks/{task.id}/skip"), headers=a.headers)
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == TaskMessages.NO_LATER_OCCURRENCE


@pytest.mark.parametrize("operation", ["complete", "skip"])
@pytest.mark.parametrize(
    "edit", ["resubmitted_rule_and_date", "repeat_after_this_only_date"]
)
async def test_task_edits_reanchor_the_effective_series_date(
    client, session, acting_user, operation, edit
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=timezone.utc),
        recurrence="RRULE:FREQ=WEEKLY"
        if edit == "resubmitted_rule_and_date"
        else "RRULE:FREQ=DAILY",
    )
    if edit == "resubmitted_rule_and_date":
        payload = {
            "due_date": "2026-10-06T09:00:00Z",
            "recurrence": "FREQ=WEEKLY",
            "tz": "UTC",
        }
        expected = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
    else:
        response = await client.patch(
            a.g(f"/tasks/{first.id}"),
            headers=a.headers,
            json={"due_date": "2026-10-07T09:00:00Z", "scope": "this"},
        )
        assert response.status_code == 200, response.text
        payload = {"recurrence": "FREQ=WEEKLY", "tz": "UTC"}
        expected = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
    response = await client.patch(
        a.g(f"/tasks/{first.id}"), headers=a.headers, json=payload
    )
    assert response.status_code == 200, response.text
    if operation == "skip":
        response = await client.post(a.g(f"/tasks/{first.id}/skip"), headers=a.headers)
        assert response.status_code == 200, response.text
        current = response.json()
    else:
        response = await client.patch(
            a.g(f"/tasks/{first.id}"),
            headers=a.headers,
            json={"status_category": "done"},
        )
        assert response.status_code == 200, response.text
        conditions = json.dumps(
            [{"field": "project_id", "op": "eq", "value": a.project.id}]
        )
        response = await client.get(
            a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        (current,) = [row for row in response.json()["items"] if row["recurrence"]]
    assert datetime.fromisoformat(current["due_date"]) == expected


async def test_fixed_to_rolling_count_keeps_the_remaining_series_end(
    client, session, acting_user
):
    from datetime import timedelta

    a = await acting_user(guild_role="member", initiative=True, project=True)
    first = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 10, 5, 9, tzinfo=timezone.utc),
        recurrence="RRULE:FREQ=DAILY;COUNT=3",
    )
    response = await client.patch(
        a.g(f"/tasks/{first.id}"),
        headers=a.headers,
        json={"recurrence_strategy": "rolling"},
    )
    assert response.status_code == 200, response.text
    task_id = first.id
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    for consumed in (1, 2, 3):
        response = await client.patch(
            a.g(f"/tasks/{task_id}"),
            headers=a.headers,
            json={"status_category": "done"},
        )
        assert response.status_code == 200, response.text
        response = await client.get(
            a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        active = [row for row in response.json()["items"] if row["recurrence"]]
        if consumed == 3:
            assert active == []
            break
        (current,) = active
        task_id = current["id"]
        assert current["recurrence_occurrence_count"] == consumed
        assert datetime.fromisoformat(current["recurrence_until"]) == (
            datetime.fromisoformat(current["due_date"]) + timedelta(days=2 - consumed)
        )


async def _remove_saved_anchor(session, task):
    from sqlalchemy import text

    connection = await session.connection()
    await connection.execute(
        text(
            "UPDATE tasks SET recurrence_anchor = NULL, recurrence_anchor_count = 0 WHERE id = :id"
        ),
        {"id": task.id},
    )
    await session.commit()
    await session.refresh(
        task, attribute_names=["recurrence_anchor", "recurrence_anchor_count"]
    )
    assert task not in session.dirty


@pytest.mark.parametrize("has_carried_dates", [False, True])
async def test_next_dates_without_a_saved_anchor_leaves_the_orm_task_clean(
    session, acting_user, has_carried_dates
):
    from app.services.tenant.task_series import next_dates

    a = await acting_user(guild_role="member", initiative=True, project=True)
    baseline = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    displayed = (
        datetime(2026, 10, 9, 9, tzinfo=timezone.utc) if has_carried_dates else baseline
    )
    task = await create_task(
        session,
        a.project,
        start_date=displayed,
        due_date=displayed,
        recurrence="RRULE:FREQ=WEEKLY;COUNT=4\nRDATE:20261007T090000Z",
        recurrence_occurrence_count=2,
        recurrence_carry={
            "due_date": baseline.isoformat(),
            "start_date": baseline.isoformat(),
        }
        if has_carried_dates
        else None,
    )
    await _remove_saved_anchor(session, task)
    before = (task.recurrence_anchor, task.recurrence_anchor_count)
    dates = next_dates(task, now=baseline, user_timezone="UTC")
    expected = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
    assert dates == (expected, expected)
    assert (task.recurrence_anchor, task.recurrence_anchor_count) == before
    assert task not in session.dirty
    assert not session.is_modified(task, include_collections=False)


@pytest.mark.parametrize("operation", ["complete", "skip"])
@pytest.mark.parametrize("has_carried_dates", [False, True])
async def test_advancing_without_a_saved_anchor_preserves_the_original_phase(
    client, session, acting_user, operation, has_carried_dates
):
    a = await acting_user(guild_role="member", initiative=True, project=True)
    baseline = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    displayed = (
        datetime(2026, 10, 9, 9, tzinfo=timezone.utc) if has_carried_dates else baseline
    )
    task = await create_task(
        session,
        a.project,
        start_date=displayed,
        due_date=displayed,
        recurrence="RRULE:FREQ=WEEKLY;COUNT=4\nRDATE:20261007T090000Z",
        recurrence_occurrence_count=2,
        recurrence_carry={
            "due_date": baseline.isoformat(),
            "start_date": baseline.isoformat(),
        }
        if has_carried_dates
        else None,
    )
    await _remove_saved_anchor(session, task)
    task_id = task.id
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    for day in (7, 12):
        if operation == "skip":
            response = await client.post(
                a.g(f"/tasks/{task_id}/skip"), headers=a.headers
            )
            assert response.status_code == 200, response.text
            current = response.json()
        else:
            response = await client.patch(
                a.g(f"/tasks/{task_id}"),
                headers=a.headers,
                json={"status_category": "done"},
            )
            assert response.status_code == 200, response.text
            response = await client.get(
                a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
            )
            assert response.status_code == 200, response.text
            (current,) = [row for row in response.json()["items"] if row["recurrence"]]
            task_id = current["id"]
        assert datetime.fromisoformat(current["due_date"]) == datetime(
            2026, 10, day, 9, tzinfo=timezone.utc
        )
        assert current["start_date"] == current["due_date"]
        assert datetime.fromisoformat(current["recurrence_anchor"]) == baseline
        assert current["recurrence_anchor_count"] == 2
    from app.services.tenant.task_series import next_dates

    await session.refresh(task)
    if operation == "complete":
        from app.models.tenant.task import Task

        task = await session.get(Task, task_id)
        assert task is not None
    assert next_dates(task, now=baseline, user_timezone="UTC") is None
