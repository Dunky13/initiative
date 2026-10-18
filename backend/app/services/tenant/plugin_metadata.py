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

A key the pinned version declares as a list field on the item's kind holds a
list of elements, a row each, which a change adds to, merges into and takes
from by their refs (:func:`write`). Every read answers the list as an array,
newest first (:func:`assembled`).

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
from app.services.marketplace.manifest_values import is_identifier, is_metadata_key
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.tenant import guild_plugins, plugin_age
from app.services.tenant import properties as properties_service
from app.services.tenant.plugin_channels import PluginChannelError

__all__ = [
    "Change",
    "annotate_plugin_values",
    "apply_changes",
    "assembled",
    "change",
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
#: Rows one statement writes, within the parameters a statement may bind.
_WRITE_BATCH = 1000
#: How a list's elements are read: newest first, then by ref.
NEWEST_FIRST = (
    col(PluginMetadata.updated_at).desc(),
    col(PluginMetadata.ref).collate("C"),
)
#: The tones a list's element may take.
_TONES = contract.enum("tone")


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
    shape alone, so a version that changes a field's kind needs no rewrite. A
    list's element, and a value kept beside its state, is compared by its own
    ``value`` unless it is a progress bar's."""
    if isinstance(value, bool):
        return None, 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return None, _number(value)
    if isinstance(value, str):
        return (value or None), _epoch(value)
    if isinstance(value, dict):
        held = value.get("value")
        if "max" not in value and isinstance(held, (str, int, float)):
            return forms(held)
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


def _fields_on(definition: Any, kind: str) -> list[dict[str, Any]]:
    """The fields a pinned definition declares on ``kind``."""
    fields = definition.get("fields") if isinstance(definition, dict) else None
    return [
        field
        for field in (fields if isinstance(fields, list) else [])
        if isinstance(field, dict)
        and isinstance(field.get("key"), str)
        and kind in (field.get("on") or ())
    ]


def shown_keys(definition: Any, kind: str) -> frozenset[str]:
    """The keys a pinned definition declares as fields on ``kind``."""
    return frozenset(field["key"] for field in _fields_on(definition, kind))


def _list_keys(definition: Any, kind: str) -> frozenset[str]:
    """The keys a pinned definition declares as list fields on ``kind``."""
    return frozenset(
        field["key"]
        for field in _fields_on(definition, kind)
        if field.get("list") is True
    )


def assembled(rows: Iterable[tuple[str, str, Any]]) -> dict[str, Any]:
    """Values by key, from ``(key, ref, value)`` rows read
    :data:`NEWEST_FIRST`: a value as it is kept, and a list's elements as an
    array in the rows' order."""
    values: dict[str, Any] = {}
    lists: set[str] = set()
    for key, ref, value in rows:
        if ref:
            if key not in lists:
                lists.add(key)
                values[key] = []
            values[key].append(value)
        elif key not in lists:
            values[key] = value
    return values


def _grouped(rows: Iterable[PluginMetadata]) -> dict[tuple[str, int], dict[str, Any]]:
    """Each item's values (:func:`assembled`), from its rows read
    :data:`NEWEST_FIRST`."""
    held: dict[tuple[str, int], list[tuple[str, str, Any]]] = defaultdict(list)
    for row in rows:
        held[(row.entity_type, row.entity_id)].append((row.key, row.ref, row.value))
    return {item: assembled(values) for item, values in held.items()}


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
        select(PluginMetadata)
        .where(
            PluginMetadata.install_id == context.install_id,
            PluginMetadata.entity_type == kind,
            PluginMetadata.entity_id.in_(set(entity_ids)),
        )
        .order_by(*NEWEST_FIRST)
    )
    grouped = _grouped(rows)
    return [
        (entity_type, entity_id, values)
        for (entity_type, entity_id), values in sorted(grouped.items())
    ]


def _is_ref(value: Any) -> bool:
    """Whether ``value`` is a list element's ``ref``: 1 to
    :data:`LOOKUP_LENGTH` characters."""
    return isinstance(value, str) and 0 < len(value) <= LOOKUP_LENGTH


#: What a list's element may hold, and what each takes (the contract's
#: ``listElement``).
_ELEMENT_TERMS: dict[str, Callable[[Any], bool]] = {
    "ref": _is_ref,
    "value": lambda value: isinstance(value, (str, int, float)),
    "url": lambda value: isinstance(value, str),
    "text": lambda value: isinstance(value, str),
    "tone": lambda value: isinstance(value, str) and value in _TONES,
    "max": lambda value: (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ),
    "state": lambda value: (
        isinstance(value, dict)
        and all(
            is_identifier(facet) and is_identifier(key) for facet, key in value.items()
        )
    ),
}


