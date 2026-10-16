"""The hooks about a community's install, and how they reach its plug-in.

Four hooks tell a plug-in what happened to the community it is installed in,
rather than to one of its connections:

* ``installed`` — the community installed it, for the first time or again.
  The references it holds come back with it (``plugin_refs``).
* ``uninstalled`` — the community removed it. Its references stand.
* ``erase`` — the community asked for its data to be erased, or is being
  purged. Once the plug-in answers, its references in the community are
  dropped, and a later install starts afresh.
* ``community_status`` — the community's status changed. The body is
  ``{"status": <CommunityStatus value>}``; the other three send ``{}``.

Each is a ``lifecycle`` context token with ``hook=<name>``, posted to the
plug-in's ``/v1/hooks/<name>`` by ``plugin_connection_flows.call_hook``.

**How to send one.** Call :func:`deliver_community_hook` (``guild_id``,
``public_id``, ``hook``, ``body``), which writes it down and wakes the worker,
or :func:`queue_community_hooks` from inside a transaction, which writes it
once that transaction commits and not at all if it rolls back. Both refuse a
name outside :data:`COMMUNITY_HOOK_NAMES` and send nothing to a plug-in this
deployment has no container registration for. A hook whose name is in
:data:`LATEST_WINS` replaces one of its kind still waiting for the same plug-in
in the same community: only the newest state is worth sending.

**How it is delivered.** Each hook is a row in ``plugin_community_hooks``
(``app.models.platform.plugin_community_hook``), delivered by one worker loop
(:data:`loop`, :func:`process_community_hooks`), one at a time per plug-in per
community and in the order they were written, so ``installed`` never overtakes
the ``uninstalled`` before it. An answer settles it:

* a 2xx is ``delivered``;
* a 404 is ``not_taken``: the plug-in does not take that hook, and it is not
  asked again;
* anything else, or no answer at all, is tried again after a backoff, until
  :data:`MAX_ATTEMPTS` have been spent, when it is ``gave_up``.

An ``erase`` that is ``delivered`` or ``not_taken`` drops the plug-in's
references in the community (``plugin_refs.drop_plugin_refs``); one that is not
answered keeps them, and is asked again. The row names no install by foreign
key, so an ``uninstalled`` or ``erase`` is retried after the install row is
gone. A purged community's rows go with its ``guilds`` row; the purge sends its
own ``erase`` first (:func:`erase_for_purge`), with a bounded number of tries.

**Statuses.** Every pass compares each enabled install's
``plugin_installs.community_status_sent`` with its community's status and
sends ``community_status`` where they differ (:func:`reconcile_community_status`),
so a status reaches every installed plug-in however it was changed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import post_commit
from app.db import session as db_session
from app.db.request_context import Unattributed
from app.models.platform.plugin_community_hook import (
    HOOK_ERROR_MAX_LENGTH,
    PluginCommunityHook,
)
from app.models.platform.plugin_install import PluginInstall
from app.services.background_tasks import Loop
from app.services.marketplace import plugin_refs, registration_lookup
from app.services.marketplace.registration_lookup import RegistrationSnapshot

logger = logging.getLogger(__name__)

__all__ = [
    "BACKOFF_SECONDS",
    "COMMUNITY_HOOK_NAMES",
    "COMMUNITY_HOOKS_POLL_SECONDS",
    "LATEST_WINS",
    "MAX_ATTEMPTS",
    "deliver_community_hook",
    "erase_for_purge",
    "loop",
    "process_community_hooks",
    "queue_community_hooks",
    "reconcile_community_status",
    "run_pass",
]

#: The hooks this module delivers. Each is in
#: ``plugin_connection_flows.HOOK_NAMES``, which is what lets ``call_hook``
#: send it.
COMMUNITY_HOOK_NAMES: frozenset[str] = frozenset(
    {"installed", "uninstalled", "erase", "community_status"}
)

#: Hooks that state where something stands now, so a newer one replaces one
#: still waiting rather than following it.
LATEST_WINS: frozenset[str] = frozenset({"community_status", "entitlement"})

#: How long the worker waits without a wake before looking anyway.
COMMUNITY_HOOKS_POLL_SECONDS = 15

#: The waits after each failed attempt, in seconds; the last repeats.
BACKOFF_SECONDS: tuple[int, ...] = (30, 120, 600, 1800, 3600, 6 * 3600)

#: Attempts before a hook is given up on: about four days of the backoff above.
MAX_ATTEMPTS = 20

#: A claim older than this is a pass that never finished, and another may take
#: the hook. Well above one call's timeout.
CLAIM_LEASE = timedelta(minutes=5)

#: How long an answered hook is kept, for an operator reading the table.
DONE_RETENTION = timedelta(days=7)

#: Hooks one pass sends, and how many at once.
BATCH_SIZE = 100
CONCURRENCY = 8

#: Tries a purge gives each plug-in's ``erase`` before it carries on.
PURGE_ERASE_ATTEMPTS = 2

#: The worker's loop: woken as hooks are written, and run every
#: :data:`COMMUNITY_HOOKS_POLL_SECONDS` regardless.
loop = Loop("community-hooks", interval=COMMUNITY_HOOKS_POLL_SECONDS)


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


async def _write(
    session: AsyncSession,
    *,
    guild_id: int,
    public_id: str,
    hook: str,
    body: Mapping[str, Any],
    install_id: Optional[int],
    now: datetime,
) -> None:
    """Stage one hook's row on a system-engine ``session``."""
    if hook in LATEST_WINS:
        await session.exec(
            delete(PluginCommunityHook).where(
                PluginCommunityHook.guild_id == guild_id,
                PluginCommunityHook.public_id == public_id,
                PluginCommunityHook.hook == hook,
                PluginCommunityHook.done_at.is_(None),
                PluginCommunityHook.claimed_at.is_(None),
            )
        )
    session.add(
        PluginCommunityHook(
            guild_id=guild_id,
            public_id=public_id,
            install_id=install_id,
            hook=hook,
            body=dict(body),
            created_at=now,
            next_attempt_at=now,
        )
    )


