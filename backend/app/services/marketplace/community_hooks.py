"""The hooks about a community's install, and how they reach its plug-in.

Five hooks tell a plug-in what happened to the community it is installed in,
rather than to one of its connections:

* ``installed`` — the community installed it, for the first time or again.
  The references it holds come back with it (``plugin_refs``).
* ``uninstalled`` — the community removed it. Its references stand.
* ``erase`` — the community asked for its data to be erased, or is being
  purged. Once the plug-in answers, its references in the community are
  dropped, and a later install starts afresh.
* ``community_status`` — the community's status changed. The body is
  ``{"status": <CommunityStatus value>}``.
* ``entitlement`` — the statement this deployment's issuer signed of what the
  community holds of the plug-in, ``{"statement": "<jws>"}`` exactly as the
  issuer sent it, written by ``plugin_entitlements.deliver_entitlement``.

``installed``, ``uninstalled`` and ``erase`` send ``{}``. Each is a
``lifecycle`` context token with ``hook=<name>``, posted to the plug-in's
``/v1/hooks/<name>`` by ``plugin_connection_flows.call_hook``.

**How to send one.** :func:`queue_community_hooks` writes hooks in the caller's
own transaction, so a rollback sends nothing; :func:`deliver_community_hook`
writes one from outside any, in a transaction of its own. Each hook is a row in
``public.plugin_community_hooks`` (``app.models.platform.plugin_community_hook``)
and arms the community's ``plugin_hooks`` sweep timer for now
(``app.services.sweep_timers``) in the same transaction. Both refuse a name
outside :data:`COMMUNITY_HOOK_NAMES` and write nothing for a declarative
plug-in, which Initiative calls on itself.

**How it is delivered.** The sweep's visit (:func:`visit`) sends the
community's due hooks, one plug-in at a time and in the order they were
written, so ``installed`` never overtakes the ``uninstalled`` before it, and a
plug-in that is down holds back only its own. A hook in :data:`LATEST_WINS`
records that a state changed and sends the state when it is sent: the
community's status then, or the newest entitlement statement then. One with a
newer one of its kind waiting is settled ``superseded`` unsent, even while it
waits out a backoff, so an old failure never holds the current state back. An
answer settles a hook:

* a 2xx is ``delivered``;
* a 404 is ``not_taken``: the plug-in does not take that hook, and it is not
  asked again;
* anything else, or no answer at all, is tried again after a backoff, and the
  plug-in's later hooks wait behind it, until :data:`MAX_ATTEMPTS` have been
  spent, when it is ``gave_up``.

The visit answers its own next due time: the soonest retry still waiting, or
the soonest answered row past :data:`DONE_RETENTION`, which the visit deletes.

An ``erase`` that is ``delivered`` or ``not_taken`` drops the plug-in's
references in the community, in the transaction that finishes it, and tells the
entitlement issuer; one that is not answered keeps them, and is asked again.
One given up on drops them all the same, since erasing is the community's
request, and goes on the audit stream (``plugin.erase_abandoned``). While an
erase is unfinished the plug-in cannot be installed again (:func:`erase_pending`).
The row names no install by foreign key, so an ``uninstalled`` or ``erase`` is
retried after the install row is gone. A purged community's rows go with its
``guilds`` row; the purge sends its own ``erase`` first
(:func:`erase_for_purge`), with a bounded number of tries.

**Statuses.** A change of a community's status arms its ``plugin_hooks`` timer
(:func:`status_changed`). The visit compares each enabled install's
``plugin_installs.community_status_sent`` with the community's status and
writes ``community_status`` where they differ; an install counts as told
only once its plug-in answers it (2xx or 404). The daily ``reconcile``
asks the same question (:func:`due_outside`), so a status that changed by a
path that armed nothing still reaches every installed plug-in within a day.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, insert, text, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import post_commit
from app.db import session as db_session
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.request_context import Unattributed
from app.models.platform.plugin_community_hook import (
    HOOK_ERROR_MAX_LENGTH,
    PluginCommunityHook,
)
from app.models.platform.plugin_install import PluginInstall
from app.models.platform.identity_ref import IdentityPurpose
from app.services.marketplace import plugin_refs, registration_lookup
from app.services.platform import identity_refs
from app.services.marketplace.registration_lookup import RegistrationSnapshot

logger = logging.getLogger(__name__)

__all__ = [
    "BACKOFF_SECONDS",
    "COMMUNITY_HOOK_NAMES",
    "DONE_RETENTION",
    "KIND",
    "LATEST_WINS",
    "MAX_ATTEMPTS",
    "deliver_community_hook",
    "due_outside",
    "erase_for_purge",
    "erase_pending",
    "queue_community_hooks",
    "status_changed",
    "visit",
]

#: The sweep timer kind that delivers them.
KIND = "plugin_hooks"

#: The hooks this module delivers. Each is in
#: ``plugin_connection_flows.HOOK_NAMES``, which is what lets ``call_hook``
#: send it.
COMMUNITY_HOOK_NAMES: frozenset[str] = frozenset(
    {"installed", "uninstalled", "erase", "community_status", "entitlement"}
)

#: Hooks that state where something stands now, so a newer one replaces one
#: still waiting rather than following it.
LATEST_WINS: frozenset[str] = frozenset({"community_status", "entitlement"})

#: The waits after each failed attempt, in seconds; the last repeats.
BACKOFF_SECONDS: tuple[int, ...] = (30, 120, 600, 1800, 3600, 6 * 3600)

#: Attempts before a hook is given up on: about four days of the backoff above.
MAX_ATTEMPTS = 20

#: How long an answered hook is kept, for an operator reading the table.
DONE_RETENTION = timedelta(days=7)

#: Tries a purge gives each plug-in's ``erase`` before it carries on.
PURGE_ERASE_ATTEMPTS = 2

_TABLE: Any = PluginCommunityHook.__table__  # type: ignore[attr-defined]


class UnknownCommunityHookError(ValueError):
    """A hook name this module does not deliver."""


def _check_name(hook: str) -> None:
    if hook not in COMMUNITY_HOOK_NAMES:
        raise UnknownCommunityHookError(f"not a community hook: {hook!r}")


async def _container(public_id: str) -> Optional[RegistrationSnapshot]:
    """The plug-in's registration, when it is a container this deployment
    calls; a declarative plug-in has nothing to receive a hook."""
    registration = (await registration_lookup.load_registrations()).get(public_id)
    if registration is None or registration.declarative:
        return None
    return registration


def _row(
    *,
    guild_id: int,
    public_id: str,
    hook: str,
    body: Mapping[str, Any],
    install_id: Optional[int],
    now: datetime,
) -> dict[str, Any]:
    return {
        "guild_id": guild_id,
        "public_id": public_id,
        "install_id": install_id,
        "hook": hook,
        "body": dict(body),
        "created_at": now,
        "next_attempt_at": now,
        "attempts": 0,
    }


async def _arm(session: AsyncSession, guild_id: int, now: datetime) -> None:
    """Arm the community's ``plugin_hooks`` timer for now, on ``session``: the
    write's own routing when it is routed there, else the system engine's."""
    from app.services import sweep_timers

    if db_session.routed_guild_id(session) == guild_id:
        await sweep_timers.arm(session, KIND, now)
    else:
        await sweep_timers.arm_now(session, KIND, [guild_id])


async def queue_community_hooks(
    session: AsyncSession,
    *,
    guild_id: int,
    public_id: str,
    hooks: Sequence[str],
    install_id: Optional[int] = None,
    body: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Write ``hooks``, in order, on ``session``, and arm the community's
    timer, so they go once its transaction commits and not at all if it rolls
    back. Each carries ``body`` (``{}`` when left out).

    ``session`` is routed into the community (a routed write inserts the rows
    and arms the timer under the community's own role), or is the system
    engine's. ``install_id`` is the install the hooks are about, as the token's
    ``plugin_install_id``; left out, the community's install of the plug-in
    when each is sent, or ``0`` when it has none. Returns whether anything was
    written: nothing is for a declarative plug-in. One with no registration
    here is written all the same (an ``erase`` has to outlive a deleted
    registration), and is reported unreachable until it is given up on.
    """
    for hook in hooks:
        _check_name(hook)
    if not hooks:
        return False
    registration = (await registration_lookup.load_registrations()).get(public_id)
    if registration is not None and registration.declarative:
        # Initiative makes a declarative plug-in's calls itself: nobody to tell.
        return False
    now = datetime.now(timezone.utc)
    await session.exec(
        insert(_TABLE).values(
            [
                _row(
                    guild_id=guild_id,
                    public_id=public_id,
                    hook=hook,
                    body=body or {},
                    install_id=install_id,
                    now=now,
                )
                for hook in hooks
            ]
        )
    )
    await _arm(session, guild_id, now)
    return True


