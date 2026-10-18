"""What each member keeps about the items in a community: their opens, stars,
follows and their own order of projects, one ``personal_items`` row per item.

Opening any tool, or anything inside one, records a view; the tools' views are
the layout header's tabs. Every view is kept for :data:`WINDOW`; past it, a
tool is kept while it is among the person's newest tabs, and anything else goes.
A star is on a tool, a follow on anything, and both last until taken off.

A row holds at least one of these, which the table checks. So each path that
lets one go deletes the rows where it was the last, and empties it in the rest.

Everything here runs on the routed session, which already holds the reader to
their own rows (``PRIVATE_ROW_TABLES``). Letting go of a mark, and the purges,
run as the platform: the row may name something the reader can no longer open,
and whoever triggers a purge cannot reach rows that are someone else's alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterable, Optional, Sequence

from sqlalchemy import func, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.personal_item import TOOL_KINDS, PersonalItem, ViewSource
from app.services.tenant.change_log import RETENTION

if TYPE_CHECKING:
    from app.services.tenant.expiry import Expiring


class Mark(str, Enum):
    """What a member sets and clears on an item."""

    #: Opened it. Any kind; a tool's view is a tab.
    view = "view"
    #: Starred it. Tools only.
    star = "star"
    #: Following it, which lifts it and what is inside it in their feed.
    follow = "follow"


#: The columns each mark sets, the first being its time.
MARK_COLUMNS: dict[Mark, tuple[str, ...]] = {
    Mark.view: ("viewed_at", "view_source"),
    Mark.star: ("starred_at",),
    Mark.follow: ("followed_at",),
}

#: Every column that keeps a row: each mark's time, and the project order.
_HOLDING = ("viewed_at", "starred_at", "followed_at", "sort_order")

# Per-user cap on tabs kept and shown. The user's ``recent_tabs_limit``
# (Interface settings) picks the value within these bounds.
MIN_RECENT_VIEWS = 1
MAX_RECENT_VIEWS = 100
DEFAULT_RECENT_VIEWS = 20

#: How long every open is kept, tab or not: the span the change log keeps, so
#: what people opened and what they changed cover the same days.
WINDOW = RETENTION


def clamp_recent_limit(value: int | None) -> int:
    """A user's ``recent_tabs_limit`` within the allowed range, the default
    where they never set one."""
    if value is None:
        return DEFAULT_RECENT_VIEWS
    return max(MIN_RECENT_VIEWS, min(MAX_RECENT_VIEWS, value))


def _key(user_id: int, kind: str, entity_id: int) -> list[Any]:
    return [
        col(PersonalItem.user_id) == user_id,
        col(PersonalItem.entity_type) == kind,
        col(PersonalItem.entity_id) == entity_id,
    ]


async def _upsert(
    session: AsyncSession, user_id: int, kind: str, entity_id: int, **values: Any
) -> None:
    """Write these columns on the row, making it where there is none."""
    await session.exec(
        pg_insert(PersonalItem)
        .values(user_id=user_id, entity_type=kind, entity_id=entity_id, **values)
        .on_conflict_do_update(
            index_elements=["user_id", "entity_type", "entity_id"], set_=values
        )
    )


async def record_view(
    session: AsyncSession,
    *,
    user_id: int,
    entity_type: str,
    entity_id: int,
    source: ViewSource = ViewSource.direct,
    persist: bool = True,
) -> datetime:
    """Record an open and where it came from, and return its time. What a
    person no longer keeps goes in the expiry sweep (:func:`expire`).

    ``persist=False`` writes nothing: a PAM grantee's browsing is transient.
    """
    now = datetime.now(timezone.utc)
    if persist:
        await _upsert(
            session,
            user_id,
            entity_type,
            entity_id,
            viewed_at=now,
            view_source=source.value,
        )
        await session.commit()
    return now


async def set_mark(
    session: AsyncSession, *, user_id: int, mark: Mark, kind: str, entity_id: int
) -> None:
    """Star or follow it. Setting one already set keeps the first time."""
    (column,) = MARK_COLUMNS[mark]
    insert = pg_insert(PersonalItem).values(
        user_id=user_id,
        entity_type=kind,
        entity_id=entity_id,
        **{column: datetime.now(timezone.utc)},
    )
    await session.exec(
        insert.on_conflict_do_update(
            index_elements=["user_id", "entity_type", "entity_id"],
            set_={
                column: func.coalesce(
                    PersonalItem.__table__.c[column], insert.excluded[column]
                )
            },
        )
    )
    await session.commit()


async def clear_mark(
    session: AsyncSession, *, user_id: int, mark: Mark, kind: str, entity_id: int
) -> None:
    """Let go of a mark: close a tab, take a star off, stop following.
    Idempotent, and whether or not the item can still be opened, so a mark on
    something the reader has lost can still come off. Run as the platform and
    limited to the reader's own row."""
    from app.db.cohorts import exec_as_system

    columns = MARK_COLUMNS[mark]
    others = [PersonalItem.__table__.c[c] for c in _HOLDING if c != columns[0]]
    key = _key(user_id, kind, entity_id)
    await exec_as_system(
        session,
        delete(PersonalItem).where(*key, *(c.is_(None) for c in others)),  # type: ignore[arg-type]
    )
    await exec_as_system(
        session,
        update(PersonalItem)  # type: ignore[arg-type]
        .where(*key, or_(*(c.is_not(None) for c in others)))
        .values({c: None for c in columns}),
    )
    await session.commit()