async def deliver_community_hook(
    *,
    guild_id: int,
    public_id: str,
    hook: str,
    body: Optional[Mapping[str, Any]] = None,
    install_id: Optional[int] = None,
) -> bool:
    """Send ``hook`` to the plug-in ``public_id`` about community ``guild_id``.

    Written down and delivered by the worker, with retries (see the module
    docstring), on a system-engine session of its own, so it can be called
    from anywhere that is not inside the transaction it is about; one that is
    calls :func:`queue_community_hooks` instead. ``install_id`` is the install
    the hook is about, as the token's ``plugin_install_id``; left out, the
    community's install of the plug-in when the hook is sent, or ``0`` when it
    has none.

    Returns whether a hook was written: ``False`` for a plug-in with no
    container registration here.
    """
    _check_name(hook)
    if await _container(public_id) is None:
        return False
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        await _write(
            session,
            guild_id=guild_id,
            public_id=public_id,
            hook=hook,
            body=body or {},
            install_id=install_id,
            now=datetime.now(timezone.utc),
        )
        await session.commit()
    loop.wake()
    return True


@dataclass
class _Queued:
    """One transaction's hooks, written in order once it commits."""

    hooks: list[tuple[int, str, str, dict[str, Any], Optional[int]]]

    def join(self, released: "_Queued") -> None:
        self.hooks.extend(released.hooks)

    async def __call__(self) -> None:
        for guild_id, public_id, hook, body, install_id in self.hooks:
            try:
                await deliver_community_hook(
                    guild_id=guild_id,
                    public_id=public_id,
                    hook=hook,
                    body=body,
                    install_id=install_id,
                )
            except Exception:
                logger.exception(
                    "community hooks: %s for %s in guild %s was not written",
                    hook,
                    public_id,
                    guild_id,
                )