def _is_element(value: Any) -> bool:
    """Whether ``value`` is one element of a list field's value: an object with
    a ``ref``, holding only :data:`_ELEMENT_TERMS`, each what it takes."""
    return (
        isinstance(value, dict)
        and "ref" in value
        and all(
            name in _ELEMENT_TERMS and _ELEMENT_TERMS[name](held)
            for name, held in value.items()
        )
    )


@dataclass(frozen=True)
class Change:
    """A change to the install's values on one item, or on itself, held to the
    contract's ``change`` (:func:`change`): ``values`` sets them by key, a
    ``None`` removing its key, and ``upsert`` and ``remove`` change a list
    field's elements by their refs (:func:`write`)."""

    values: Mapping[str, Any]
    upsert: Mapping[str, Sequence[Mapping[str, Any]]]
    remove: Mapping[str, Sequence[str]]


def change(*, values: Any = None, upsert: Any = None, remove: Any = None) -> Change:
    """``values``, ``upsert`` and ``remove`` held to the contract's ``change``:
    at least one of the three, each an object by metadata key, and each key in
    one of them; ``upsert`` gives a list of elements under each key, and
    ``remove`` a list of refs. Each element, and each value that is not an
    array, is at most :data:`VALUE_BYTES` as JSON. Whether an array is a list's
    elements or one value is the item's to say, and :func:`write` measures it
    then."""
    given = [ops for ops in (values, upsert, remove) if ops is not None]
    if not given or not all(isinstance(ops, dict) for ops in given):
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    keys = [key for ops in given for key in ops]
    for key in keys:
        _check_key(key)
    if len(set(keys)) < len(keys):
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    for elements in (upsert or {}).values():
        if not isinstance(elements, list) or not all(map(_is_element, elements)):
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    measured = [
        *(element for elements in (upsert or {}).values() for element in elements),
        *(
            one
            for value in (values or {}).values()
            if value is not None
            for one in (value if isinstance(value, list) else [value])
        ),
    ]
    if any(_size(one) > VALUE_BYTES for one in measured):
        raise PluginChannelError(
            PluginChannelMessages.METADATA_VALUE_TOO_LARGE, status_code=413
        )
    for refs in (remove or {}).values():
        if not isinstance(refs, list) or not all(map(_is_ref, refs)):
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    return Change(values=values or {}, upsert=upsert or {}, remove=remove or {})


def _merged(held: Any, given: Mapping[str, Any]) -> dict[str, Any]:
    """An upserted element over the one with its ref: the properties given
    replace its own, the rest stay, and its ``state`` merges facet by facet."""
    if not isinstance(held, dict):
        return dict(given)
    merged = {**held, **given}
    if isinstance(held.get("state"), dict) and "state" in given:
        merged["state"] = {**held["state"], **given["state"]}
    return merged