async def item_state(
    session: AsyncSession, *, user_id: int, kind: str, entity_id: int
) -> Optional[PersonalItem]:
    """The reader's row on this item, if they keep anything about it."""
    return (
        await session.exec(select(PersonalItem).where(*_key(user_id, kind, entity_id)))
    ).one_or_none()


async def list_marked(
    session: AsyncSession, *, user_id: int, mark: Mark, limit: Optional[int] = None
) -> Sequence[PersonalItem]:
    """The tools the reader marked this way in this community, newest first:
    the tabs for views, the sidebar's stars for stars. Stars are listed whole:
    the list is also what lights each star on a page."""
    column = PersonalItem.__table__.c[MARK_COLUMNS[mark][0]]
    statement = (
        select(PersonalItem)
        .where(
            col(PersonalItem.user_id) == user_id,
            col(PersonalItem.entity_type).in_(TOOL_KINDS),
            column.is_not(None),
        )
        .order_by(column.desc())
    )
    if limit is not None:
        statement = statement.limit(limit)
    return (await session.exec(statement)).all()


async def rows_for(
    session: AsyncSession, *, user_id: int, kind: str, ids: Iterable[int]
) -> dict[int, PersonalItem]:
    """The reader's rows on these items of one kind, by id, for a list that
    shows what they keep about each."""
    wanted = list(ids)
    if not wanted:
        return {}
    rows = await session.exec(
        select(PersonalItem).where(
            col(PersonalItem.user_id) == user_id,
            col(PersonalItem.entity_type) == kind,
            col(PersonalItem.entity_id).in_(wanted),
        )
    )
    return {row.entity_id: row for row in rows.all()}


async def place_projects(
    session: AsyncSession, *, user_id: int, order: Sequence[int]
) -> None:
    """Put these projects in the reader's own list in this order."""
    if not order:
        return
    insert = pg_insert(PersonalItem).values(
        [
            dict(
                user_id=user_id,
                entity_type="project",
                entity_id=project_id,
                sort_order=float(index),
            )
            for index, project_id in enumerate(order)
        ]
    )
    await session.exec(
        insert.on_conflict_do_update(
            index_elements=["user_id", "entity_type", "entity_id"],
            set_={"sort_order": insert.excluded.sort_order},
        )
    )
    await session.commit()