async def deliver_community_hook(
    *,
    guild_id: int,
    public_id: str,
    hook: str,
    body: Optional[Mapping[str, Any]] = None,
    install_id: Optional[int] = None,
) -> bool:
    """Send ``hook`` to the plug-in ``public_id`` about community ``guild_id``,
    from outside any transaction about it: :func:`queue_community_hooks` on a
    system-engine session of its own, committed. Returns whether it was
    written."""
    _check_name(hook)
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        written = await queue_community_hooks(
            session,
            guild_id=guild_id,
            public_id=public_id,
            hooks=(hook,),
            install_id=install_id,
            body=body,
        )
        await session.commit()
    return written


def status_changed(session: Any, guild_id: int) -> None:
    """The community's status is changing in ``session``'s transaction: once
    it commits, arm its ``plugin_hooks`` timer, whose visit tells each
    installed plug-in. Nothing is armed if it rolls back."""
    from app.services import sweep_timers

    post_commit.after_commit(session, lambda: sweep_timers.arm_in(KIND, [guild_id]))


# --- the visit ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Outcome:
    #: ``delivered``, ``not_taken``, or ``None`` to try again.
    outcome: Optional[str]
    error: Optional[str] = None


#: The community's enabled installs whose plug-in was last told a status other
#: than the community's (or none), with no ``community_status`` hook already
#: waiting for its plug-in.
_STATUS_UNTOLD_SQL = text(
    """
SELECT i.install_id, i.listing_uid
FROM public.plugin_installs i
JOIN public.guilds g ON g.id = i.guild_id
WHERE i.guild_id = :guild
  AND i.enabled
  AND i.community_status_sent IS DISTINCT FROM g.status
"""
)