async def write(
    session: AsyncSession,
    context: InstallContext,
    kind: str,
    entity_id: Optional[int],
    changes: Sequence[Change],
    pinned: Callable[[], Awaitable[Any]],
    *,
    made: Optional[Callable[[dict[str, Any]], Awaitable[Sequence[Change]]]] = None,
) -> dict[str, Any]:
    """Make ``changes``, in turn, to the install's values on one item, or on
    itself. Answers every value it keeps there now (:func:`assembled`).

    A key the pinned version declares as a list field on the item's kind holds
    a list of elements, a row each: ``values`` replaces them with a list of
    elements, or with none for a ``None``; ``upsert`` adds an element with a
    ref the list does not hold, and merges into the one it does (the
    properties given replace its own, the rest stay, and its ``state`` merges
    facet by facet); ``remove`` takes the elements with those refs, and a ref
    the list does not hold changes nothing. Any other key holds one value,
    which ``values`` sets and a ``None`` removes. Each value, and each element,
    is at most :data:`VALUE_BYTES` as JSON; a list counts as one key, and its
    elements' bytes add up.

    With ``made``, the changes made are those it answers when given what the
    install holds there (:func:`assembled`), under the item's lock, so writes
    made at once each read what the one before left.

    ``pinned`` reads the install's pinned definition, whose fields on the
    item's kind say which values are shown and which keys hold lists; a value
    on the install itself is never shown and holds no list, and its definition
    is not read.

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
    lists: Collection[str] = frozenset()
    if kind != INSTALL_METADATA_KIND:
        # Lock order: the install's fields lock (shared here), then the item's
        # lock. Holding the first while the definition is read, to the commit,
        # means a reconcile to a new definition (which takes it exclusively)
        # runs either before this read, which then sees the new definition,
        # or after this commit, and corrects what it wrote.
        await _lock_fields(session, context.guild_id, context.install_id, shared=True)
        definition = await pinned()
        shown, lists = shown_keys(definition, kind), _list_keys(definition, kind)

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
    stored = {
        (key, ref): (value, updated_at)
        for key, ref, value, updated_at in await session.exec(
            select(
                PluginMetadata.key,
                PluginMetadata.ref,
                PluginMetadata.value,
                PluginMetadata.updated_at,
            )
            .where(*where)
            .order_by(*NEWEST_FIRST)
        )
    }
    if made is not None:
        changes = await made(
            assembled((key, ref, value) for (key, ref), (value, _) in stored.items())
        )
    # The keys an item ends up with are counted below; a write may remove every
    # key it holds and set as many again, and no more.
    named = {
        key
        for each in changes
        for ops in (each.values, each.upsert, each.remove)
        for key in ops
    }
    if len(named) > 2 * max_keys:
        raise PluginChannelError(
            PluginChannelMessages.METADATA_LIMIT_REACHED, status_code=409
        )
    # What the item holds as each change is made, by key: its value under the
    # ref '', or its list's elements by their refs.
    held: dict[str, dict[str, Any]] = defaultdict(dict)
    for (key, ref), (value, _) in stored.items():
        held[key][ref] = value
    written: set[tuple[str, str]] = set()
    for each in changes:
        for key, value in each.values.items():
            if key not in lists:
                held[key] = {} if value is None else {"": value}
            elif value is None or (
                isinstance(value, list) and all(map(_is_element, value))
            ):
                held[key] = {element["ref"]: element for element in value or ()}
            else:
                raise PluginChannelError(PluginChannelMessages.METADATA_LIST_MISMATCH)
            written.update((key, ref) for ref in held[key])
        for key in (*each.upsert, *each.remove):
            if key not in lists:
                raise PluginChannelError(PluginChannelMessages.METADATA_LIST_MISMATCH)
        for key, elements in each.upsert.items():
            held[key].pop("", None)
            for element in elements:
                ref = element["ref"]
                held[key][ref] = _merged(held[key].get(ref), element)
                written.add((key, ref))
        for key, refs in each.remove.items():
            for ref in refs:
                held[key].pop(ref, None)

    rows = [
        (key, ref, value)
        for key, values in held.items()
        for ref, value in values.items()
    ]
    sizes = {(key, ref): _size(value) for key, ref, value in rows}
    if any(sizes[item] > VALUE_BYTES for item in written if item in sizes):
        raise PluginChannelError(
            PluginChannelMessages.METADATA_VALUE_TOO_LARGE, status_code=413
        )
    if (
        sum(1 for values in held.values() if values) > max_keys
        or sum(sizes.values()) > max_bytes
    ):
        raise PluginChannelError(
            PluginChannelMessages.METADATA_LIMIT_REACHED, status_code=409
        )

    gone = [item for item in stored if item not in sizes]
    if gone:
        await session.exec(
            delete(PluginMetadata).where(
                *where, tuple_(PluginMetadata.key, PluginMetadata.ref).in_(gone)
            )
        )
    now = datetime.now(timezone.utc)
    fresh = [row for row in rows if row[:2] in written]
    for start in range(0, len(fresh), _WRITE_BATCH):
        statement = insert(PluginMetadata).values(
            [
                {
                    "install_id": context.install_id,
                    "entity_type": kind,
                    "entity_id": entity_id,
                    "key": key,
                    "ref": ref,
                    "value": value,
                    "lookup": ref or _lookup(value),
                    "text_form": text_form,
                    "number_form": number_form,
                    "shown": key in shown,
                    "updated_at": now,
                }
                for key, ref, value in fresh[start : start + _WRITE_BATCH]
                for text_form, number_form in [forms(value)]
            ]
        )
        await session.exec(
            statement.on_conflict_do_update(
                index_elements=["install_id", "entity_type", "entity_id", "key", "ref"],
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
    # Newest first, then by ref, as a read answers them.
    rows.sort(key=lambda row: row[1])
    rows.sort(
        key=lambda row: now if row[:2] in written else stored[row[:2]][1],
        reverse=True,
    )
    return assembled(rows)


async def find(
    session: AsyncSession, context: InstallContext, key: str, value: str
) -> list[tuple[str, int, dict[str, Any]]]:
    """The items the install can read holding ``value`` under ``key``, a list
    holding it as an element's ref, with the values it keeps on each: at most
    :data:`FIND_LIMIT`, in kind and id order. The install's own values are not
    an item."""
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
        select(PluginMetadata)
        .where(
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
        .order_by(*NEWEST_FIRST)
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


def _targeted(answer: Any) -> list[tuple[dict[str, Any], Change]]:
    """What a declarative plug-in's ``write`` answered, held to the contract's
    ``targetedChange``: a list of at most :data:`WRITE_TARGETS`, each a target
    and a change (:func:`change`). Nothing answered is no change. An answer
    that is not that is refused whole, before anything is written."""
    if answer is UNDEFINED:
        return []
    if not isinstance(answer, list) or len(answer) > WRITE_TARGETS:
        raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
    changes: list[tuple[dict[str, Any], Change]] = []
    for raw in answer:
        if not (
            isinstance(raw, dict)
            and set(raw) <= {"target", "set", "upsert", "remove"}
            and _is_target(raw.get("target"))
        ):
            raise PluginChannelError(PluginChannelMessages.INVALID_PAYLOAD)
        changes.append(
            (
                raw["target"],
                change(
                    values=raw.get("set"),
                    upsert=raw.get("upsert"),
                    remove=raw.get("remove"),
                ),
            )
        )
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
    An item more than one change reaches is written once, its changes made in
    the order they were answered. Each item is written by :func:`write`, under
    its checks, caps and locks, and committed; one the install cannot read, or
    that is not there, is skipped.

    Raises :class:`PluginChannelError` for an answer that is not targeted
    changes, an install that may not act, and a write refused for any other
    reason. The items written before a refusal keep what was written: every
    change sets, merges or removes values, so making the same changes again
    leaves the same values.
    """
    changes = _targeted(answer)
    if not changes:
        return
    async with _as_install(plugin, registration, guild_id) as (session, route, pinned):
        context = await route()
        routed = time.monotonic()
        targets: dict[tuple[str, int], list[Change]] = {}
        for target, made in changes:
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
                targets.setdefault(item, []).append(made)

        for (kind, entity_id), made in targets.items():
            if time.monotonic() - routed > _REROUTE_SECONDS:
                context = await route()
                routed = time.monotonic()
            try:
                await write(session, context, kind, entity_id, made, pinned)
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

    async def changes(held: dict[str, Any]) -> list[Change]:
        answer = await made(held)
        if answer is None:
            return []
        ((_, changed),) = _targeted(
            [{**answer, "target": {"kind": kind, "id": entity_id}}]
        )
        return [changed]

    async with _as_install(plugin, registration, guild_id) as (session, route, pinned):
        await write(session, await route(), kind, entity_id, [], pinned, made=changes)


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
    """A plug-in field a reader may filter tasks by: its kind, the facets of
    its states, and the initiatives where they are drawn it."""

    install_id: int
    key: str
    kind: str
    facets: frozenset[str]
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
    # Each field's kind and the facets of its states.
    declared: dict[tuple[int, str], tuple[str, frozenset[str]]] = {}
    for install_id, definition, initiative_id, roles in rows.all():
        for field in _fields_on(definition, "task"):
            pair = (install_id, field["key"])
            if pair not in wanted:
                continue
            states = field.get("states")
            declared[pair] = (
                str(field.get("kind")),
                frozenset(map(str, states if isinstance(states, dict) else ())),
            )
            if await offered(
                install_id, initiative_id, roles, definition.get("minimum_age")
            ):
                reach[pair].add(initiative_id)
    return {
        wanted[pair]: FilterField(pair[0], pair[1], *declared[pair], frozenset(found))
        for pair, found in reach.items()
    }


