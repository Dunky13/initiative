"""Fire-and-forget pings to the external billing service, and its two reads.

Two nudges: a guild's membership changed, and a guild's lifecycle status
changed — deleted, restored, or moved by the operator.
What the service does with either is its own business; this side only sends
it. Neither carries a fact — the lifecycle one does not say which way the
guild moved.

Two more, for a listing a package names terms for: a plug-in's usage total
for one meter and month (``usage``), and its install, uninstall or erasure in
a community (``install``). These carry the listing's uid and what happened,
and still nothing about any person.

* the payload is the guild's reference and a fresh event id, and nothing
  else — no member data, no PII, no count;
* no retry queue and no delivery guarantee;
* the join/leave transaction must never fail or slow because the service is
  down: the send runs as a detached task with a tight timeout and swallows
  every error.

FOSS balance: on a self-hosted install (``BILLING_SERVICE_URL`` /
``BILLING_HMAC_SECRET`` unset — the default) :func:`notify_membership_changed`
returns before doing anything: no outbound call, no queued work, no logging.

The request carries the same request-bound HMAC discipline as the inbound
envelope (``METHOD\\nPATH\\nTIMESTAMP\\nsha256(body)`` keyed by the shared
secret), so billing can authenticate the nudge without a second credential.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import date
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.db import post_commit
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.platform.identity_refs import billing_ref, existing_ref

logger = logging.getLogger(__name__)

MEMBERSHIP_PING_PATH = "/api/v1/pings/membership"
LIFECYCLE_PING_PATH = "/api/v1/pings/lifecycle"
PLAN_SUMMARY_PATH = "/api/v1/plan-summary"
USAGE_PING_PATH = "/api/v1/pings/usage"
INSTALL_PING_PATH = "/api/v1/pings/install"
UNINSTALL_NOTICE_PATH = "/api/v1/plugin-uninstall-notice"

# httpx defaults to no total deadline; keep the whole attempt short — the
# ping is advisory and must never hold resources behind a slow billing pod.
_PING_TIMEOUT = httpx.Timeout(3.0, connect=2.0)
_PLAN_SUMMARY_TIMEOUT = httpx.Timeout(2.0, connect=1.0)
_PLAN_SUMMARY_MAX_BYTES = 1024
#: The whole answer to an uninstall-notice read, before it is shown verbatim.
UNINSTALL_NOTICE_SECONDS = 2.0
_UNINSTALL_NOTICE_MAX_BYTES = 4096

#: What happened to a plug-in in a community, as the install ping names it.
InstallEvent = Literal["installed", "uninstalled", "erased"]


def billing_ping_enabled() -> bool:
    """True only when a hosted deployment configured the outbound side."""
    return bool(settings.BILLING_SERVICE_URL and settings.BILLING_HMAC_SECRET)


def build_membership_ping(guild_ref: str) -> tuple[str, bytes, dict[str, str]]:
    """Assemble (url, body, headers) for one membership ping. Pure — no I/O."""
    return _build_ping(MEMBERSHIP_PING_PATH, guild_ref)


def build_lifecycle_ping(guild_ref: str) -> tuple[str, bytes, dict[str, str]]:
    """Assemble (url, body, headers) for one lifecycle ping. Pure — no I/O."""
    return _build_ping(LIFECYCLE_PING_PATH, guild_ref)


def _build_ping(ping_path: str, guild_ref: str) -> tuple[str, bytes, dict[str, str]]:
    """Assemble (url, body, headers) for one ping. Pure — no I/O.

    The guild is named by the reference billing holds for it, which is the only
    name for it the two share. The HMAC is bound to the path component
    billing's verifier will see, so a base URL with a path prefix still signs
    correctly.
    """
    return _signed_post(
        ping_path, {"community_ref": guild_ref, "event_id": uuid4().hex}
    )


def build_usage_ping(
    guild_ref: str, *, listing_uid: str, meter: str, period: str, quantity: int
) -> tuple[str, bytes, dict[str, str]]:
    """Assemble (url, body, headers) for one usage ping. Pure — no I/O."""
    return _signed_post(
        USAGE_PING_PATH,
        {
            "community_ref": guild_ref,
            "listing_uid": listing_uid,
            "meter": meter,
            "period": period,
            "quantity": quantity,
            "event_id": uuid4().hex,
        },
    )


def build_install_ping(
    guild_ref: str, *, listing_uid: str, event: InstallEvent
) -> tuple[str, bytes, dict[str, str]]:
    """Assemble (url, body, headers) for one install ping. Pure — no I/O."""
    return _signed_post(
        INSTALL_PING_PATH,
        {
            "community_ref": guild_ref,
            "listing_uid": listing_uid,
            "event": event,
            "event_id": uuid4().hex,
        },
    )


def _signed_post(route: str, payload: dict) -> tuple[str, bytes, dict[str, str]]:
    base = settings.BILLING_SERVICE_URL.rstrip("/")
    url = base + route
    path = urlsplit(url).path
    body = json.dumps(payload, separators=(",", ":")).encode()
    ts = str(int(time.time()))
    message = "\n".join(["POST", path, ts, hashlib.sha256(body).hexdigest()]).encode()
    signature = hmac.new(
        settings.BILLING_HMAC_SECRET.encode(), message, hashlib.sha256
    ).hexdigest()
    headers = {
        "X-Billing-Timestamp": ts,
        "X-Billing-Signature": signature,
        "Content-Type": "application/json",
    }
    return url, body, headers


async def _send_membership_ping(guild_id: int) -> None:
    """One attempt, no retry; never raises (task exceptions would only spam
    the loop's never-retrieved handler)."""
    try:
        guild_ref = await billing_ref(IdentityEntity.guild, guild_id)
        url, body, headers = build_membership_ping(guild_ref)
        async with httpx.AsyncClient(timeout=_PING_TIMEOUT) as client:
            await client.post(url, content=body, headers=headers)
    except Exception:
        logger.debug(
            "billing: membership ping for guild %s failed (billing will "
            "reconcile at period close)",
            guild_id,
        )


async def _send_lifecycle_ping(guild_id: int) -> None:
    """One attempt, no retry; never raises. Uses the guild's existing billing
    reference and never mints one."""
    try:
        guild_ref = await existing_ref(
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=IdentityPurpose.billing,
        )
        if guild_ref is None:
            return
        url, body, headers = build_lifecycle_ping(guild_ref)
        async with httpx.AsyncClient(timeout=_PING_TIMEOUT) as client:
            await client.post(url, content=body, headers=headers)
    except Exception:
        logger.debug(
            "billing: lifecycle ping for guild %s failed",
            guild_id,
        )


async def _post_ping(guild_id: int, build, what: str) -> None:
    """One attempt, no retry; never raises. Names the guild by its billing
    reference, minting one if billing has never been told of it: either ping
    is what makes billing act for the community."""
    try:
        guild_ref = await billing_ref(IdentityEntity.guild, guild_id)
        url, body, headers = build(guild_ref)
        async with httpx.AsyncClient(timeout=_PING_TIMEOUT) as client:
            await client.post(url, content=body, headers=headers)
    except Exception:
        logger.debug("billing: %s ping for guild %s failed", what, guild_id)


def notify_usage_reported(
    guild_id: int, *, listing_uid: str, meter: str, period: str, quantity: int
) -> None:
    """Tell billing a plug-in's total for one meter and month.

    Fire-and-forget like the other pings, and a no-op when billing is not
    configured. A lost ping is made good by the next report: each carries the
    period's whole total.
    """
    if not billing_ping_enabled():
        return
    post_commit.spawn(
        _post_ping(
            int(guild_id),
            lambda ref: build_usage_ping(
                ref,
                listing_uid=listing_uid,
                meter=meter,
                period=period,
                quantity=quantity,
            ),
            "usage",
        )
    )


def notify_plugin_install(
    guild_id: int, *, listing_uid: str, event: InstallEvent
) -> None:
    """Tell billing a listing with package terms was installed, uninstalled or
    erased in ``guild_id``. Call after the commit."""
    if not billing_ping_enabled():
        return
    post_commit.spawn(
        _post_ping(
            int(guild_id),
            lambda ref: build_install_ping(ref, listing_uid=listing_uid, event=event),
            "install",
        )
    )


def _dispatch(send, guild_id: int) -> None:
    if not billing_ping_enabled():
        return
    post_commit.spawn(send(int(guild_id)))


def notify_membership_changed(guild_id: int) -> None:
    """Nudge billing that ``guild_id``'s membership changed.

    Call from any code path that inserts or deletes a ``guild_memberships``
    row. Fire-and-forget: returns immediately, and is a complete no-op when
    billing is not configured. Callers may invoke this before their commit —
    a ping for a rolled-back change is harmless, because it carries no facts.
    """
    _dispatch(_send_membership_ping, guild_id)


def notify_lifecycle_changed(guild_id: int) -> None:
    """Nudge billing that ``guild_id``'s lifecycle status changed.

    Call **after** the commit, so the status it points at is the new one.
    """
    _dispatch(_send_lifecycle_ping, guild_id)


class PlanCharge(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    # Minor units of ``currency``.
    total: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class PlanChange(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    action: Literal["cancel", "pause", "resume"]
    on: date


class PlanSummary(BaseModel):
    """Billing's account of a guild's plan, as billing answered it.

    Read for one response and never stored: what a plan costs is billing's to
    hold (see ``app.models.platform.billing``). Fields billing adds later are
    ignored; a field that is here and malformed refuses the whole answer.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    tier_name: str | None = Field(default=None, max_length=64)
    trial_ends_on: date | None = None
    renews_on: date | None = None
    next_charge: PlanCharge | None = None
    scheduled_change: PlanChange | None = None
    payment_failed: bool = False


def build_plan_summary_query(guild_ref: str) -> tuple[str, bytes, dict[str, str]]:
    return _signed_post(PLAN_SUMMARY_PATH, {"community_ref": guild_ref})


async def guild_plan_summary(guild_id: int) -> PlanSummary | None:
    """Ask billing for ``guild_id``'s plan, or ``None`` when it cannot say.

    A read. The signed POST is a query and changes nothing on billing's side:
    initiative never writes to billing, and every change to a plan is made in
    the billing portal.

    A guild billing holds no reference for has never been there, so it has no
    trial, charge or failure to report: that is an empty summary, not a
    missing one, and nothing is minted to ask.
    """
    if not billing_ping_enabled():
        return None
    try:
        guild_ref = await existing_ref(
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=IdentityPurpose.billing,
        )
        if guild_ref is None:
            return PlanSummary()
        url, body, headers = build_plan_summary_query(guild_ref)
        async with httpx.AsyncClient(
            timeout=_PLAN_SUMMARY_TIMEOUT, follow_redirects=False
        ) as client:
            response = await client.post(url, content=body, headers=headers)
        if (
            response.status_code != 200
            or len(response.content) > _PLAN_SUMMARY_MAX_BYTES
        ):
            return None
        return PlanSummary.model_validate_json(response.content)
    except Exception:
        return None


async def guild_payment_failed(guild_id: int) -> bool:
    """Whether billing reports ``guild_id``'s last payment as failed.

    Read from the plan summary; a summary billing cannot give says no.
    """
    summary = await guild_plan_summary(guild_id)
    return summary is not None and summary.payment_failed


class UninstallNotice(BaseModel):
    """What billing says about removing one plug-in, in the reader's language.

    Shown verbatim and kept nowhere. Fields billing adds later are ignored.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    message: str = Field(min_length=1, max_length=500)
    action_url: str | None = Field(default=None, max_length=2000)

    @field_validator("action_url")
    @classmethod
    def _web_address(cls, value: str | None) -> str | None:
        if value is not None and urlsplit(value).scheme not in ("https", "http"):
            raise ValueError("action_url is not a web address")
        return value


def build_uninstall_notice_query(
    guild_ref: str, *, listing_uid: str, locale: str
) -> tuple[str, bytes, dict[str, str]]:
    return _signed_post(
        UNINSTALL_NOTICE_PATH,
        {"community_ref": guild_ref, "listing_uid": listing_uid, "locale": locale},
    )


async def _ask_uninstall_notice(
    guild_id: int, listing_uid: str, locale: str
) -> UninstallNotice | None:
    guild_ref = await existing_ref(
        entity_type=IdentityEntity.guild,
        entity_id=guild_id,
        purpose=IdentityPurpose.billing,
    )
    if guild_ref is None:
        return None
    url, body, headers = build_uninstall_notice_query(
        guild_ref, listing_uid=listing_uid, locale=locale
    )
    async with httpx.AsyncClient(
        timeout=_PLAN_SUMMARY_TIMEOUT, follow_redirects=False
    ) as client:
        response = await client.post(url, content=body, headers=headers)
    if (
        response.status_code != 200
        or len(response.content) > _UNINSTALL_NOTICE_MAX_BYTES
    ):
        return None
    return UninstallNotice.model_validate_json(response.content)


async def plugin_uninstall_notice(
    guild_id: int, *, listing_uid: str, locale: str
) -> UninstallNotice | None:
    """Ask billing what to tell somebody removing a plug-in, or ``None`` when
    it cannot say within :data:`UNINSTALL_NOTICE_SECONDS`.

    A read that changes nothing on billing's side. A guild billing holds no
    reference for has never been there, and is told nothing; so is one on a
    deployment with no billing.
    """
    if not billing_ping_enabled():
        return None
    try:
        return await asyncio.wait_for(
            _ask_uninstall_notice(guild_id, listing_uid, locale),
            timeout=UNINSTALL_NOTICE_SECONDS,
        )
    except Exception:
        return None
