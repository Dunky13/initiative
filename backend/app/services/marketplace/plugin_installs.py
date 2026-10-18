"""The install index: which communities hold which plug-in, without visiting them.

``public.plugin_installs`` mirrors three facts of each community's ``guild_plugins``
rows: the listing an install came from, whether it is switched on, and the
value its plug-in's vendor webhooks are routed to it by (``hook_route``). It is
written wherever those facts change — at install and uninstall, when the plug-in
is switched on or off, and when the routed static connection's value is stored,
removed, or reported removed by the vendor — and read by two things:

* :func:`page`, the plug-in's own listing of its installs, a keyset page at a
  time;
* :func:`routed`, the installs a vendor delivery belongs to.

A route is held by one community unless the listing's registration shares
routes (``shared_routes``): each row's ``exclusive`` is the negation of it, and
a unique index holds an exclusive route to one row. A connect claims its route
(:func:`claim`) before it stores the value.

Every call runs on the system engine, which alone reaches the table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from cryptography.fernet import InvalidToken
from sqlalchemy import delete, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.encryption import (
    SALT_PLUGIN_INSTALLS_CURSOR,
    decrypt_field,
    encrypt_field,
)
from app.db import session as db_session
from app.db.errors import dbapi_constraint
from app.models.platform.plugin_install import (
    EXCLUSIVE_ROUTE_INDEX,
    HOOK_ROUTE_MAX_LENGTH,
    PluginInstall,
)
from app.models.platform.plugin_service_registration import PluginServiceRegistration
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild, CommunityStatus
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.tenant.plugin_config import connection_by_id

logger = logging.getLogger(__name__)

__all__ = [
    "PAGE_LIMIT",
    "IndexedInstall",
    "claim",
    "forget",
    "hook_route",
    "page",
    "record",
    "route_of",
    "routed",
]

#: The most installs one page lists.
PAGE_LIMIT = 200


@dataclass(frozen=True)
class IndexedInstall:
    guild_id: int
    install_id: int
    #: Switched on, in a community in use.
    active: bool


def route_of(
    definition: Optional[dict[str, Any]], config: Optional[Mapping[str, Any]]
) -> Optional[str]:
    """The value vendor webhooks route by in an install's stored ``config``:
    the field of the static connection the ``webhooks.route`` of
    ``definition`` names.

    Only a managed field routes: its value comes from the plug-in's
    ``after_connect`` hook, which checked it at the vendor, and never from a
    form."""
    route = ((definition or {}).get("webhooks") or {}).get("route")
    if not isinstance(route, dict):
        return None
    connection = connection_by_id(definition, route.get("connection"))
    managed = {
        field.get("key")
        for field in (connection or {}).get("fields") or []
        if isinstance(field, dict) and field.get("managed") is True
    }
    if route.get("field") not in managed:
        return None
    stored = (config or {}).get(route.get("connection")) or {}
    value = stored.get(route.get("field")) if isinstance(stored, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return text if text and len(text) <= HOOK_ROUTE_MAX_LENGTH else None


def hook_route(plugin: GuildPlugin) -> Optional[str]:
    """The value this install's vendor webhooks are routed by, as its pinned
    definition reads it (:func:`route_of`). None once the vendor has reported
    the routed connection ``removed``, which ``set_connection_state`` records
    as the install's configuration state."""
    route = ((plugin.definition or {}).get("webhooks") or {}).get("route")
    connection = route.get("connection") if isinstance(route, dict) else None
    removed = ("invalid", f"{connection}_removed")
    if (plugin.config_state, plugin.config_state_detail) == removed:
        return None
    return route_of(plugin.definition, plugin.config)


