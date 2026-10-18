"""The values an installed plug-in keeps in Initiative.

An install keeps values by key, on the items it can read and on itself
(``plugin_metadata``). Every function here runs on the request's session,
routed as the install by the install seam, so the table's policies decide
which rows it reaches: its own, on an item it can read, with the read scope of
the item's tool. The checks here answer the same questions first, so a refusal
names its reason instead of surfacing as a policy violation.

A container plug-in writes its values through the installation API. A
declarative plug-in's are the changes its expressions answer, which
:func:`apply_changes` makes on a session of its own, routed as the install
through the same seam.

A value on an item is ``shown`` when the install's pinned version declares
its key as a field on the item's kind: whoever can read the item reads it
then, and it comes back with the item (:func:`annotate_plugin_values`). The
write sets it, and :func:`reconcile_shown` sets it again when the install
moves to another version.

The caps are the plug-in kit's (``metadataValueBytes`` and the rest), read
from the vendored contract.
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Collection,
    Iterable,
    Mapping,
    Optional,
    Sequence,
)

from sqlalchemy import Table, and_, delete, exists, false, or_, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import InstallAccessError, VerifiedInstall, establish_install_access
from app.core.messages import PluginChannelMessages, PluginMessages
from app.core.plugin_scopes import tool_resource
from app.core.tools import INSTALL_METADATA_KIND, ITEM_KINDS, KINDS
from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.guild_standing import GuildContext, InstallContext
from app.db.initiative_rls import governing_path
from app.db.request_context import SystemGuild
from app.db.session import (
    RLS_CONTEXT_MAX_AGE_SECONDS,
    guild_context,
    require_actor_context,
    set_rls_context,
)
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.plugin_metadata import LOOKUP_LENGTH, PluginMetadata
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.project import Project
from app.models.tenant.property import PropertyType
from app.models.tenant.task import Task
from app.schemas.query import FilterOp
from app.schemas.tenant.plugin_data import PluginValueSummary
from app.schemas.tenant.tool_layout import PLUGIN_FIELD_PREFIX
from app.services.marketplace import contract
from app.services.marketplace.expressions import UNDEFINED
from app.services.marketplace.manifest_values import is_metadata_key
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.tenant import guild_plugins, plugin_age
from app.services.tenant import properties as properties_service
from app.services.tenant.plugin_channels import PluginChannelError

__all__ = [
    "annotate_plugin_values",
    "apply_changes",
    "drop_for_items",
    "filter_clause",
    "filter_fields",
    "find",
    "forms",
    "read",
    "reconcile_shown",
    "shown_keys",
    "values_on",
    "write",
]

#: The most one value may take, as JSON.
VALUE_BYTES = contract.cap("metadataValueBytes")
#: What one install may keep on one item.
ITEM_KEYS = contract.cap("metadataKeysPerObject")
ITEM_BYTES = contract.cap("metadataBytesPerObject")
#: What an install may keep on itself.
INSTALL_KEYS = contract.cap("installMetadataKeys")
INSTALL_BYTES = contract.cap("installMetadataBytes")
#: The most items one read may name.
READ_IDS = 500
#: The most items one look-up answers.
FIND_LIMIT = 100
#: The most targeted changes one of a declarative plug-in's ``write``
#: expressions may answer.
WRITE_TARGETS = contract.cap("writeTargets")
#: How long one routing as the install serves a run of changes before it is
#: established again, well inside the age a routing may reach.
_REROUTE_SECONDS = RLS_CONTEXT_MAX_AGE_SECONDS / 2
#: The largest id an item's row holds: a change naming one past it names an
#: item that is not there.
_MAX_ITEM_ID = 2**31 - 1


def _table(kind: str) -> Table:
    return SQLModel.metadata.tables[KINDS[kind].table]


def _read_scope(kind: str) -> str:
    """The scope an install reads ``kind`` with: its tool's read scope."""
    governed = governing_path(KINDS[kind].table)
    assert governed is not None, kind
    return f"{tool_resource(governed[0]).value}:read"


def _check_key(key: str) -> None:
    if not is_metadata_key(key):
        raise PluginChannelError(PluginChannelMessages.METADATA_KEY_INVALID)