async def _tell_status(session: AsyncSession, guild_id: int, now: datetime) -> None:
    """Write ``community_status`` for each of the community's enabled installs
    whose plug-in has not been told its status and has none waiting. The row
    says only that the status moved: what is sent is the status when it is
    sent, and the install counts as told once the plug-in answers."""
    untold = (
        await session.exec(_STATUS_UNTOLD_SQL, params={"guild": guild_id})  # type: ignore[call-overload]
    ).all()
    if not untold:
        return
    by_listing = {
        snapshot.listing_uid: snapshot
        for snapshot in (await registration_lookup.load_registrations()).values()
        if snapshot.listing_uid and not snapshot.declarative
    }
    waiting = set(
        (
            await session.exec(
                select(PluginCommunityHook.public_id).where(
                    PluginCommunityHook.guild_id == guild_id,
                    PluginCommunityHook.hook == "community_status",
                    col(PluginCommunityHook.done_at).is_(None),
                )
            )
        ).all()
    )
    rows = [
        _row(
            guild_id=guild_id,
            public_id=by_listing[row.listing_uid].public_id,
            hook="community_status",
            body={},
            install_id=int(row.install_id),
            now=now,
        )
        for row in untold
        if row.listing_uid in by_listing
        and by_listing[row.listing_uid].public_id not in waiting
    ]
    if rows:
        await session.exec(insert(_TABLE).values(rows))


async def _current_body(
    hook: str, guild_id: int, public_id: str, stored: Mapping[str, Any]
) -> Optional[dict[str, Any]]:
    """What a hook says when it is sent. A state hook says the state now: the
    community's status, or the newest signed entitlement statement as stored
    (``None`` when there is none, and nothing to send). Every other hook says what it was
    written with."""
    if hook == "community_status":
        from app.services.marketplace.community_status import community_status

        return {"status": await community_status(guild_id)}
    if hook == "entitlement":
        from app.services.marketplace import plugin_entitlements

        registration = (await registration_lookup.load_registrations()).get(public_id)
        if registration is None or not registration.listing_uid:
            return None
        statement = await plugin_entitlements.read_statement(
            guild_id, registration.listing_uid
        )
        if statement is None:
            return None
        # The signed statement exactly as the issuer sent it, never rebuilt:
        # the plug-in verifies the issuer's signature over these bytes.
        return {"statement": statement.jws}
    return dict(stored)