#: Each view, ranked among its person's tabs or other views, beside that
#: person's tab limit when it is not the default.
_RANKED = """
    (
        SELECT user_id, entity_type, entity_id, viewed_at,
               entity_type = ANY (CAST(:tabs AS text[])) AS is_tab,
               row_number() OVER (
                   PARTITION BY user_id,
                                entity_type = ANY (CAST(:tabs AS text[]))
                   ORDER BY viewed_at DESC
               ) AS n
          FROM personal_items
         WHERE viewed_at IS NOT NULL
    ) ranked
    LEFT JOIN unnest(CAST(:users AS integer[]), CAST(:limits AS integer[]))
           AS chosen(user_id, tab_limit)
           ON chosen.user_id = ranked.user_id
"""

#: The view goes once it is past the window: anything but a tab among its
#: person's newest ``recent_tabs_limit``.
_LETS_GO = (
    "(NOT ranked.is_tab OR ranked.n > COALESCE(chosen.tab_limit, :default_limit))"
)

#: Every view :func:`expire` lets go: past the window, and let go. A row the
#: view was all of goes; the rest keep what else they hold. A view reopened
#: while this runs is left: it no longer has the time it was ranked by.
_EXPIRE = f"""
    WITH doomed AS (
        SELECT ranked.user_id, ranked.entity_type, ranked.entity_id,
               ranked.viewed_at
          FROM {_RANKED}
         WHERE ranked.viewed_at < :cutoff AND {_LETS_GO}
    ),
    gone AS (
        DELETE FROM personal_items p USING doomed d
         WHERE (p.user_id, p.entity_type, p.entity_id, p.viewed_at)
             = (d.user_id, d.entity_type, d.entity_id, d.viewed_at)
           AND p.starred_at IS NULL AND p.followed_at IS NULL
           AND p.sort_order IS NULL
    )
    UPDATE personal_items p SET viewed_at = NULL, view_source = NULL
      FROM doomed d
     WHERE (p.user_id, p.entity_type, p.entity_id, p.viewed_at)
         = (d.user_id, d.entity_type, d.entity_id, d.viewed_at)
       AND num_nonnulls(p.starred_at, p.followed_at, p.sort_order) > 0
"""

#: The oldest view :func:`expire` would let go once it passes the window.
_OLDEST_LET_GO = "SELECT min(ranked.viewed_at) FROM " + _RANKED + " WHERE " + _LETS_GO


def _ranking(expiring: Expiring) -> dict:
    users = list(expiring.tab_limits)
    return dict(
        tabs=list(TOOL_KINDS),
        users=users,
        limits=[expiring.tab_limits[user] for user in users],
        default_limit=DEFAULT_RECENT_VIEWS,
    )


async def expire(session: AsyncSession, expiring: Expiring) -> None:
    """Let go of each person's views past :data:`WINDOW`, except a tab among
    their newest ``recent_tabs_limit``."""
    await session.exec(
        text(_EXPIRE).bindparams(cutoff=expiring.now - WINDOW, **_ranking(expiring))
    )


async def next_due(session: AsyncSession, expiring: Expiring) -> datetime | None:
    """When the next view :func:`expire` would let go passes the window."""
    oldest = (
        await session.exec(text(_OLDEST_LET_GO).bindparams(**_ranking(expiring)))
    ).scalar_one()
    return None if oldest is None else oldest + WINDOW


async def purge_for_entities(
    session: AsyncSession, entity_type: str, entity_ids: Iterable[int]
) -> None:
    """Drop everyone's rows on these, for a purge: ``entity_id`` is a weak
    reference, so nothing carries the rows out with the item."""
    from app.db.cohorts import exec_as_system

    ids = tuple(entity_ids)
    if not ids:
        return
    await exec_as_system(
        session,
        delete(PersonalItem).where(  # type: ignore[arg-type]
            col(PersonalItem.entity_type) == entity_type,
            col(PersonalItem.entity_id).in_(ids),
        ),
    )


async def purge_for_user(session: AsyncSession, user_id: int) -> None:
    """Drop a person's rows in this community, for their leaving it."""
    from app.db.cohorts import exec_as_system

    await exec_as_system(
        session,
        delete(PersonalItem).where(col(PersonalItem.user_id) == user_id),  # type: ignore[arg-type]
    )
