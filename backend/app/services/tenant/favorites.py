"""A member's stars: any tool, kept in the tool's own community.

A star is ``(user_id, entity_type, entity_id)`` in ``favorites``, the shape of
``recent_views``: the row says who and what, its schema says which community,
and RLS reaches the tool it names to decide whether the reader may still see it.
A star on something the reader can no longer read is simply not shown.

Everything here runs on the routed session, which already holds the reader to
their own rows (``PRIVATE_ROW_TABLES``); the purges run as the platform,
because whoever triggers them cannot reach rows that are someone else's alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.tenant.favorite import Favorite

#: The most stars one community's list carries. Far more than anybody keeps;
#: a bound so a list read is never open-ended.
MAX_FAVORITES = 200


async def add(
    session: AsyncSession, *, user_id: int, tool: Tool, entity_id: int
) -> None:
    """Star it. Starring something already starred keeps the first star's time."""
    await session.exec(
        pg_insert(Favorite)
        .values(
            user_id=user_id,
            entity_type=tool.value,
            entity_id=entity_id,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "entity_type", "entity_id"])
    )
    await session.commit()


async def remove(
    session: AsyncSession, *, user_id: int, tool: Tool, entity_id: int
) -> None:
    """Take the star off. Idempotent."""
    await session.exec(
        delete(Favorite).where(  # type: ignore[arg-type]
            col(Favorite.user_id) == user_id,
            col(Favorite.entity_type) == tool.value,
            col(Favorite.entity_id) == entity_id,
        )
    )
    await session.commit()


async def list_favorites(
    session: AsyncSession, *, user_id: int, limit: int = MAX_FAVORITES
) -> Sequence[Favorite]:
    """This community's stars, newest first."""
    return (
        await session.exec(
            select(Favorite)
            .where(Favorite.user_id == user_id)
            .order_by(col(Favorite.created_at).desc())
            .limit(limit)
        )
    ).all()


async def starred_ids(
    session: AsyncSession, *, user_id: int, tool: Tool, ids: Iterable[int]
) -> set[int]:
    """Which of these the reader starred, for a list that marks them."""
    wanted = list(ids)
    if not wanted:
        return set()
    return set(
        (
            await session.exec(
                select(Favorite.entity_id).where(
                    Favorite.user_id == user_id,
                    Favorite.entity_type == tool.value,
                    col(Favorite.entity_id).in_(wanted),
                )
            )
        ).all()
    )


async def purge_for_entities(
    session: AsyncSession, entity_type: str, entity_ids: Iterable[int]
) -> None:
    """Drop everyone's star on these, for a purge: ``entity_id`` is a weak
    reference, so nothing carries the rows out with the tool."""
    from app.db.cohorts import exec_as_system

    ids = tuple(entity_ids)
    if not ids:
        return
    await exec_as_system(
        session,
        delete(Favorite).where(  # type: ignore[arg-type]
            col(Favorite.entity_type) == entity_type,
            col(Favorite.entity_id).in_(ids),
        ),
    )


async def purge_for_user(session: AsyncSession, user_id: int) -> None:
    """Drop a person's stars in this community, for their leaving it."""
    from app.db.cohorts import exec_as_system

    await exec_as_system(
        session,
        delete(Favorite).where(col(Favorite.user_id) == user_id),  # type: ignore[arg-type]
    )