async def claim(guild_id: int, plugin: GuildPlugin, route: Optional[str]) -> bool:
    """Write one install's row as ``plugin`` stands, routed by ``route``.

    False, writing nothing, when the route is held for another community's
    install. Whether this install's route is its own alone follows its
    registration's ``shared_routes``, read under a share lock, so a change to
    the setting waits for this write and this write for the change."""
    if not plugin.listing_uid or plugin.id is None:
        return True
    async with db_session.SystemSessionLocal() as session:
        shared = (
            await session.exec(
                select(PluginServiceRegistration.shared_routes)
                .where(PluginServiceRegistration.listing_uid == plugin.listing_uid)
                .with_for_update(read=True)
            )
        ).all()
        values = {
            "listing_uid": plugin.listing_uid,
            "enabled": bool(plugin.enabled),
            "hook_route": route,
            "exclusive": not (shared and all(shared)),
        }
        try:
            await session.exec(
                pg_insert(PluginInstall)
                .values(guild_id=guild_id, install_id=plugin.id, **values)
                .on_conflict_do_update(
                    index_elements=[PluginInstall.guild_id, PluginInstall.install_id],
                    set_=values,
                )
            )
            await session.commit()
        except IntegrityError as exc:
            if dbapi_constraint(exc) != EXCLUSIVE_ROUTE_INDEX:
                raise
            await session.rollback()
            return False
    return True


async def record(guild_id: int, plugin: GuildPlugin) -> None:
    """Write one install's row as ``plugin`` now stands. A route held for
    another community is left out: the row is written with none."""
    if not await claim(guild_id, plugin, hook_route(plugin)):
        logger.info(
            "plug-in installs: install %s in guild %s routes by a value another "
            "community holds, and is indexed without it",
            plugin.id,
            guild_id,
        )
        await claim(guild_id, plugin, None)


async def forget(guild_id: int, install_id: int) -> None:
    """Remove one install's row."""
    async with db_session.SystemSessionLocal() as session:
        await session.exec(
            delete(PluginInstall).where(
                PluginInstall.guild_id == guild_id,
                PluginInstall.install_id == install_id,
            )
        )
        await session.commit()


def _encode_cursor(entry: IndexedInstall) -> str:
    """Where a page ended, sealed: the plug-in never sees our ids."""
    return encrypt_field(
        f"{entry.guild_id}:{entry.install_id}", SALT_PLUGIN_INSTALLS_CURSOR
    )


def _decode_cursor(cursor: Optional[str]) -> Optional[tuple[int, int]]:
    """A cursor that does not open starts the list again."""
    if not cursor:
        return None
    try:
        guild, _, install = decrypt_field(
            cursor, SALT_PLUGIN_INSTALLS_CURSOR
        ).partition(":")
        return int(guild), int(install)
    except (InvalidToken, ValueError):
        return None


async def page(
    listing_uid: str, *, cursor: Optional[str], limit: int
) -> tuple[list[IndexedInstall], Optional[str]]:
    """One page of a listing's installs, in (community, install) order, and
    the cursor for the next page, or ``None`` at the end."""
    statement = (
        select(
            PluginInstall.guild_id,
            PluginInstall.install_id,
            (
                PluginInstall.enabled.is_(True)
                & Guild.status.in_(sorted(LIVE_STATUS_VALUES))
            ).label("active"),
        )
        .join(Guild, Guild.id == PluginInstall.guild_id)
        .where(PluginInstall.listing_uid == listing_uid)
        .order_by(PluginInstall.guild_id, PluginInstall.install_id)
        .limit(limit + 1)
    )
    after = _decode_cursor(cursor)
    if after is not None:
        statement = statement.where(
            tuple_(PluginInstall.guild_id, PluginInstall.install_id) > tuple_(*after)
        )
    async with db_session.SystemSessionLocal() as session:
        rows = (await session.exec(statement)).all()
    entries = [
        IndexedInstall(guild_id=row[0], install_id=row[1], active=bool(row[2]))
        for row in rows
    ]
    if len(entries) <= limit:
        return entries, None
    return entries[:limit], _encode_cursor(entries[limit - 1])


async def routed(listing_uid: str, route_value: str) -> list[IndexedInstall]:
    """The installs of a listing whose webhooks route by ``route_value``, one
    per community that connected it: switched on, in a community open to
    writes."""
    statement = (
        select(PluginInstall.guild_id, PluginInstall.install_id)
        .join(Guild, Guild.id == PluginInstall.guild_id)
        .where(
            PluginInstall.listing_uid == listing_uid,
            PluginInstall.hook_route == route_value,
            PluginInstall.enabled.is_(True),
            Guild.status == CommunityStatus.active.value,
        )
        .order_by(PluginInstall.guild_id)
    )
    async with db_session.SystemSessionLocal() as session:
        rows = (await session.exec(statement)).all()
    return [
        IndexedInstall(guild_id=row[0], install_id=row[1], active=True) for row in rows
    ]