async def _send(
    *,
    hook: str,
    guild_id: int,
    public_id: str,
    install_id: Optional[int],
    body: Mapping[str, Any],
) -> _Outcome:
    """Send one hook once, and say how it ended."""
    from app.services.tenant import plugin_connection_flows as flows

    registration = await _container(public_id)
    if (
        registration is None
        or not registration.base_url
        or not registration.live_in(guild_id)
    ):
        return _Outcome(None, "the plug-in is not reachable here")

    guild_ref: Optional[str] = None
    if hook == "erase":
        # Nothing to tell it to forget when it calls the community nothing;
        # whatever else it holds a name for is dropped all the same.
        guild_ref = await plugin_refs.existing_plugin_guild_ref(
            guild_id=guild_id, public_id=public_id
        )
        if guild_ref is None:
            return _Outcome("delivered")
    if install_id is None:
        install_id = await plugin_refs.current_install_id(
            guild_id=guild_id, public_id=public_id
        )
    try:
        await flows.call_hook(
            hook,
            public_id=public_id,
            base_url=registration.base_url,
            guild_id=guild_id,
            install_id=install_id or 0,
            body=body,
            guild_ref=guild_ref,
        )
    except flows.HookError as exc:
        if exc.status == 404:
            return _Outcome("not_taken")
        if exc.status is not None and 200 <= exc.status < 300:
            # Answered, with a body nothing here reads.
            return _Outcome("delivered")
        return _Outcome(None, str(exc))
    return _Outcome("delivered")


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1])


async def _report_erased(guild_id: int, public_id: str) -> None:
    """Tell the entitlement issuer the plug-in's data is erased, for a listing
    it has terms for."""
    from app.services.marketplace import plugin_entitlements

    registration = (await registration_lookup.load_registrations()).get(public_id)
    if registration is None or not registration.listing_uid:
        return
    try:
        await plugin_entitlements.erased(guild_id, registration.listing_uid)
    except Exception:
        logger.exception(
            "community hooks: the erase of %s in guild %s was not reported",
            public_id,
            guild_id,
        )


async def _record_abandoned_erase(row: PluginCommunityHook, attempts: int) -> None:
    """Put an ``erase`` the plug-in never answered on the audit stream."""
    from app.core.audit_events import AuditEventType
    from app.services import audit as audit_service

    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        await audit_service.record(
            session,
            event_type=AuditEventType.PLUGIN_ERASE_ABANDONED,
            actor_user_id=None,
            guild_id=row.guild_id,
            target_type="plugin",
            target_id=row.install_id,
            detail={"plugin": row.public_id, "attempts": attempts},
        )
        await session.commit()


async def _mark_status_told(
    session: AsyncSession, row: PluginCommunityHook, status: str
) -> None:
    """The plug-in answered ``community_status``: its install counts as told
    ``status``."""
    registration = (await registration_lookup.load_registrations()).get(row.public_id)
    if registration is None or not registration.listing_uid:
        return
    await session.exec(
        update(PluginInstall.__table__)  # type: ignore[attr-defined]
        .where(
            PluginInstall.__table__.c.guild_id == row.guild_id,  # type: ignore[attr-defined]
            PluginInstall.__table__.c.listing_uid == registration.listing_uid,  # type: ignore[attr-defined]
        )
        .values(community_status_sent=status)
    )


