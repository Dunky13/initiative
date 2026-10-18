"""Telling subscribers what people changed on what they subscribed to.

A member subscribes to a tool or to anything inside one (``personal_items``),
and hears of what other people do to it, or to what is inside a tool they
subscribed to. A comment is told on the comment's own path, with everyone else
a comment concerns, so nobody hears of one twice
(``comments._process_comment_notifications``). Every other change is read from
the change log here, one committed transaction at a time, and each transaction
is recorded once its subscribers are told (``subscription_notices``), in the
same transaction as their notices.

What counts is what the activity feed counts: people's changes, never a
plug-in's, and not the facets that are no news (``activity_feed.QUIET_FACETS``).
Each change is told about the item it is part of (``content_item_of``), on the
one line each subscriber keeps for that item, as the feed names it: created,
completed, edited and so on. A subscriber hears only of what happened after
they subscribed, and ``notifications.notify`` decides the rest: only people
who can still open it, never the person who made the change, and what each of
them switched off.

The sweep wakes only while somebody in the community is subscribed to
something. A transaction from before the earliest subscription there is told to
nobody, so the first subscription settles those in one statement rather than
reading a week of the change log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import BigInteger, DateTime, Integer, bindparam, func, select, text
from sqlalchemy import column as sa_column
from sqlalchemy import table as sa_table
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.holds import HOLDABLE_TABLES
from app.db.initiative_rls import entity_tables
from app.db.request_context import SystemGuild, SystemMaintenance
from app.db.session import set_rls_context
from app.models.platform.notification import NotificationType
from app.models.tenant.personal_item import PersonalItem
from app.services import notifications
from app.services.platform import accounts as accounts_service
from app.services.tenant import activity_feed, personal_items

if TYPE_CHECKING:
    from app.services.tenant.expiry import Expiring

#: Transactions one visit takes; the rest wait for the next.
BATCH_LIMIT = 50

#: The verb a line names when one transaction did several things to an item:
#: the one that says the most.
VERB_ORDER: tuple[str, ...] = (
    activity_feed.Verb.completed.value,
    activity_feed.Verb.published.value,
    activity_feed.Verb.created.value,
    activity_feed.Verb.moved.value,
    activity_feed.Verb.scheduled.value,
    activity_feed.Verb.edited.value,
)

#: A committed transaction of the change log nobody has been told of yet.
_UNTOLD = (
    "pg_visible_in_snapshot(o.txn_id::text::xid8, pg_current_snapshot())"
    " AND NOT EXISTS (SELECT 1 FROM subscription_notices n"
    " WHERE n.txn_id = o.txn_id)"
)
#: The oldest of them, by the first change each wrote.
_PENDING = text(
    "SELECT o.txn_id FROM event_outbox o WHERE "
    + _UNTOLD
    + " GROUP BY o.txn_id ORDER BY min(o.id) ASC LIMIT :limit"
).bindparams(bindparam("limit", type_=Integer))
#: Every untold transaction that ended before anybody subscribed, settled.
_BEFORE_ANYONE = text(
    "INSERT INTO subscription_notices (txn_id, settled_at)"
    " SELECT o.txn_id, :now FROM event_outbox o WHERE "
    + _UNTOLD
    + " GROUP BY o.txn_id HAVING max(o.occurred_at) < :earliest"
    " ON CONFLICT (txn_id) DO NOTHING"
).bindparams(
    bindparam("now", type_=DateTime(timezone=True)),
    bindparam("earliest", type_=DateTime(timezone=True)),
)
_CLAIM = text(
    "INSERT INTO subscription_notices (txn_id, settled_at) VALUES (:txn, :now)"
    " ON CONFLICT (txn_id) DO NOTHING RETURNING txn_id"
).bindparams(
    bindparam("txn", type_=BigInteger),
    bindparam("now", type_=DateTime(timezone=True)),
)


def _changes() -> Any:
    """What one transaction changed, by the item each change is part of: who
    changed it, when, the verbs it comes to, the item's title and the tool it
    is in."""
    sql = f"""
        WITH changes AS (
            SELECT o.resource_type, o.resource_id, o.parents, o.action,
                   o.changed::text[] AS changed, o.actor_user_id, o.occurred_at
            FROM event_outbox o
            WHERE o.txn_id = :txn
              AND o.actor_user_id IS NOT NULL
              AND o.actor_install_id IS NULL
              AND o.resource_type <> 'comments'
              AND NOT (o.action = 'updated' AND o.changed::text[] <@ :quiet)
        )
        SELECT item.kind, item.id, o.actor_user_id AS actor,
               max(o.occurred_at) AS occurred_at,
               array_agg(DISTINCT v.verb) FILTER (WHERE v.verb IS NOT NULL)
                   AS verbs,
               max(se.title) AS title, max(se.dac_tool) AS tool,
               max(se.dac_id) AS tool_id
        FROM changes o
        CROSS JOIN LATERAL content_item_of(o.resource_type, o.resource_id, o.parents)
            AS item
        CROSS JOIN LATERAL (SELECT {activity_feed._verb()} AS verb) AS v
        LEFT JOIN search_entries se
          ON se.entity_type = item.kind AND se.entity_id = item.id
         AND se.chunk_ix = 0
        GROUP BY item.kind, item.id, o.actor_user_id
        """
    return text(sql).bindparams(
        bindparam("txn", type_=BigInteger),
        bindparam("quiet", type_=ARRAY(Text)),
        bindparam("schedule_columns", type_=ARRAY(Text)),
        bindparam("item_tables", type_=ARRAY(Text)),
    )


def _earliest_subscription():
    return select(func.min(PersonalItem.subscribed_at)).where(
        col(PersonalItem.subscribed_at).is_not(None)
    )


def next_due(now: datetime):
    """Now while somebody is subscribed and a committed transaction is untold,
    else nothing."""
    del now
    untold = text("EXISTS (SELECT 1 FROM event_outbox o WHERE " + _UNTOLD + ")")
    subscribed = (
        select(PersonalItem.user_id)
        .where(col(PersonalItem.subscribed_at).is_not(None))
        .exists()
    )
    return select(func.now()).where(subscribed, untold)


async def _held(session: AsyncSession, table: str, row_id: int) -> bool:
    """Whether the platform holds this row: a held row reads as absent to the
    community, so nobody in it hears of it."""
    if table not in HOLDABLE_TABLES:
        return False
    row = sa_table(table, sa_column("id"), sa_column("held_at"))
    found = await session.exec(  # type: ignore[call-overload]
        select(row.c.id).where(row.c.id == row_id, row.c.held_at.is_not(None))
    )
    return found.first() is not None


async def _tell(session: AsyncSession, txn_id: int) -> None:
    """Tell the subscribers of everything one transaction changed."""
    rows = (
        await session.exec(  # type: ignore[call-overload]
            _changes(), params={"txn": txn_id, **activity_feed.verb_params()}
        )
    ).mappings()
    for row in list(rows):
        verbs = set(row["verbs"] or ())
        verb = next((v for v in VERB_ORDER if v in verbs), None)
        if verb is None:
            continue
        about = (row["kind"], row["id"])
        # The tool an item is in, as its search entry names it, or as the
        # registries resolve it where it has none.
        subject = None
        if row["tool"] is not None:
            tool = (row["tool"], row["tool_id"])
        else:
            subject = await notifications.resolve_subject(session, about)
            if subject is None:
                continue
            tool = (subject.tool.value, subject.resource_id)
        recipients = await personal_items.subscribers(
            session, about, tool, since=row["occurred_at"]
        )
        if not recipients:
            continue
        subject = subject or await notifications.resolve_subject(session, about)
        actor = await accounts_service.load_one(row["actor"])
        if subject is None or actor is None:
            continue
        if await _held(session, entity_tables()[about[0]], about[1]) or await _held(
            session, subject.tool.plural, subject.resource_id
        ):
            continue
        name = await notifications.actor_name(session, actor)
        await notifications.notify(
            session,
            NotificationType.subscription_activity,
            recipients,
            about=subject,
            key="subscription.changed",
            values={"actor": name, "context": row["title"] or ""},
            data={"entity_type": about[0], "entity_id": about[1], "verb": verb},
            actor=actor,
            rollup_key=f"subscription:{about[0]}:{about[1]}",
        )


async def tell_subscribers(session: AsyncSession, guild_id: int) -> None:
    """The sweep's visit: take the untold transactions, oldest first, and tell
    each one's subscribers. A transaction another pass took first is left to it.

    The scan runs as the platform's maintenance login, which reads which
    transactions exist and nothing of what they say; what they say is read
    routed into the community, where the policies decide it."""
    now = datetime.now(timezone.utc)
    await set_rls_context(session, SystemGuild(guild_id))
    earliest: Optional[datetime] = (
        await session.exec(_earliest_subscription())  # type: ignore[call-overload]
    ).scalar_one_or_none()
    if earliest is None:
        return
    await session.exec(  # type: ignore[call-overload]
        _BEFORE_ANYONE, params={"now": now, "earliest": earliest}
    )
    await set_rls_context(session, SystemMaintenance(guild_id))
    pending = [
        row[0]
        for row in await session.exec(  # type: ignore[call-overload]
            _PENDING, params={"limit": BATCH_LIMIT}
        )
    ]
    await set_rls_context(session, SystemGuild(guild_id))
    for txn_id in pending:
        claimed = (
            await session.exec(  # type: ignore[call-overload]
                _CLAIM, params={"txn": txn_id, "now": now}
            )
        ).first()
        if claimed is not None:
            await _tell(session, txn_id)


async def expire(session: AsyncSession, expiring: Expiring) -> None:
    """Drop the records of transactions the change log let go: they go with
    the changes they record."""
    if not expiring.expired_txns:
        return
    await session.exec(  # type: ignore[call-overload]
        text("DELETE FROM subscription_notices WHERE txn_id = ANY(:txn_ids)"),
        params={"txn_ids": sorted(expiring.expired_txns)},
    )