def queue_community_hooks(
    session: Any,
    *,
    guild_id: int,
    public_id: str,
    hooks: Sequence[str],
    install_id: Optional[int] = None,
    body: Optional[Mapping[str, Any]] = None,
) -> None:
    """Send ``hooks``, in order, once ``session``'s transaction commits, and
    not at all if it rolls back. Each is :func:`deliver_community_hook` with
    ``body`` (``{}`` when left out)."""
    for hook in hooks:
        _check_name(hook)
    queued = post_commit.after_commit(
        session, _Queued([]), key="plugin_community_hooks"
    )
    for hook in hooks:
        queued.hooks.append((guild_id, public_id, hook, dict(body or {}), install_id))


# --- statuses ----------------------------------------------------------------

#: Each enabled install whose plug-in was last told a status other than its
#: community's, marked as told it now.
_STATUS_MOVED_SQL = text(
    """
UPDATE public.plugin_installs i
SET community_status_sent = g.status
FROM public.guilds g
WHERE g.id = i.guild_id
  AND i.enabled
  AND i.community_status_sent IS DISTINCT FROM g.status
RETURNING i.guild_id, i.install_id, i.listing_uid, g.status
"""
)


async def reconcile_community_status(session: AsyncSession) -> int:
    """Send ``community_status`` to every enabled install whose community's
    status is not the one its plug-in was last told. Returns how many were
    written.

    The mark and the hook are written in one transaction on ``session``, a
    system-engine session, which this commits.
    """
    await db_session.set_rls_context(session, Unattributed())
    moved = (await session.exec(_STATUS_MOVED_SQL)).all()
    if not moved:
        await session.commit()
        return 0
    by_listing = {
        snapshot.listing_uid: snapshot
        for snapshot in (await registration_lookup.load_registrations()).values()
        if snapshot.listing_uid and not snapshot.declarative
    }
    now = datetime.now(timezone.utc)
    written = 0
    for row in moved:
        registration = by_listing.get(row.listing_uid)
        if registration is None:
            continue
        await _write(
            session,
            guild_id=int(row.guild_id),
            public_id=registration.public_id,
            hook="community_status",
            body={"status": row.status},
            install_id=int(row.install_id),
            now=now,
        )
        written += 1
    await session.commit()
    return written


# --- delivery ----------------------------------------------------------------

#: The oldest unanswered hook of each plug-in in each community, claimed when
#: it is due and nobody holds it. The claim's conditions are on the row itself,
#: so a pass racing another for one re-reads them once the other's write lands.
_CLAIM_SQL = text(
    """
WITH heads AS (
  SELECT DISTINCT ON (guild_id, public_id) id
  FROM public.plugin_community_hooks
  WHERE done_at IS NULL
  ORDER BY guild_id, public_id, id
)
UPDATE public.plugin_community_hooks h
SET claimed_at = :now, attempts = h.attempts + 1
FROM (SELECT id FROM heads LIMIT :limit) AS due
WHERE h.id = due.id
  AND h.done_at IS NULL
  AND h.next_attempt_at <= :now
  AND (h.claimed_at IS NULL OR h.claimed_at < :lease_cutoff)
RETURNING h.id, h.guild_id, h.public_id, h.install_id, h.hook, h.body, h.attempts
"""
)


@dataclass(frozen=True)
class _Claimed:
    id: int
    guild_id: int
    public_id: str
    install_id: Optional[int]
    hook: str
    body: dict[str, Any]
    attempts: int


@dataclass(frozen=True)
class _Outcome:
    #: ``delivered``, ``not_taken``, or ``None`` to try again.
    outcome: Optional[str]
    error: Optional[str] = None


async def _claim(now: datetime) -> list[_Claimed]:
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        rows = (
            await session.exec(
                _CLAIM_SQL,
                params={
                    "now": now,
                    "lease_cutoff": now - CLAIM_LEASE,
                    "limit": BATCH_SIZE,
                },
            )
        ).all()
        await session.commit()
    return [
        _Claimed(
            id=int(row.id),
            guild_id=int(row.guild_id),
            public_id=str(row.public_id),
            install_id=row.install_id,
            hook=str(row.hook),
            body=dict(row.body or {}),
            attempts=int(row.attempts),
        )
        for row in rows
    ]


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


