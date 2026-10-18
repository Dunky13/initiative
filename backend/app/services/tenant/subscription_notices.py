"""Telling subscribers what people changed on what they are subscribed to.

Who is subscribed is :func:`personal_items.subscribers_of`: whoever made an item
or is named on it, and whoever subscribed to it or to its tool, less whoever
unsubscribed. Comments, reactions and answers are told where they are made, in
the writer's own transaction (``comments``, ``reactions``, the RSVP route).
Every other change has no such place, since the change log is the one record of
every write, so it is told from there: one batch of committed transactions at a
time, by this sweep.

Each subscriber is told **as themselves**. The batch is picked, and the people
it concerns are found, as the platform, by identifiers alone; that decides only
whom to ask. Then each of them is routed into the community through the seam a
request takes (``cross_guild.gather_across_guilds``, ``on_behalf``), and reads
what the batch did with the activity feed's own statement
(``activity_feed.batch_query``), so their own policies decide what reaches
them: sharing, the initiative, holds, archiving. Nothing here restates them.

What counts is what the feed counts, not the facets that are no news
(``activity_feed.QUIET_FACETS``) and never the reader's own, with one more: a
plug-in's change (an automation completing a task, a calendar moving an event)
is told to the people named on the item, though not to everyone following it,
naming the plug-in, or the member it acted for. Somebody named on an item (an assignee, an attendee) hears of it
under what they are given (``assigned_activity``); everyone else under what
they follow (``subscription_activity``). Either is one line per item, which a
comment on it joins. A subscription by hand hears only of what happened after
it.

Progress is one row (``subscription_progress``): a transaction-id snapshot,
so a transaction that commits after a later one has been told is still read.
It moves once a batch is told; a visit cut short tells that batch again, and
the notices join the lines they already opened. The migration that made it
started each community's where its log stood; a community made since starts
at the beginning of its own.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import Any

from sqlalchemy import BigInteger, Integer, bindparam, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.subscription_progress import SubscriptionProgress
from app.services import notifications
from app.services.cross_guild import gather_across_guilds
from app.services.platform import accounts as accounts_service
from app.services.tenant import activity_feed, personal_items
from app.services.tenant.personal_items import Ref, Subscriber, Tie

#: Transactions one visit takes; the rest are due at once.
BATCH_LIMIT = 50

#: The verb a line names when one batch did several things to an item: the
#: one that says the most.
VERB_ORDER: tuple[str, ...] = (
    activity_feed.Verb.completed.value,
    activity_feed.Verb.published.value,
    activity_feed.Verb.created.value,
    activity_feed.Verb.moved.value,
    activity_feed.Verb.scheduled.value,
    activity_feed.Verb.edited.value,
)

#: The oldest untold transactions (committed, and past the progress row), and
#: the oldest transaction still running, read in one snapshot.
_PICK = text(
    "SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint AS xmin,"
    " ARRAY(SELECT o.txn_id FROM event_outbox o, subscription_progress p"
    " WHERE o.txn_id >= p.told_xmin AND o.txn_id <> ALL (p.told_above)"
    " AND pg_visible_in_snapshot(o.txn_id::text::xid8, pg_current_snapshot())"
    " GROUP BY o.txn_id ORDER BY o.txn_id LIMIT :limit)"
    " AS untold"
).bindparams(bindparam("limit", type_=Integer))

#: What a batch changed, by the item each change is part of and the tool it is
#: in: identifiers only, for finding whom it concerns.
_CONCERNS = text(
    "SELECT item.kind, item.id, o.dac_tool, o.dac_id,"
    " max(o.occurred_at) AS latest, bool_or(o.actor_install_id IS NULL) AS by_people"
    " FROM event_outbox o"
    " CROSS JOIN LATERAL content_item_of(o.resource_type, o.resource_id, o.parents)"
    " AS item"
    " WHERE o.txn_id = ANY (:txns)"
    " AND (o.actor_user_id IS NOT NULL OR o.actor_install_id IS NOT NULL)"
    " AND o.resource_type <> 'comments'"
    " AND NOT (o.action = 'updated' AND o.changed::text[] <@ :quiet)"
    " GROUP BY item.kind, item.id, o.dac_tool, o.dac_id"
).bindparams(
    bindparam("txns", type_=ARRAY(BigInteger)),
    bindparam("quiet", type_=ARRAY(Text)),
)

#: Who made the batch's changes: the people, and the installs that acted as
#: themselves.
_ACTORS = text(
    "SELECT DISTINCT actor_user_id, actor_install_id FROM event_outbox"
    " WHERE txn_id = ANY (:txns)"
).bindparams(bindparam("txns", type_=ARRAY(BigInteger)))


def next_due(now: datetime) -> Any:
    """Now while a committed transaction is past the progress row, or before
    there is one; else nothing."""
    del now
    return select(func.now()).where(
        text(
            "NOT EXISTS (SELECT 1 FROM subscription_progress)"
            " OR EXISTS (SELECT 1 FROM event_outbox o, subscription_progress p"
            " WHERE o.txn_id >= p.told_xmin AND o.txn_id <> ALL (p.told_above)"
            " AND pg_visible_in_snapshot(o.txn_id::text::xid8, pg_current_snapshot()))"
        )
    )


async def _concerned(
    session: AsyncSession, batch: list[int]
) -> dict[int, dict[Ref, Subscriber]]:
    """Everyone the batch concerns, by person: each item it changed that they
    are subscribed to, and how."""
    rows = (
        await session.exec(  # type: ignore[call-overload]
            _CONCERNS,
            params={"txns": batch, "quiet": list(activity_feed.QUIET_FACETS)},
        )
    ).all()
    items: dict[Ref, Ref | None] = {}
    latest: dict[Ref, datetime] = {}
    by_people: set[Ref] = set()
    for kind, entity_id, tool, tool_id, at, people in rows:
        ref = (kind, entity_id)
        items[ref] = None if tool is None else (tool, tool_id)
        latest[ref] = max(at, latest.get(ref, at))
        if people:
            by_people.add(ref)
    by_person: dict[int, dict[Ref, Subscriber]] = {}
    for ref, people in (await personal_items.subscribers_of(session, items)).items():
        for person, subscriber in people.items():
            # Subscribed by hand after it happened: not news to them.
            if subscriber.since is not None and subscriber.since > latest[ref]:
                continue
            # Only plug-ins changed it: news to whoever is named on it.
            if ref not in by_people and subscriber.tie is not Tie.named:
                continue
            by_person.setdefault(person, {})[ref] = subscriber
    return by_person


async def _tell(
    batch: list[int],
    concerns: dict[Ref, Subscriber],
    actors: dict[int, User],
    installs: dict[int, notifications.PluginAuthor],
    reader_id: int,
    routed: AsyncSession,
    _guild_id: int,
) -> list[None]:
    """Tell one subscriber, on a session routed as them, what the batch did
    that they can see."""
    statement, params = activity_feed.batch_query(batch, reader_id=reader_id)
    rows = (await routed.exec(statement, params=params)).mappings().all()  # type: ignore[call-overload]
    for row in rows:
        ref = (row["entity_type"], row["entity_id"])
        subscriber = concerns.get(ref)
        # The verb that says the most, and whoever did that, latest first. A
        # plug-in's change is news only to the people named on the item.
        named = subscriber is not None and subscriber.tie is Tie.named
        done = [
            entry
            for entry in (raw.split(":") for raw in row["done"] or ())
            if named or not entry[2]
        ]
        verb = next((v for v in VERB_ORDER if any(d[0] == v for d in done)), None)
        _verb, person, install = next((d for d in done if d[0] == verb), (None, "", ""))
        actor: User | notifications.PluginAuthor | None = (
            actors.get(int(person))
            if person
            else installs.get(int(install))
            if install
            else None
        )
        if subscriber is None or verb is None or actor is None:
            continue
        line = "assigned" if named else "subscription"
        await notifications.notify(
            routed,
            NotificationType.assigned_activity
            if named
            else NotificationType.subscription_activity,
            [reader_id],
            about=ref,
            key=f"{line}.changed",
            values={
                "actor": await notifications.actor_name(routed, actor),
                "context": row["title"] or "",
            },
            data={"entity_type": ref[0], "entity_id": ref[1], "verb": verb},
            actor=actor,
            rollup_key=f"{line}:{ref[0]}:{ref[1]}",
        )
    return []


async def tell_subscribers(session: AsyncSession, guild_id: int) -> None:
    """The sweep's visit: take the oldest untold transactions, tell everyone
    they concern, then move the progress row past them."""
    await set_rls_context(session, SystemGuild(guild_id))
    progress = (await session.exec(select(SubscriptionProgress))).one_or_none()
    if progress is None:
        # A community made since subscriptions began: everything in its log
        # is its own, so the first visit starts at the beginning of it.
        progress = SubscriptionProgress(told_xmin=0, told_above=[])
        session.add(progress)
        await session.commit()
    picked = (
        await session.exec(_PICK, params={"limit": BATCH_LIMIT + 1})  # type: ignore[call-overload]
    ).one()
    untold: list[int] = list(picked.untold)
    batch = untold[:BATCH_LIMIT]
    if batch:
        concerned = await _concerned(session, batch)
        acted = (
            await session.exec(_ACTORS, params={"txns": batch})  # type: ignore[call-overload]
        ).all()
        actors = await accounts_service.load([person for person, _ in acted])
        install_ids = [i for person, i in acted if person is None and i is not None]
        installs = {
            install_id: notifications.PluginAuthor(name=name)
            for install_id, name in (
                await session.exec(
                    select(GuildPlugin.id, GuildPlugin.name).where(
                        col(GuildPlugin.id).in_(install_ids)
                    )
                )
            ).all()
        }
        for reader_id, concerns in sorted(concerned.items()):
            await gather_across_guilds(
                session,
                reader_id,
                [guild_id],
                partial(_tell, batch, concerns, actors, installs, reader_id),
                on_behalf=True,
                writes=True,
            )
        await set_rls_context(session, SystemGuild(guild_id))
        progress = (await session.exec(select(SubscriptionProgress))).one()
    # Everything below the oldest transaction still running has ended, so it
    # was told by now or never committed; unless more were untold than one
    # batch takes, and the first of those holds the line where it starts.
    line = (
        picked.xmin
        if len(untold) <= BATCH_LIMIT
        else min(picked.xmin, untold[BATCH_LIMIT])
    )
    line = max(line, progress.told_xmin)
    progress.told_above = sorted(
        {txn for txn in (*progress.told_above, *batch) if txn >= line}
    )
    progress.told_xmin = line
    session.add(progress)
    await session.commit()
