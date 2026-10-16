"""Sweep timers: the write arms them, the worker visits only what is due."""

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import metrics
from app.db import cohorts
from app.models.platform.guild import CommunityStatus
from app.models.platform.community_timer import CommunityTimer
from app.models.tenant.post import Post
from app.services import sweep_timers
from app.services.tenant import post_publication
from app.testing import (
    create_guild,
    create_initiative,
    create_post,
    create_user,
    route_session_to_guild,
    route_system,
)


async def _community(session: AsyncSession, **guild):
    author = await create_user(session)
    community = await create_guild(session, creator=author, **guild)
    initiative = await create_initiative(session, community, author)
    return author, initiative, cast(int, community.id)


async def _scheduled(session, initiative, author, *, due_in: timedelta) -> int:
    """A notice waiting for its time, written the way a factory writes: on a
    session routed to no community, which arms nothing."""
    post = await create_post(
        session,
        initiative,
        author,
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + due_in,
    )
    return cast(int, post.id)


async def _timers(
    session: AsyncSession, kind: str | None = None
) -> list[tuple[int, str, datetime]]:
    rows = await session.exec(
        text(
            "SELECT community_id, kind, due_at FROM public.community_timers"
            " ORDER BY due_at"
        )
    )
    return [tuple(row) for row in rows.all() if kind in (None, row.kind)]  # type: ignore[misc]


async def _as_community(community_id: int, *statements) -> None:
    """Run ``statements`` routed into the community the way its sweeps and
    requests are, and commit."""
    async with cohorts.system_session(community_id) as routed:
        await route_system(routed, guild_id=community_id)
        for statement in statements:
            await routed.exec(statement)
        await routed.commit()


async def _due_now(session: AsyncSession, community_id: int, kind: str) -> None:
    """A timer that has come due, however it was armed."""
    await session.exec(
        text(
            "INSERT INTO public.community_timers (community_id, kind, due_at)"
            " VALUES (:community, :kind, now())"
        ).bindparams(community=community_id, kind=kind)
    )
    await session.commit()


def _reschedule(post_id: int, at: datetime):
    return update(Post).where(Post.id == post_id).values(scheduled_for=at)  # type: ignore[arg-type]


async def test_a_routed_write_arms_its_timer_once(session: AsyncSession):
    """Only a write routed into the community arms, the earliest timer wins,
    and a later one adds nothing while it waits."""
    author, initiative, community_id = await _community(session)
    first = await _scheduled(session, initiative, author, due_in=timedelta(hours=2))
    second = await _scheduled(session, initiative, author, due_in=timedelta(hours=3))
    assert await _timers(session) == []

    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    await _as_community(community_id, _reschedule(first, soon))
    await _as_community(community_id, _reschedule(second, soon + timedelta(hours=1)))
    assert await _timers(session) == [(community_id, "posts", soon)]

    sooner = soon - timedelta(minutes=30)
    await _as_community(community_id, _reschedule(second, sooner))
    assert [due for _c, _k, due in await _timers(session)] == [sooner, soon]


async def test_a_change_arms_the_upkeep_and_the_webhook_backstop(
    session: AsyncSession,
):
    author, initiative, community_id = await _community(session)
    post = await create_post(session, initiative, author)

    await _as_community(
        community_id,
        update(Post).where(Post.id == post.id).values(name="Renamed"),  # type: ignore[arg-type]
    )

    assert {kind for _c, kind, _due in await _timers(session)} == {
        "webhooks",
        "expiry",
        "engagement",
        sweep_timers.RECONCILE,
    }


async def test_the_worker_runs_what_is_due_and_arms_the_next(session: AsyncSession):
    author, initiative, community_id = await _community(session)
    due = await _scheduled(session, initiative, author, due_in=timedelta(hours=1))
    later = datetime.now(timezone.utc) + timedelta(hours=3)
    pending = await _scheduled(session, initiative, author, due_in=timedelta(hours=3))
    await _as_community(
        community_id,
        _reschedule(due, datetime.now(timezone.utc) - timedelta(minutes=1)),
        _reschedule(pending, later),
    )

    await sweep_timers.process_due_timers()

    await route_session_to_guild(session, community_id)
    published = (
        await session.exec(select(Post.id).where(Post.published_at.is_not(None)))  # type: ignore[union-attr]
    ).all()
    assert published == [due]
    # Publishing is a change of its own, which arms the community's upkeep.
    assert await _timers(session, "posts") == [(community_id, "posts", later)]


async def test_a_community_that_cannot_take_the_sweep_keeps_its_timer(
    session: AsyncSession,
):
    """Suspended, its posts wait; the timer comes back each lease until it
    returns."""
    author, initiative, community_id = await _community(
        session, status=CommunityStatus.suspended.value
    )
    post_id = await _scheduled(
        session, initiative, author, due_in=-timedelta(minutes=1)
    )
    await _due_now(session, community_id, "posts")

    await sweep_timers.process_due_timers()

    [(_c, kind, due)] = await _timers(session)
    assert kind == "posts" and due > datetime.now(timezone.utc)
    await route_session_to_guild(session, community_id)
    assert (await session.get(Post, post_id)).published_at is None  # type: ignore[union-attr]


async def test_a_failed_visit_keeps_its_timer(session: AsyncSession, monkeypatch):
    author, initiative, community_id = await _community(session)
    await _scheduled(session, initiative, author, due_in=-timedelta(minutes=1))
    await _due_now(session, community_id, "posts")

    async def fails(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(post_publication, "publish_due_posts", fails)
    await sweep_timers.process_due_timers()

    [(_c, kind, due)] = await _timers(session)
    assert kind == "posts" and due > datetime.now(timezone.utc)


async def test_reconcile_arms_what_no_write_did_and_counts_it(session: AsyncSession):
    author, initiative, community_id = await _community(session)
    await _scheduled(session, initiative, author, due_in=timedelta(hours=2))
    await _due_now(session, community_id, sweep_timers.RECONCILE)
    repairs = metrics.sweep_timer_repairs.labels("posts")._value.get()

    await sweep_timers.process_due_timers()

    [(_c, _k, posts)] = await _timers(session, "posts")
    assert posts > datetime.now(timezone.utc) + timedelta(hours=1)
    [(_c, _k, again)] = await _timers(session, sweep_timers.RECONCILE)
    assert again > datetime.now(timezone.utc) + timedelta(hours=23)
    assert metrics.sweep_timer_repairs.labels("posts")._value.get() == repairs + 1


async def test_a_community_arms_its_own_timers_and_reads_none(session: AsyncSession):
    _author, _initiative, community_id = await _community(session)
    _other_author, _other, other_id = await _community(session)
    due = datetime.now(timezone.utc)

    async with cohorts.system_session(community_id) as routed:
        await route_system(routed, guild_id=community_id)
        for statement, refused in (
            (
                text(
                    "INSERT INTO public.community_timers (community_id, kind, due_at)"
                    " VALUES (:community, 'posts', :due)"
                ).bindparams(community=other_id, due=due),
                "row-level security",
            ),
            (text("SELECT * FROM public.community_timers"), "permission denied"),
        ):
            with pytest.raises(DBAPIError, match=refused):
                await routed.exec(statement)
            await routed.rollback()
            await route_system(routed, guild_id=community_id)


def test_a_timer_names_the_community_the_sweep_and_the_time_and_nothing_else():
    """What the work is, the visit reads from the community's own schema."""
    assert set(CommunityTimer.__table__.columns.keys()) == {  # type: ignore[attr-defined]
        "id",
        "community_id",
        "kind",
        "due_at",
    }