#: The kinds a filter compares by their words; every other by its number.
_COMPARED_AS_TEXT = frozenset({"text", "link", "badge"})


def filter_clause(
    field: FilterField, op: FilterOp, value: Any, facet: Any = None
) -> Any:
    """A task list's condition on one plug-in field: one probe of the task's
    rows by its key, which a list's element each answers alone, on a task in
    an initiative where the reader is drawn the field. With ``facet``, one of
    the facets of the field's states, a value is compared by the key it names
    for that facet. ``None`` when the value cannot be compared."""
    form: Any
    if facet is None:
        as_text = field.kind in _COMPARED_AS_TEXT
        form = PluginMetadata.text_form if as_text else PluginMetadata.number_form
    elif isinstance(facet, str) and facet in field.facets:
        as_text, form = True, col(PluginMetadata.value)["state"][facet].astext
    else:
        return None

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
    initiative, a list's as an array (:func:`assembled`): those of the
    installs whose actions the reader could run there — on, placed in the
    item's initiative with a role the reader holds (or the reader its admin),
    and the reader old enough for the plug-in
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
                PluginMetadata.ref,
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
            .order_by(PluginMetadata.install_id, PluginMetadata.key, *NEWEST_FIRST)
        )
        offered = _Offered(context)
        held: dict[tuple[int, int], list[tuple[str, str, Any]]] = defaultdict(list)
        for item_id, install_id, key, ref, value, initiative_id, roles, minimum in rows:
            if await offered(install_id, initiative_id, roles, minimum):
                held[(item_id, install_id)].append((key, ref, value))
        for (item_id, install_id), values in held.items():
            found[item_id].extend(
                PluginValueSummary(plugin_id=install_id, key=key, value=value)
                for key, value in assembled(values).items()
            )
    return found
