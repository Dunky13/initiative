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

Beside it, ``public.plugin_install_claims`` holds the values each install has
claimed for its plug-in's unique settings, current and earlier, so no two
communities hold the same one. A value is claimed here first
(:func:`claim_assigned`, :func:`claim_setting`) and then stored on the install,
and given back (:func:`release_setting`) when it could not be. Claims go with
the install's row (:func:`forget`).

Every call runs on the system engine, which alone reaches the tables.
"""

from __future__ import annotations

import logging
import secrets
import string
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from cryptography.fernet import InvalidToken
from sqlalchemy import delete, func, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

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
    PluginInstallClaim,
)
from app.models.platform.plugin_service_registration import PluginServiceRegistration
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild, CommunityStatus
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace.manifest_values import (
    MAX_UNIQUE_SETTING_VALUE_LENGTH,
    MIN_UNIQUE_SETTING_VALUE_LENGTH,
    UNIQUE_SETTING_VALUE_CHARS,
)
from app.services.tenant.plugin_config import REMOVED_AT, connection_by_id

logger = logging.getLogger(__name__)

__all__ = [
    "PAGE_LIMIT",
    "IndexedInstall",
    "SettingClaim",
    "claim",
    "claim_assigned",
    "claim_setting",
    "forget",
    "hook_route",
    "page",
    "record",
    "release_setting",
    "routed",
]

#: The most installs one page lists.
PAGE_LIMIT = 200

#: What a random suffix is drawn from: the letters and digits a unique
#: setting's value may hold.
_SUFFIX_CHARACTERS = "".join(sorted(UNIQUE_SETTING_VALUE_CHARS))
#: How long a random suffix is, from its first tries to its last, and how many
#: tries each length gets.
_SUFFIX_LENGTHS = (2, 3, 4)
_TRIES_PER_LENGTH = 3
#: How many random letters stand in for a name that gives too few of its own.
_RANDOM_NAME_LENGTH = 4


@dataclass(frozen=True)
class IndexedInstall:
    guild_id: int
    install_id: int
    #: Switched on, in a community in use.
    active: bool
    #: The route value it was found by, for :func:`routed`.
    route: Optional[str] = None


def hook_route(
    definition: Optional[dict[str, Any]], config: Optional[Mapping[str, Any]]
) -> Optional[str]:
    """The value an install's vendor webhooks are routed by: in its stored
    ``config``, the field of the static connection the ``webhooks.route`` of
    its pinned ``definition`` names. None while that connection holds the
    vendor's report that it was removed (``REMOVED_AT``).

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
    if not isinstance(stored, dict) or REMOVED_AT in stored:
        return None
    value = stored.get(route.get("field"))
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return text if text and len(text) <= HOOK_ROUTE_MAX_LENGTH else None


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
    if not await claim(guild_id, plugin, hook_route(plugin.definition, plugin.config)):
        logger.info(
            "plug-in installs: install %s in guild %s routes by a value another "
            "community holds, and is indexed without it",
            plugin.id,
            guild_id,
        )
        await claim(guild_id, plugin, None)


async def forget(guild_id: int, install_id: int) -> None:
    """Remove one install's row, and with it the values it claimed."""
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
        IndexedInstall(
            guild_id=row[0], install_id=row[1], active=True, route=route_value
        )
        for row in rows
    ]


# --- claims on unique settings -------------------------------------------------


@dataclass(frozen=True)
class SettingClaim:
    """A value an install claimed for one of its unique settings."""

    key: str
    value: str
    #: The install held it already, as an earlier value, so giving the claim
    #: back keeps it.
    held: bool


def _random(alphabet: str, length: int) -> str:
    """``length`` characters drawn from ``alphabet``."""
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _name_value(name: str) -> str:
    """A unique setting's value from a community's name: its letters and
    digits, without accents, in lowercase, from its first letter, cut to fit;
    random letters when that leaves fewer than two."""
    folded = unicodedata.normalize("NFKD", name.casefold())
    kept = "".join(
        character for character in folded if character in UNIQUE_SETTING_VALUE_CHARS
    ).lstrip(string.digits)[:MAX_UNIQUE_SETTING_VALUE_LENGTH]
    if len(kept) < MIN_UNIQUE_SETTING_VALUE_LENGTH:
        return _random(string.ascii_lowercase, _RANDOM_NAME_LENGTH)
    return kept