async def _settle(
    session: AsyncSession,
    row: PluginCommunityHook,
    outcome: _Outcome,
    sent: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Record how one attempt ended, and drop the references an ``erase`` that
    is done with let go. Returns whether the hook is done."""
    now = datetime.now(timezone.utc)
    attempts = row.attempts + 1
    values: dict[str, Any] = {"attempts": attempts}
    if outcome.outcome is not None:
        values.update(done_at=now, outcome=outcome.outcome, last_error=None)
        if row.hook == "community_status" and sent is not None:
            await _mark_status_told(session, row, str(sent["status"]))
    else:
        values["last_error"] = (outcome.error or "")[:HOOK_ERROR_MAX_LENGTH] or None
        if attempts >= MAX_ATTEMPTS:
            values.update(done_at=now, outcome="gave_up")
            logger.warning(
                "community hooks: gave up on %s for %s in guild %s after %d "
                "attempts (%s)",
                row.hook,
                row.public_id,
                row.guild_id,
                attempts,
                values["last_error"],
            )
        else:
            values["next_attempt_at"] = now + _backoff(attempts)
    await session.exec(update(_TABLE).where(_TABLE.c.id == row.id).values(**values))
    erased = row.hook == "erase" and "done_at" in values
    dropped = 0
    if erased:
        # Erasing is the community's request: a plug-in that never answers it
        # does not keep the names, it only loses the chance to say it erased.
        # Dropped in the transaction that finishes the erase, so nothing can
        # see it finished and still find the names.
        dropped = await identity_refs.drop_sector_refs(
            session,
            sector_guild_id=row.guild_id,
            sector_plugin=row.public_id,
            purpose=IdentityPurpose.plugin,
        )
    await session.commit()
    if erased:
        logger.info(
            "community hooks: %s %s erase in guild %s; %d reference(s) dropped",
            row.public_id,
            "never answered" if values["outcome"] == "gave_up" else "answered",
            row.guild_id,
            dropped,
        )
        if values["outcome"] == "gave_up":
            await _record_abandoned_erase(row, attempts)
        else:
            await _report_erased(row.guild_id, row.public_id)
    return "done_at" in values


async def _deliver_plugin(
    guild_id: int, rows: list[PluginCommunityHook], now: datetime
) -> None:
    """Send one plug-in's due hooks, oldest first, until one is not answered,
    on a session of its own so plug-ins are sent to side by side, and one that
    is down or waiting out a backoff holds back only its own.

    A state hook with a newer one of its kind waiting is settled ``superseded``
    first, whether or not it is due, so a send that failed never holds the
    current state back."""
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        stale, _rest = _effective(rows)
        if stale:
            await session.exec(
                update(_TABLE)
                .where(_TABLE.c.id.in_(stale))
                .values(done_at=now, outcome="superseded")
            )
            await session.commit()
        for row in rows:
            if row.id in stale:
                continue
            if row.next_attempt_at > now:
                return
            sent: Optional[dict[str, Any]] = None
            try:
                sent = await _current_body(row.hook, guild_id, row.public_id, row.body)
                outcome = (
                    _Outcome("superseded")
                    if sent is None
                    else await _send(
                        hook=row.hook,
                        guild_id=guild_id,
                        public_id=row.public_id,
                        install_id=row.install_id,
                        body=sent,
                    )
                )
            except Exception as exc:
                logger.exception(
                    "community hooks: sending %s to %s in guild %s failed",
                    row.hook,
                    row.public_id,
                    guild_id,
                )
                outcome = _Outcome(None, type(exc).__name__)
            if not await _settle(session, row, outcome, sent):
                return


async def erase_pending(*, guild_id: int, public_id: str) -> bool:
    """Whether the community asked ``public_id`` to erase its data and that
    erase is not finished: neither answered nor given up on."""
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        return (
            await session.exec(
                select(PluginCommunityHook.id).where(
                    PluginCommunityHook.guild_id == guild_id,
                    PluginCommunityHook.public_id == public_id,
                    PluginCommunityHook.hook == "erase",
                    col(PluginCommunityHook.done_at).is_(None),
                )
            )
        ).first() is not None


def _effective(
    rows: list[PluginCommunityHook],
) -> tuple[list[int], list[PluginCommunityHook]]:
    """One plug-in's unfinished hooks, oldest first, split into the state
    hooks a newer one of their kind supersedes and the rest, in order."""
    newest = {row.hook: row.id for row in rows if row.hook in LATEST_WINS}
    stale = [
        int(row.id or 0)
        for row in rows
        if row.hook in LATEST_WINS and row.id != newest[row.hook]
    ]
    return stale, [row for row in rows if row.id not in stale]


async def _next_due(session: AsyncSession, guild_id: int) -> Optional[datetime]:
    """When the community next has hook work: each plug-in's first hook still
    to send (now, if one of its state hooks is waiting to be superseded), or an
    answered row coming past its keeping. A hook queued behind one waiting
    out a retry is not counted: it goes once that one does."""
    rows = (
        await session.exec(
            select(PluginCommunityHook)
            .where(
                PluginCommunityHook.guild_id == guild_id,
                col(PluginCommunityHook.done_at).is_(None),
            )
            .order_by(col(PluginCommunityHook.public_id), col(PluginCommunityHook.id))
        )
    ).all()
    by_plugin: dict[str, list[PluginCommunityHook]] = {}
    for row in rows:
        by_plugin.setdefault(row.public_id, []).append(row)
    due: list[datetime] = []
    now = datetime.now(timezone.utc)
    for queue in by_plugin.values():
        stale, rest = _effective(queue)
        if stale:
            due.append(now)
        elif rest:
            due.append(rest[0].next_attempt_at)
    kept = (
        await session.exec(
            select(func.min(PluginCommunityHook.done_at)).where(
                PluginCommunityHook.guild_id == guild_id,
                col(PluginCommunityHook.done_at).is_not(None),
            )
        )
    ).first()
    if kept is not None:
        due.append(kept + DONE_RETENTION)
    return min(due) if due else None


async def visit(routed: AsyncSession, guild_id: int) -> Optional[datetime]:
    """The ``plugin_hooks`` sweep's visit: tell installed plug-ins a status they
    have not been told, send the community's due hooks, delete answered ones
    past their keeping, and answer when there is next work.

    The rows are ``public``'s and kept by the system engine, so they are read
    and written on system sessions of the visit's own; ``routed``, the
    community's session, holds the community's lock for the visit, so two
    visits never send one hook twice.
    """
    if not await advisory_lock(
        routed, LockNamespace.PLUGIN_HOOKS, guild_id, wait=False
    ):
        # Another visit is sending them, and answers the next time itself.
        return None
    now = datetime.now(timezone.utc)
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        await _tell_status(session, guild_id, now)
        await session.exec(
            delete(_TABLE).where(
                _TABLE.c.guild_id == guild_id,
                _TABLE.c.done_at.is_not(None),
                _TABLE.c.done_at <= now - DONE_RETENTION,
            )
        )
        pending = (
            await session.exec(
                select(PluginCommunityHook)
                .where(
                    PluginCommunityHook.guild_id == guild_id,
                    col(PluginCommunityHook.done_at).is_(None),
                )
                .order_by(
                    col(PluginCommunityHook.public_id), col(PluginCommunityHook.id)
                )
            )
        ).all()
        await session.commit()
        session.expunge_all()
    by_plugin: dict[str, list[PluginCommunityHook]] = {}
    for row in pending:
        by_plugin.setdefault(row.public_id, []).append(row)
    await asyncio.gather(
        *(_deliver_plugin(guild_id, rows, now) for rows in by_plugin.values())
    )
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        return await _next_due(session, guild_id)


async def due_outside(guild_id: int, now: datetime) -> Optional[datetime]:
    """What the daily reconcile asks of the ``plugin_hooks`` sweep, read on the
    system engine since its rows are ``public``'s: ``now`` when an enabled
    install has not been told the community's status, else the visit's own
    next due time."""
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        untold = (
            await session.exec(_STATUS_UNTOLD_SQL, params={"guild": guild_id})  # type: ignore[call-overload]
        ).all()
        # An untold install of a plug-in with no registration here has nothing
        # to be sent; it is told once there is one.
        registered = {
            snapshot.listing_uid
            for snapshot in (await registration_lookup.load_registrations()).values()
            if snapshot.listing_uid and not snapshot.declarative
        }
        if any(row.listing_uid in registered for row in untold):
            return now
        return await _next_due(session, guild_id)


# --- a purge -------------------------------------------------------------------


async def _indexed_installs(guild_id: int) -> dict[str, int]:
    """The community's installs, by listing, from the install index."""
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        rows = (
            await session.exec(
                select(PluginInstall.listing_uid, PluginInstall.install_id).where(
                    PluginInstall.guild_id == guild_id
                )
            )
        ).all()
    return {str(listing): int(install) for listing, install in rows}


async def erase_for_purge(guild_id: int, *, public_ids: Iterable[str] = ()) -> None:
    """Tell every plug-in holding references in a community about to be purged
    to erase what it holds, before they are dropped.

    Best-effort and bounded: each plug-in is tried :data:`PURGE_ERASE_ATTEMPTS`
    times, all of them at once, and the purge goes ahead whatever they answer.
    ``public_ids`` adds plug-ins to tell beside those holding references.
    Never raises.
    """
    try:
        holding = set(await plugin_refs.plugins_with_refs(guild_id=guild_id))
        holding.update(public_ids)
        if not holding:
            return
        installs = await _indexed_installs(guild_id)
        registrations = await registration_lookup.load_registrations()
    except Exception:
        logger.exception("community hooks: purge of guild %s told nobody", guild_id)
        return

    async def tell(public_id: str) -> None:
        registration = registrations.get(public_id)
        install_id = (
            installs.get(registration.listing_uid or "")
            if registration is not None
            else None
        )
        for _ in range(PURGE_ERASE_ATTEMPTS):
            try:
                outcome = await _send(
                    hook="erase",
                    guild_id=guild_id,
                    public_id=public_id,
                    install_id=install_id or 0,
                    body={},
                )
            except Exception:
                logger.exception(
                    "community hooks: erase for %s in purged guild %s failed",
                    public_id,
                    guild_id,
                )
                continue
            if outcome.outcome is not None:
                # Told while the community's row, and billing's name for it,
                # still stand.
                await _report_erased(guild_id, public_id)
                return
        logger.warning(
            "community hooks: %s did not answer erase for purged guild %s",
            public_id,
            guild_id,
        )

    await asyncio.gather(*(tell(public_id) for public_id in sorted(holding)))