def _size(value: Any) -> int:
    """``value``'s size as compact JSON, in bytes."""
    return len(
        json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def _lookup(value: Any) -> Optional[str]:
    """The text a value is looked up by: a string, number or boolean of at most
    :data:`LOOKUP_LENGTH` characters, as JSON writes it (strings bare)."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (bool, int, float)):
        text = json.dumps(value)
    else:
        return None
    return text if len(text) <= LOOKUP_LENGTH else None


def _epoch(text: str) -> Optional[float]:
    """A date or datetime as seconds since the epoch: a date at midnight UTC,
    a datetime without a zone in UTC. ``None`` for any other text."""
    try:
        if len(text) == 10:
            day = date.fromisoformat(text)
            moment = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        else:
            moment = datetime.fromisoformat(text)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return moment.timestamp()


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def forms(value: Any) -> tuple[Optional[str], Optional[float]]:
    """What a value is compared by: its words and its number
    (:class:`~app.models.tenant.plugin_metadata.PluginMetadata`), from its
    shape alone, so a version that changes a field's kind needs no rewrite."""
    if isinstance(value, bool):
        return None, 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return None, _number(value)
    if isinstance(value, str):
        return (value or None), _epoch(value)
    if isinstance(value, dict):
        words = next(
            (
                value[name]
                for name in ("text", "url")
                if isinstance(value.get(name), str) and value[name]
            ),
            None,
        )
        part, whole = _number(value.get("value")), _number(value.get("max"))
        return words, part / whole if part is not None and whole else None
    return None, None


async def _readable(session: AsyncSession, kind: str, entity_id: int) -> bool:
    """Whether the routed install can read the item. Its table's policies
    decide, as they do for every read of it."""
    table = _table(kind)
    return bool(await session.scalar(exists().where(table.c.id == entity_id).select()))


def shown_keys(definition: Any, kind: str) -> frozenset[str]:
    """The keys a pinned definition declares as fields on ``kind``."""
    fields = definition.get("fields") if isinstance(definition, dict) else None
    return frozenset(
        field["key"]
        for field in (fields if isinstance(fields, list) else [])
        if isinstance(field, dict)
        and isinstance(field.get("key"), str)
        and kind in (field.get("on") or ())
    )


def _grouped(rows: Iterable[PluginMetadata]) -> dict[tuple[str, int], dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, Any]] = defaultdict(dict)
    for row in rows:
        grouped[(row.entity_type, row.entity_id)][row.key] = row.value
    return grouped


async def read(
    session: AsyncSession,
    context: InstallContext,
    kind: str,
    entity_ids: Sequence[int],
) -> list[tuple[str, int, dict[str, Any]]]:
    """The install's values on each item it can read, by item. An item holding
    none, or one it cannot read, is left out. For the install's own values,
    ``entity_ids`` is not read."""
    if kind == INSTALL_METADATA_KIND:
        entity_ids = [context.install_id]
    elif len(entity_ids) > READ_IDS:
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    if not entity_ids:
        return []
    rows = await session.exec(
        select(PluginMetadata).where(
            PluginMetadata.install_id == context.install_id,
            PluginMetadata.entity_type == kind,
            PluginMetadata.entity_id.in_(set(entity_ids)),
        )
    )
    grouped = _grouped(rows)
    return [
        (entity_type, entity_id, values)
        for (entity_type, entity_id), values in sorted(grouped.items())
    ]