def _candidates(base: str) -> Iterator[str]:
    """``base``, then ``base`` cut to make room for a random suffix of letters
    and digits, longer after every few tries. Never a counter."""
    yield base
    for length in _SUFFIX_LENGTHS:
        for _ in range(_TRIES_PER_LENGTH):
            yield base[: MAX_UNIQUE_SETTING_VALUE_LENGTH - length] + _random(
                _SUFFIX_CHARACTERS, length
            )


async def _make_current(
    session: AsyncSession,
    guild_id: int,
    install_id: int,
    key: str,
    value: Optional[str],
) -> None:
    """Mark ``value`` the one the install holds now for ``key``, and every other
    value it claimed for ``key`` an earlier one; ``None`` marks them all
    earlier."""
    current = PluginInstallClaim.value == value
    await session.exec(
        update(PluginInstallClaim)
        .where(
            col(PluginInstallClaim.guild_id) == guild_id,
            col(PluginInstallClaim.install_id) == install_id,
            col(PluginInstallClaim.key) == key,
            col(PluginInstallClaim.current).is_distinct_from(current),
        )
        .values(current=current)
    )


async def _claim_setting(
    session: AsyncSession, guild_id: int, plugin: GuildPlugin, key: str, value: str
) -> Optional[SettingClaim]:
    """Claim ``value`` for the install's setting ``key`` and mark it the one it
    holds now, or ``None`` while another install of the plug-in holds it."""
    inserted = (
        await session.exec(
            pg_insert(PluginInstallClaim)
            .values(
                guild_id=guild_id,
                install_id=plugin.id,
                key=key,
                value=value,
                listing_uid=plugin.listing_uid,
                current=True,
                claimed_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing()
            .returning(PluginInstallClaim.value)
        )
    ).first()
    if inserted is None:
        holder = (
            await session.exec(
                select(
                    PluginInstallClaim.guild_id, PluginInstallClaim.install_id
                ).where(
                    PluginInstallClaim.listing_uid == plugin.listing_uid,
                    PluginInstallClaim.key == key,
                    func.lower(PluginInstallClaim.value) == value.lower(),
                )
            )
        ).first()
        if holder is None or tuple(holder) != (guild_id, plugin.id):
            return None
    await _make_current(session, guild_id, plugin.id, key, value)
    return SettingClaim(key=key, value=value, held=inserted is None)


async def claim_setting(
    guild_id: int, plugin: GuildPlugin, key: str, value: str
) -> Optional[SettingClaim]:
    """Claim ``value`` for the install's unique setting ``key``, as the one it
    holds now. ``None`` while another install of the plug-in holds it, now or
    as an earlier value."""
    async with db_session.SystemSessionLocal() as session:
        claimed = await _claim_setting(session, guild_id, plugin, key, value)
        await session.commit()
    return claimed


async def claim_assigned(
    guild_id: int, plugin: GuildPlugin, keys: Sequence[str]
) -> list[SettingClaim]:
    """Claim a value for each of the install's unique settings ``keys``: the
    community's name (:func:`_name_value`), or that with a short random suffix
    while another install holds it. A key that no value is claimed for in a few
    tries is left out, and stays without one."""
    async with db_session.SystemSessionLocal() as session:
        name = (
            await session.exec(select(Guild.name).where(Guild.id == guild_id))
        ).first()
        base = _name_value(name or "")
        claimed: list[SettingClaim] = []
        for key in keys:
            for value in _candidates(base):
                one = await _claim_setting(session, guild_id, plugin, key, value)
                if one is not None:
                    claimed.append(one)
                    break
            else:
                logger.warning(
                    "plug-in settings: no value could be claimed for %s of install "
                    "%s in guild %s",
                    key,
                    plugin.id,
                    guild_id,
                )
        await session.commit()
    return claimed


async def release_setting(
    guild_id: int, install_id: int, claimed: SettingClaim, *, current: Optional[str]
) -> None:
    """Give back a claim the install could not store: its value is forgotten
    unless the install held it already, and ``current``, the value the install
    still holds, is its current one again."""
    async with db_session.SystemSessionLocal() as session:
        if not claimed.held:
            await session.exec(
                delete(PluginInstallClaim).where(
                    col(PluginInstallClaim.guild_id) == guild_id,
                    col(PluginInstallClaim.install_id) == install_id,
                    col(PluginInstallClaim.key) == claimed.key,
                    col(PluginInstallClaim.value) == claimed.value,
                )
            )
        await _make_current(session, guild_id, install_id, claimed.key, current)
        await session.commit()
