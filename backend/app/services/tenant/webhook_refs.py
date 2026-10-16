"""What one webhook subscriber calls the guild, and the people writing in it.

A delivery leaves this deployment, so the guild it came from and the member
whose write caused it are named by reference rather than by row id — the same
rule every other boundary follows.

Which reference depends on who is receiving, because a reference is pairwise:

* **A plug-in registered the subscription.** It already holds a name for the guild
  and for each member, minted for it in this guild and used on every other
  exchange it has with us. A delivery arrives under those, so the plug-in can match an
  envelope to what it has stored without learning a second set of names for the
  same people.
* **A member registered it against a URL of their own.** There is no plug-in to
  borrow a sector from, so the subscription is the sector. The names are stable
  for that subscription and unrelated to every other subscriber's.

Either way the sector is ``(guild_id, <thing>)``: the plug-in by its
``public_id``, or the subscription by its per-guild row id.

Reached only on the system engine, like every other minting path, so each call
opens a session of its own: the callers are a background poller routed into a
guild role and a request handler doing the same.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from app.db import session as db_session
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.platform import identity_refs

__all__ = [
    "drop_subscription_refs",
    "name_for_subscriber",
    "names_for_subscribers",
]


def _sector(
    *, plugin: str | None, subscription_id: int
) -> tuple[IdentityPurpose, int | None, str | None]:
    """The purpose, and the row or plug-in inside the guild, that this
    subscriber is named by."""
    if plugin is not None:
        return IdentityPurpose.plugin, None, plugin
    return IdentityPurpose.webhook, subscription_id, None


#: ``(plugin, subscription_id, actor_ids)`` — one subscriber to name, by the
#: ``public_id`` of the plug-in that registered it (or ``None`` for a member's
#: own), and the people it will be told about.
Subscriber = tuple[str | None, int, Collection[int]]


async def name_for_subscriber(
    *,
    guild_id: int,
    plugin: str | None,
    subscription_id: int,
    actor_ids: Collection[int] = (),
) -> tuple[str, dict[int, str]]:
    """This subscriber's names for the guild and for each actor it will be told about.

    Returns ``(guild_ref, {user_id: ref})``. Minted on first use, in one
    session for the whole batch, because a delivery names as many people as the
    transaction it describes touched.
    """
    (names,) = await names_for_subscribers(
        guild_id=guild_id, subscribers=[(plugin, subscription_id, actor_ids)]
    )
    return names


async def names_for_subscribers(
    *, guild_id: int, subscribers: Sequence[Subscriber]
) -> list[tuple[str, dict[int, str]]]:
    """:func:`name_for_subscriber` for each of many subscribers, in order — one
    session and one commit for the lot, for a page listing them."""
    if not subscribers:
        return []
    names = []
    async with db_session.SystemSessionLocal() as session:
        for plugin, subscription_id, actor_ids in subscribers:
            purpose, sector_id, sector_plugin = _sector(
                plugin=plugin, subscription_id=subscription_id
            )
            guild_ref = await identity_refs.ensure_ref(
                session,
                entity_type=IdentityEntity.guild,
                entity_id=guild_id,
                purpose=purpose,
                sector_guild_id=guild_id,
                sector_id=sector_id,
                sector_plugin=sector_plugin,
            )
            actor_refs = {
                actor_id: await identity_refs.ensure_ref(
                    session,
                    entity_type=IdentityEntity.user,
                    entity_id=actor_id,
                    purpose=purpose,
                    sector_guild_id=guild_id,
                    sector_id=sector_id,
                    sector_plugin=sector_plugin,
                )
                for actor_id in sorted(
                    {actor_id for actor_id in actor_ids if actor_id is not None}
                )
            }
            names.append((guild_ref, actor_refs))
        await session.commit()
    return names


async def drop_subscription_refs(*, guild_id: int, subscription_id: int) -> int:
    """Remove the references minted for one subscription's own sector.

    Only the sector this module owns: a subscription a plug-in registered is named
    in that plug-in's, which outlives it.
    """
    async with db_session.SystemSessionLocal() as session:
        dropped = await identity_refs.drop_sector_refs(
            session,
            sector_guild_id=guild_id,
            sector_id=subscription_id,
            purpose=IdentityPurpose.webhook,
        )
        await session.commit()
    return dropped