async def write(
    session: AsyncSession,
    context: InstallContext,
    kind: str,
    entity_id: Optional[int],
    values: Mapping[str, Any],
    pinned: Callable[[], Awaitable[Any]],
    *,
    made: Optional[Callable[[dict[str, Any]], Awaitable[Mapping[str, Any]]]] = None,
) -> dict[str, Any]:
    """Write some of the install's values on one item, or on itself; a
    ``None`` removes its key. Answers every value it keeps there now.

    With ``made``, the values written are those it answers when given what
    the install holds there, by key, under the item's lock, so writes made at
    once each read what the one before left.

    ``pinned`` reads the install's pinned definition, whose fields on the
    item's kind say which values are shown; a value on the install itself is
    never shown, and its definition is not read.

    On an item, the install needs its tool's read scope and to be able to read
    it: the values are the install's own, and writing them changes nothing on
    the item. Nothing is written while the community's content is on hold.
    """
    if context.content_hold:
        raise PluginChannelError(PluginChannelMessages.GUILD_READ_ONLY, status_code=409)
    if kind == INSTALL_METADATA_KIND:
        entity_id = context.install_id
        max_keys, max_bytes = INSTALL_KEYS, INSTALL_BYTES
    else:
        if entity_id is None:
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
        if not context.holds(_read_scope(kind)):
            raise PluginChannelError(PluginMessages.SCOPE_REQUIRED, status_code=403)
        if not await _readable(session, kind, entity_id):
            raise PluginChannelError(
                PluginChannelMessages.METADATA_ITEM_NOT_FOUND, status_code=404
            )
        max_keys, max_bytes = ITEM_KEYS, ITEM_BYTES

    shown: Collection[str] = frozenset()
    if kind != INSTALL_METADATA_KIND:
        # Lock order: the install's fields lock (shared here), then the item's
        # lock. Holding the first while the definition is read, to the commit,
        # means a reconcile to a new definition (which takes it exclusively)
        # runs either before this read, which then sees the new definition,
        # or after this commit, and corrects what it wrote.
        await _lock_fields(session, context.guild_id, context.install_id, shared=True)
        shown = shown_keys(await pinned(), kind)

    # Writes to one item take turns, so the caps hold across them.
    await advisory_lock(
        session,
        LockNamespace.PLUGIN_METADATA,
        f"{context.guild_id}:{context.install_id}:{kind}:{entity_id}",
    )
    where = (
        PluginMetadata.install_id == context.install_id,
        PluginMetadata.entity_type == kind,
        PluginMetadata.entity_id == entity_id,
    )
    kept = {
        row.key: row.value
        for row in await session.exec(select(PluginMetadata).where(*where))
    }
    if made is not None:
        values = await made(dict(kept))
    # The keys an item ends up with are counted below; a write may remove every
    # key it holds and set as many again, and no more.
    if len(values) > 2 * max_keys:
        raise PluginChannelError(
            PluginChannelMessages.METADATA_LIMIT_REACHED, status_code=409
        )
    sizes: dict[str, int] = {}
    for key, value in values.items():
        _check_key(key)
        if value is not None:
            sizes[key] = _size(value)
            if sizes[key] > VALUE_BYTES:
                raise PluginChannelError(
                    PluginChannelMessages.METADATA_VALUE_TOO_LARGE, status_code=413
                )

    after = {key: value for key, value in kept.items() if key not in values}
    after.update({key: value for key, value in values.items() if value is not None})
    total = sum(
        sizes[key] if key in sizes else _size(value) for key, value in after.items()
    )
    if len(after) > max_keys or total > max_bytes:
        raise PluginChannelError(
            PluginChannelMessages.METADATA_LIMIT_REACHED, status_code=409
        )

    removed = [key for key, value in values.items() if value is None and key in kept]
    if removed:
        await session.exec(
            delete(PluginMetadata).where(
                *where,
                PluginMetadata.key.in_(removed),
            )
        )
    now = datetime.now(timezone.utc)
    written = []
    for key, value in values.items():
        if value is None:
            continue
        text_form, number_form = forms(value)
        written.append(
            {
                "install_id": context.install_id,
                "entity_type": kind,
                "entity_id": entity_id,
                "key": key,
                "value": value,
                "lookup": _lookup(value),
                "text_form": text_form,
                "number_form": number_form,
                "shown": key in shown,
                "updated_at": now,
            }
        )
    if written:
        statement = insert(PluginMetadata).values(written)
        await session.exec(
            statement.on_conflict_do_update(
                index_elements=["install_id", "entity_type", "entity_id", "key"],
                set_={
                    "value": statement.excluded.value,
                    "lookup": statement.excluded.lookup,
                    "text_form": statement.excluded.text_form,
                    "number_form": statement.excluded.number_form,
                    "shown": statement.excluded.shown,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )
    await session.commit()
    return after


async def find(
    session: AsyncSession, context: InstallContext, key: str, value: str
) -> list[tuple[str, int, dict[str, Any]]]:
    """The items the install can read holding ``value`` under ``key``, with
    the values it keeps on each: at most :data:`FIND_LIMIT`, in kind and id
    order. The install's own values are not an item."""
    _check_key(key)
    if len(value) > LOOKUP_LENGTH:
        return []
    matches = (
        await session.exec(
            select(PluginMetadata.entity_type, PluginMetadata.entity_id)
            .where(
                PluginMetadata.install_id == context.install_id,
                PluginMetadata.key == key,
                PluginMetadata.lookup == value,
                PluginMetadata.entity_type != INSTALL_METADATA_KIND,
            )
            .order_by(PluginMetadata.entity_type, PluginMetadata.entity_id)
            .limit(FIND_LIMIT)
        )
    ).all()
    if not matches:
        return []
    by_kind: dict[str, list[int]] = defaultdict(list)
    for entity_type, entity_id in matches:
        by_kind[entity_type].append(entity_id)
    rows = await session.exec(
        select(PluginMetadata).where(
            PluginMetadata.install_id == context.install_id,
            or_(
                *(
                    and_(
                        PluginMetadata.entity_type == entity_type,
                        PluginMetadata.entity_id.in_(ids),
                    )
                    for entity_type, ids in by_kind.items()
                )
            ),
        )
    )
    grouped = _grouped(rows)
    return [
        (entity_type, entity_id, grouped.get((entity_type, entity_id), {}))
        for entity_type, entity_id in matches
    ]


def _is_target(target: Any) -> bool:
    """Whether ``target`` is one of the contract's ``changeTarget`` shapes: an
    item, the install, or the items the install holds a value on."""
    if not isinstance(target, dict):
        return False
    if set(target) == {"kind", "id"}:
        kind, entity_id = target["kind"], target["id"]
        return (
            isinstance(kind, str)
            and kind in ITEM_KINDS
            and isinstance(entity_id, int)
            and not isinstance(entity_id, bool)
            and entity_id >= 1
        )
    if set(target) == {"install"}:
        return target["install"] is True
    holding = target.get("holding") if set(target) == {"holding"} else None
    return (
        isinstance(holding, dict)
        and set(holding) == {"key", "value"}
        and is_metadata_key(holding["key"])
        and isinstance(holding["value"], str)
        and len(holding["value"]) <= LOOKUP_LENGTH
    )


def _targeted(answer: Any) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """What a declarative plug-in's ``write`` answered, held to the contract's
    ``targetedChange``: a list of at most :data:`WRITE_TARGETS`, each a target
    and the values it sets, where a value is at most :data:`VALUE_BYTES` as
    JSON and a null removes its key. Nothing answered is no change. An answer
    that is not that is refused whole, before anything is written."""
    if answer is UNDEFINED:
        return []
    if not isinstance(answer, list) or len(answer) > WRITE_TARGETS:
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    changes: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for change in answer:
        if not (
            isinstance(change, dict)
            and set(change) == {"target", "set"}
            and _is_target(change["target"])
            and isinstance(change["set"], dict)
        ):
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
        for key, value in change["set"].items():
            _check_key(key)
            if value is not None and _size(value) > VALUE_BYTES:
                raise PluginChannelError(
                    PluginChannelMessages.METADATA_VALUE_TOO_LARGE, status_code=413
                )
        changes.append((change["target"], change["set"]))
    return changes


@asynccontextmanager
async def _as_install(
    plugin: GuildPlugin, registration: RegistrationSnapshot, guild_id: int
) -> AsyncIterator[
    tuple[
        AsyncSession,
        Callable[[], Awaitable[InstallContext]],
        Callable[[], Awaitable[Any]],
    ]
]:
    """A session of its own routed as the install, through the install seam
    with the scopes the install holds (:func:`guild_plugins.install_scopes`):
    the session, what routes it again, and what reads the install's pinned
    definition."""
    install = VerifiedInstall(
        guild_id=guild_id,
        install_id=int(plugin.id or 0),
        client_id=registration.public_id,
        scopes=guild_plugins.install_scopes(plugin, registration),
    )
    async with cohorts.request_sessionmaker(guild_id)() as session:

        async def route() -> InstallContext:
            try:
                return await establish_install_access(session, install)
            except InstallAccessError as exc:
                raise PluginChannelError(
                    PluginChannelMessages.INSTALL_NOT_FOUND, status_code=404
                ) from exc

        async def pinned() -> Any:
            return await session.scalar(
                select(GuildPlugin.definition).where(
                    GuildPlugin.id == install.install_id
                )
            )

        yield session, route, pinned


async def apply_changes(
    plugin: GuildPlugin,
    registration: RegistrationSnapshot,
    answer: Any,
    *,
    guild_id: int,
) -> None:
    """Make the changes a declarative plug-in's ``write`` answered, as its
    install, on a session of its own routed through the install seam with the
    scopes the install holds (:func:`guild_plugins.install_scopes`).

    ``answer`` is held to the contract first (:func:`_targeted`). Each target
    is then found as the install: one item, the install itself, or every item
    the install holds a value on, at most :data:`FIND_LIMIT` (:func:`find`).
    An item more than one change reaches is written once, with the later
    change's values over the earlier's, which is what writing them in turn
    leaves. Each item is written by :func:`write`, under its checks, caps and
    locks, and committed; one the install cannot read, or that is not there,
    is skipped.

    Raises :class:`PluginChannelError` for an answer that is not targeted
    changes, an install that may not act, and a write refused for any other
    reason. The items written before a refusal keep what was written: every
    change sets values, so making the same changes again leaves the same
    values.
    """
    changes = _targeted(answer)
    if not changes:
        return
    async with _as_install(plugin, registration, guild_id) as (session, route, pinned):
        context = await route()
        routed = time.monotonic()
        targets: dict[tuple[str, int], dict[str, Any]] = {}
        for target, values in changes:
            if "holding" in target:
                found = [
                    (kind, entity_id)
                    for kind, entity_id, _ in await find(
                        session,
                        context,
                        target["holding"]["key"],
                        target["holding"]["value"],
                    )
                ]
            elif "install" in target:
                found = [(INSTALL_METADATA_KIND, context.install_id)]
            elif target["id"] <= _MAX_ITEM_ID:
                found = [(target["kind"], target["id"])]
            else:
                found = []
            for item in found:
                targets.setdefault(item, {}).update(values)

        for (kind, entity_id), values in targets.items():
            if time.monotonic() - routed > _REROUTE_SECONDS:
                context = await route()
                routed = time.monotonic()
            try:
                await write(session, context, kind, entity_id, values, pinned)
            except PluginChannelError as exc:
                if exc.code not in (
                    PluginMessages.SCOPE_REQUIRED,
                    PluginChannelMessages.METADATA_ITEM_NOT_FOUND,
                ):
                    raise


async def change_item(
    plugin: GuildPlugin,
    registration: RegistrationSnapshot,
    kind: str,
    entity_id: int,
    made: Callable[[dict[str, Any]], Awaitable[Any]],
    *,
    guild_id: int,
) -> None:
    """Make the change ``made`` answers on one item, as :func:`apply_changes`
    makes a change, from what the install holds there: ``made`` is given those
    values, by key, under the item's lock (:func:`write`), so changes made at
    once each start from what the one before left. It answers one change,
    held to the contract's ``change``, or ``None`` for none. An item the
    install cannot read, or that is not there, is refused rather than
    skipped."""

    async def values(held: dict[str, Any]) -> Mapping[str, Any]:
        answer = await made(held)
        if answer is None:
            return {}
        ((_, changed),) = _targeted(
            [{**answer, "target": {"kind": kind, "id": entity_id}}]
        )
        return changed

    async with _as_install(plugin, registration, guild_id) as (session, route, pinned):
        await write(session, await route(), kind, entity_id, {}, pinned, made=values)


async def drop_for_items(
    session: AsyncSession, kind: str, entity_ids: Iterable[int]
) -> None:
    """Remove every install's values on these items, as they are purged."""
    ids = list(entity_ids)
    if ids:
        await session.exec(
            delete(PluginMetadata).where(
                PluginMetadata.entity_type == kind,
                PluginMetadata.entity_id.in_(ids),
            )
        )


async def _lock_fields(
    session: AsyncSession, guild_id: int, install_id: int, *, shared: bool
) -> None:
    """The lock that orders reading an install's pinned definition for a write
    against reconciling its values to a new one."""
    await advisory_lock(
        session, LockNamespace.PLUGIN_FIELDS, f"{guild_id}:{install_id}", shared=shared
    )


async def reconcile_shown(
    guild_id: int, install_id: int, *, session: Optional[AsyncSession] = None
) -> None:
    """Show the install's values on items exactly where its pinned definition
    declares their keys as fields, after it moves to another version. Only the
    rows whose answer changes are written.

    The definition is read once no write is between reading it and committing
    (:func:`write`), so what a write read before the move is corrected here.

    ``session`` is the community's system session, routed, whose caller
    commits; without one the rows are written and committed on a system
    session of their own."""
    if session is None:
        async with cohorts.system_session(guild_id) as own:
            await set_rls_context(own, SystemGuild(guild_id))
            await reconcile_shown(guild_id, install_id, session=own)
            await own.commit()
        return
    await _lock_fields(session, guild_id, install_id, shared=False)
    definition = await session.scalar(
        select(GuildPlugin.definition).where(GuildPlugin.id == install_id)
    )
    declared = {kind: shown_keys(definition, kind) for kind in ITEM_KINDS}
    shown = or_(
        false(),
        *(
            and_(PluginMetadata.entity_type == kind, PluginMetadata.key.in_(keys))
            for kind, keys in declared.items()
            if keys
        ),
    )
    await session.exec(
        update(PluginMetadata)
        .where(
            PluginMetadata.install_id == install_id,
            PluginMetadata.entity_type != INSTALL_METADATA_KIND,
            PluginMetadata.shown.is_distinct_from(shown),
        )
        .values(shown=shown)
    )


class _Offered:
    """Whether a reader is drawn an install's values in an initiative: it is
    placed there with a role the reader holds (or the reader is the
    community's admin), and the reader is old enough for it. Each pair is
    decided once, and the reader's age read only if a plug-in asks for one."""

    def __init__(self, context: GuildContext) -> None:
        self._context = context
        self._viewer: Optional[plugin_age.AgeViewer] = None
        self._known: dict[tuple[int, int], bool] = {}

    async def __call__(
        self, install_id: int, initiative_id: int, roles: Any, minimum: Any
    ) -> bool:
        if (install_id, initiative_id) not in self._known:
            old_enough = True
            if minimum is not None:
                self._viewer = self._viewer or await plugin_age.current_viewer(
                    self._context.user_id
                )
                old_enough = plugin_age.age_allows(
                    {"minimum_age": minimum}, self._viewer
                )
            self._known[(install_id, initiative_id)] = (
                guild_plugins.surface_access(
                    guild_plugins.ITEM_SURFACE,
                    initiative_id=initiative_id,
                    placement_role_ids=list(roles or ()),
                    is_guild_admin=self._context.is_admin,
                    member_role_ids=self._context.member_role_ids,
                    age_allows=old_enough,
                )
                is guild_plugins.SurfaceAccess.open
            )
        return self._known[(install_id, initiative_id)]


@dataclass(frozen=True)
class FilterField:
    """A plug-in field a reader may filter tasks by: its kind, and the
    initiatives where they are drawn it."""

    install_id: int
    key: str
    kind: str
    initiatives: frozenset[int]


async def filter_fields(
    session: AsyncSession, field_ids: Collection[str]
) -> dict[str, FilterField]:
    """Of these ``plugin:<install>:<key>`` ids, the fields the reader may filter
    tasks by: those declared on tasks by an install that is on, where
    :func:`annotate_plugin_values` would draw them. A filter on any other
    narrows nothing, so it tells nobody which tasks hold a value they are not
    drawn. An installed plug-in and a guest are drawn none."""
    context = guild_context(session)
    wanted: dict[tuple[int, str], str] = {}
    for field_id in field_ids:
        install, _, key = field_id.removeprefix(PLUGIN_FIELD_PREFIX).partition(":")
        if field_id.startswith(PLUGIN_FIELD_PREFIX) and install.isdigit() and key:
            wanted[(int(install), key)] = field_id
    if not wanted or context is None or context.guest:
        return {}
    rows = await session.exec(
        select(
            GuildPlugin.id,
            GuildPlugin.definition,
            PluginPlacement.initiative_id,
            PluginPlacement.role_ids,
        )
        .join(PluginPlacement, PluginPlacement.install_id == GuildPlugin.id)
        .where(
            GuildPlugin.enabled.is_(True),
            col(GuildPlugin.id).in_(sorted({install for install, _ in wanted})),
        )
    )
    offered = _Offered(context)
    reach: dict[tuple[int, str], set[int]] = defaultdict(set)
    kinds: dict[tuple[int, str], str] = {}
    for install_id, definition, initiative_id, roles in rows.all():
        declared = definition.get("fields") if isinstance(definition, dict) else None
        for field in declared if isinstance(declared, list) else ():
            if not isinstance(field, dict) or "task" not in (field.get("on") or ()):
                continue
            pair = (install_id, str(field.get("key")))
            if pair not in wanted:
                continue
            kinds[pair] = str(field.get("kind"))
            if await offered(
                install_id, initiative_id, roles, definition.get("minimum_age")
            ):
                reach[pair].add(initiative_id)
    return {
        wanted[pair]: FilterField(pair[0], pair[1], kinds[pair], frozenset(found))
        for pair, found in reach.items()
    }


#: The kinds a filter compares by their words; every other by its number.
_COMPARED_AS_TEXT = frozenset({"text", "link", "badge"})


def filter_clause(field: FilterField, op: FilterOp, value: Any) -> Any:
    """A task list's condition on one plug-in field: one probe of the task's
    row by its key, on a task in an initiative where the reader is drawn the
    field. ``None`` when the value cannot be compared."""
    as_text = field.kind in _COMPARED_AS_TEXT
    form = PluginMetadata.text_form if as_text else PluginMetadata.number_form

    def held(*where: Any) -> Any:
        return and_(
            exists().where(
                PluginMetadata.install_id == field.install_id,
                PluginMetadata.entity_type == "task",
                PluginMetadata.entity_id == Task.id,
                PluginMetadata.key == field.key,
                PluginMetadata.shown.is_(True),
                *where,
            ),
            col(Task.project_id).in_(
                select(Project.id).where(
                    col(Project.initiative_id).in_(sorted(field.initiatives))
                )
            ),
        )

    if op == FilterOp.is_null:
        try:
            empty = (
                value
                if isinstance(value, bool)
                else properties_service.normalize_is_null_value(value)
            )
        except ValueError:
            return None
        present = held(form.is_not(None))
        return ~present if empty else present
    if as_text:
        compared, by = value, PropertyType.text
    else:
        compared, by = _compared_number(value), PropertyType.number
    predicate = properties_service.build_property_value_predicate(
        form, by, op, compared
    )
    return None if predicate is None else held(predicate)


def _compared_number(value: Any) -> Any:
    """A filter's value as its field's values are kept: a date or datetime as
    seconds since the epoch, a checkbox as 1 or 0."""
    if isinstance(value, list):
        return [_compared_number(each) for each in value]
    return forms(value)[1] if isinstance(value, (bool, str)) else value


async def annotate_plugin_values(session: AsyncSession, tasks: Sequence[Task]) -> None:
    """Set ``.plugin_values`` on every task (:func:`values_on`). Each task's
    project is loaded."""
    found = await values_on(
        session,
        "task",
        {
            task.id: task.project.initiative_id
            for task in tasks
            if task.id is not None and task.project is not None
        },
    )
    for task in tasks:
        object.__setattr__(task, "plugin_values", found.get(task.id or 0, []))


async def values_on(
    session: AsyncSession, kind: str, initiatives: Mapping[int, Optional[int]]
) -> dict[int, list[PluginValueSummary]]:
    """The shown values on items of one kind, by item id, given each item's
    initiative: those of the installs whose actions the reader could run there
    — on, placed in the item's initiative with a role the reader holds (or the
    reader its admin), and the reader old enough for the plug-in
    (``guild_plugins.surface_access``). One query for the page.

    ``session`` is the reader's, so which values it reads is the table's
    policies' answer; which installs' values are drawn is decided here. An
    item no initiative holds is drawn none, nor is an installed plug-in reading
    items: it reads its own values through its metadata routes. Nor is a
    guest, who runs no plug-in."""
    context = require_actor_context(session)
    initiatives = {
        item: initiative
        for item, initiative in initiatives.items()
        if initiative is not None
    }
    found: dict[int, list[PluginValueSummary]] = defaultdict(list)
    if initiatives and isinstance(context, GuildContext) and not context.guest:
        rows = await session.exec(
            select(
                PluginMetadata.entity_id,
                PluginMetadata.install_id,
                PluginMetadata.key,
                PluginMetadata.value,
                PluginPlacement.initiative_id,
                PluginPlacement.role_ids,
                GuildPlugin.definition["minimum_age"],
            )
            .join(GuildPlugin, GuildPlugin.id == PluginMetadata.install_id)
            .join(
                PluginPlacement,
                PluginPlacement.install_id == PluginMetadata.install_id,
            )
            .where(
                PluginMetadata.entity_type == kind,
                PluginMetadata.shown.is_(True),
                GuildPlugin.enabled.is_(True),
                tuple_(PluginMetadata.entity_id, PluginPlacement.initiative_id).in_(
                    list(initiatives.items())
                ),
            )
            .order_by(PluginMetadata.install_id, PluginMetadata.key)
        )
        offered = _Offered(context)
        for item_id, install_id, key, value, initiative_id, roles, minimum in rows:
            if await offered(install_id, initiative_id, roles, minimum):
                found[item_id].append(
                    PluginValueSummary(plugin_id=install_id, key=key, value=value)
                )
    return found