async def _settle(claimed: _Claimed, outcome: _Outcome, now: datetime) -> None:
    """Record how one attempt ended, and drop the references an answered
    ``erase`` let go."""
    if outcome.outcome is not None and claimed.hook == "erase":
        dropped = await plugin_refs.drop_plugin_refs(
            guild_id=claimed.guild_id, public_id=claimed.public_id
        )
        logger.info(
            "community hooks: %s erased its data in guild %s; %d reference(s) dropped",
            claimed.public_id,
            claimed.guild_id,
            dropped,
        )
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        row = await session.get(PluginCommunityHook, claimed.id)
        if row is None:
            # Its community was purged while it was being sent.
            return
        row.claimed_at = None
        if outcome.outcome is not None:
            row.done_at = now
            row.outcome = outcome.outcome
            row.last_error = None
        else:
            row.last_error = (outcome.error or "")[:HOOK_ERROR_MAX_LENGTH] or None
            if claimed.attempts >= MAX_ATTEMPTS:
                row.done_at = now
                row.outcome = "gave_up"
                logger.warning(
                    "community hooks: gave up on %s for %s in guild %s after %d "
                    "attempts (%s)",
                    claimed.hook,
                    claimed.public_id,
                    claimed.guild_id,
                    claimed.attempts,
                    row.last_error,
                )
            else:
                row.next_attempt_at = now + _backoff(claimed.attempts)
        session.add(row)
        await session.commit()


async def _deliver(claimed: _Claimed) -> None:
    try:
        outcome = await _send(
            hook=claimed.hook,
            guild_id=claimed.guild_id,
            public_id=claimed.public_id,
            install_id=claimed.install_id,
            body=claimed.body,
        )
    except Exception as exc:
        logger.exception(
            "community hooks: sending %s to %s in guild %s failed",
            claimed.hook,
            claimed.public_id,
            claimed.guild_id,
        )
        outcome = _Outcome(None, f"{type(exc).__name__}")
    await _settle(claimed, outcome, datetime.now(timezone.utc))


async def _sweep(now: datetime) -> int:
    async with db_session.SystemSessionLocal() as session:
        await db_session.set_rls_context(session, Unattributed())
        result = await session.exec(
            delete(PluginCommunityHook).where(
                PluginCommunityHook.done_at.is_not(None),
                PluginCommunityHook.done_at < now - DONE_RETENTION,
            )
        )
        await session.commit()
    return result.rowcount or 0


async def run_pass(*, now: Optional[datetime] = None) -> int:
    """One pass: statuses reconciled, answered hooks swept, and every due hook
    sent once. Returns how many were sent. Split from the loop entry point so a
    test can drive it."""
    moment = now or datetime.now(timezone.utc)
    async with db_session.SystemSessionLocal() as session:
        await reconcile_community_status(session)
    await _sweep(moment)
    claimed = await _claim(moment)
    if not claimed:
        return 0
    limit = asyncio.Semaphore(CONCURRENCY)

    async def bounded(one: _Claimed) -> None:
        async with limit:
            await _deliver(one)

    await asyncio.gather(*(bounded(one) for one in claimed))
    return len(claimed)


async def process_community_hooks() -> None:
    """One pass of the community-hook loop. Idempotent and safe to run on a
    schedule even when nothing is due."""
    await run_pass()


# --- a purge -------------------------------------------------------------------


async def _indexed_installs(guild_id: int) -> dict[str, int]:
    """The community's installs, by listing, from the install index."""
    from sqlmodel import select

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
                return
        logger.warning(
            "community hooks: %s did not answer erase for purged guild %s",
            public_id,
            guild_id,
        )

    await asyncio.gather(*(tell(public_id) for public_id in sorted(holding)))
