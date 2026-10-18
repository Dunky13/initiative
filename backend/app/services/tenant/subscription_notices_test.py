"""Subscribers hear of what other people change on what they subscribed to:
after they subscribed, on one line per item, a comment included, and nothing of
what the platform holds."""

from typing import cast

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.services.tenant import subscription_notices
from app.testing import create_resource_grant, create_task, drain_notices


async def _tell(guild_id: int) -> None:
    """Run the sweep's visit as the sweep does, then deliver what it wrote."""
    async with cohorts.system_session(guild_id) as system:
        await subscription_notices.tell_subscribers(system, guild_id)
        await system.commit()
    await drain_notices()


async def _lines(session: AsyncSession, user_id: int) -> list[Notification]:
    return list(
        await session.exec(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.type == NotificationType.subscription_activity,
            )
        )
    )


async def test_a_subscriber_hears_of_changes_after_subscribing(
    client, session: AsyncSession, acting_user
):
    """Subscribed to the project, a member hears of an edit to a task in it
    and of a comment on it, on the task's one line; not of the edit made before
    they subscribed. Whoever made a change hears nothing of their own."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, a.project, user=b.user)
    task_id = cast(int, (await create_task(session, a.project, title="Hall")).id)
    guild_id, project_id, a_id, b_id = a.guild.id, a.project.id, a.user.id, b.user.id

    before = await client.patch(
        a.g(f"/tasks/{task_id}"), headers=a.headers, json={"title": "Book the hall"}
    )
    assert before.status_code == 200, before.text
    for actor, path in ((b, f"project/{project_id}"), (a, f"task/{task_id}")):
        subscribed = await client.put(
            actor.g(f"/personal-items/subscribe/{path}"), headers=actor.headers
        )
        assert subscribed.status_code == 200, subscribed.text
    await _tell(guild_id)
    assert await _lines(session, b_id) == []

    after = await client.patch(
        a.g(f"/tasks/{task_id}"), headers=a.headers, json={"title": "Book the big hall"}
    )
    assert after.status_code == 200, after.text
    await _tell(guild_id)
    (line,) = await _lines(session, b_id)
    assert (line.data["entity_type"], line.data["entity_id"], line.data["verb"]) == (
        "task",
        task_id,
        "edited",
    )

    commented = await client.post(
        a.g("/comments/"),
        headers=a.headers,
        json={"task_id": task_id, "content": "On it"},
    )
    assert commented.status_code == 201, commented.text
    await drain_notices()
    session.expire_all()
    (line,) = await _lines(session, b_id)
    assert line.data["verb"] == "commented"
    assert await _lines(session, a_id) == []

    held = await client.patch(
        a.g(f"/tasks/{task_id}"), headers=a.headers, json={"title": "Held hall"}
    )
    assert held.status_code == 200, held.text
    async with cohorts.system_session(guild_id) as system:
        await set_rls_context(system, SystemGuild(guild_id))
        await system.exec(  # type: ignore[call-overload]
            text("UPDATE tasks SET held_at = now() WHERE id = :id"),
            params={"id": task_id},
        )
        await system.commit()
    await _tell(guild_id)
    session.expire_all()
    (line,) = await _lines(session, b_id)
    assert line.data["verb"] == "commented"
