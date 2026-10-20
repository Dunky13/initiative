"""Endpoints for the external billing service.

Machine-to-machine: requests are verified by
``app.services.platform.billing.verify_billing_envelope`` over the raw body
before parsing, run under the ``initiative_billing`` database role scoped to
the request's guild, and share one transaction (jti redemption, event-log
claim, and write commit or roll back together). Not part of the OpenAPI
schema; no user is ever resolved.

Every verb names its guild by the **reference** billing holds for it, never by
a row id of ours. ``_resolve_guild`` is the one place that becomes a guild id,
and everything past it works on the id as before.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from app.api.deps import SessionDep
from app.core.messages import BillingMessages
from app.db import cohorts
from app.db.session import set_rls_context
from app.schemas.platform.billing import (
    BillingCommunityNotice,
    BillingCommunityNoticeRead,
    BillingCommunityNameRead,
    BillingCommunityNameRequest,
    BillingCommunityNamesRead,
    BillingCommunityNamesRequest,
    BillingCommunityStatusRead,
    BillingCommunityStatusRequest,
    BillingCommunityTierApply,
    BillingCommunityTierRead,
    BillingPluginEntitlementApply,
    BillingPluginEntitlementRead,
    BillingUsageRead,
    BillingUsageRequest,
)
from app.models.platform.guild import CommunityStatus
from app.models.platform.identity_ref import IdentityEntity
from app.db import post_commit
from app.services.marketplace import plugin_entitlements
from app.services.platform import billing as billing_service
from app.services.platform import guilds as guilds_service
from app.services.platform import identity_refs
from app.db.request_context import Billing

router = APIRouter(include_in_schema=False)
logger = logging.getLogger(__name__)


def _payload_error_code(exc: ValidationError) -> str:
    """Surface a BILLING_* code raised by a model validator (e.g. the
    support-source restriction) instead of the generic payload code."""
    for error in exc.errors():
        message = str(error.get("msg", ""))
        for code in (
            BillingMessages.SUPPORT_SOURCE_RESTRICTED,
            BillingMessages.ACTOR_REQUIRED,
            BillingMessages.NOTICE_SOURCE_NOT_ALLOWED,
            BillingMessages.INVALID_STATEMENT,
        ):
            if code in message:
                return code
    return BillingMessages.INVALID_PAYLOAD


async def _verify_and_parse(request: Request, model):
    """Envelope first, parse second (see module docstring)."""
    body = await request.body()
    claims = billing_service.verify_billing_envelope(
        method=request.method,
        path=request.url.path,
        headers=request.headers,
        body=body,
    )
    try:
        payload = model.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_payload_error_code(exc),
        ) from exc
    return claims, payload


async def _resolve_guild(guild_ref: str) -> int:
    """The guild billing's reference names.

    Billing names a guild by the reference it was given and never by a row id
    of ours, so this is the edge every verb below crosses first. An unknown
    reference answers 404 with nothing consumed, which is the same retryable
    shape as a guild that does not exist yet.
    """
    guild_id = await identity_refs.resolve_billing_ref(guild_ref, IdentityEntity.guild)
    if guild_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.COMMUNITY_NOT_FOUND,
        )
    return guild_id


async def _burn_jti(session, claims) -> None:
    await billing_service.record_jti(
        session, jti=claims.jti, expires_at=claims.expires_at
    )


@router.post("/community-tier", response_model=BillingCommunityTierRead)
async def apply_community_tier(
    request: Request, session: SessionDep
) -> BillingCommunityTierRead:
    claims, payload = await _verify_and_parse(request, BillingCommunityTierApply)
    guild_id = await _resolve_guild(payload.community_ref)
    await set_rls_context(session, Billing(guild_id))
    await _burn_jti(session, claims)
    status_before = await billing_service.guild_lifecycle_status(session, guild_id)
    # A refusal rolls back with neither the jti nor the event id consumed: a
    # missing guild (404) is retryable once it exists, a source restriction
    # (422) once the payload is corrected.
    result = await billing_service.apply_guild_tier(session, payload, guild_id=guild_id)
    await session.commit()
    if (
        result.status is CommunityStatus.on_hold
        and status_before is not CommunityStatus.on_hold
    ):
        # Told once, on the way in, and on the system engine: the billing
        # role writes guild status and caps and nothing else.
        async with cohorts.system_session(guild_id) as system_session:
            await guilds_service.announce_on_hold(system_session, guild_id)
    return result


@router.post("/community-notice", response_model=BillingCommunityNoticeRead)
async def community_notice(
    request: Request, session: SessionDep
) -> BillingCommunityNoticeRead:
    """Tell a community's owner something about its plan, from a fixed list.

    Billing names the notice and the day it is about; the words, the
    recipients and the delivery are ours. At least once, never lost:

    1. the envelope is checked and its jti burned, and that is committed;
    2. on the system engine — the billing role writes the event log and may
       not read it — an event id already in the log is a replay, and tells
       nobody;
    3. on the system engine, the bell lines and the letters are written to the
       notice outbox, whose worker delivers and retries them, and committed;
    4. only then is the event id claimed, on the billing session.

    The two writes are on two roles and cannot share a transaction without
    widening either one's grants. A failure before step 4 leaves the event
    unclaimed, and billing's retry delivers it; a crash between 3 and 4
    repeats the reminder rather than losing it. A community that is deleted or
    suspended is recorded and tells nobody.
    """
    claims, payload = await _verify_and_parse(request, BillingCommunityNotice)
    guild_id = await _resolve_guild(payload.community_ref)
    await set_rls_context(session, Billing(guild_id))
    await _burn_jti(session, claims)
    if await billing_service.guild_lifecycle_status(session, guild_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.COMMUNITY_NOT_FOUND,
        )
    await session.commit()  # persist the one-shot jti redemption
    owner_user_id = (
        await identity_refs.resolve_billing_ref(
            payload.recipient_user_ref, IdentityEntity.user
        )
        if payload.recipient_user_ref
        else None
    )
    try:
        async with cohorts.system_session(guild_id) as system_session:
            if await billing_service.event_claimed(system_session, payload.event_id):
                return BillingCommunityNoticeRead(delivered=False)
            delivered = await guilds_service.queue_billing_notice(
                system_session,
                guild_id,
                kind=payload.kind.value,
                day=payload.day,
                owner_user_id=owner_user_id,
            )
    except Exception as exc:
        logger.exception("billing: community notice %s not written", payload.event_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BillingMessages.NOTICE_NOT_DELIVERED,
        ) from exc
    # A concurrent delivery of the same event may have claimed it meanwhile;
    # both wrote the notice, which is the at-least-once this accepts.
    await billing_service.claim_community_notice(session, payload, guild_id=guild_id)
    await session.commit()
    return BillingCommunityNoticeRead(delivered=delivered)


@router.post("/community-name", response_model=BillingCommunityNameRead)
async def community_name(
    request: Request, session: SessionDep
) -> BillingCommunityNameRead:
    """Signed read: what one guild calls itself.

    For rendering. A reference is unreadable on purpose, so a page about
    somebody's own community would otherwise have nothing to title itself with.

    Envelope-verified and jti-burned like the other reads. A guild that has been
    deleted 404s with the jti unredeemed, so the call stays retryable while it
    is the caller's timing rather than their credential that is wrong.
    """
    claims, payload = await _verify_and_parse(request, BillingCommunityNameRequest)
    guild_id = await _resolve_guild(payload.community_ref)
    await set_rls_context(session, Billing(guild_id))
    await _burn_jti(session, claims)

    name = await billing_service.guild_display_name(session, guild_id)
    if name is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.COMMUNITY_NOT_FOUND,
        )
    await session.commit()  # persist the one-shot jti redemption
    return BillingCommunityNameRead(community_ref=payload.community_ref, name=name)


@router.post("/community-names", response_model=BillingCommunityNamesRead)
async def community_names(
    request: Request, session: SessionDep
) -> BillingCommunityNamesRead:
    """Signed read: what each of many guilds calls itself, for billing's owner
    directory, which names every paying community at once.

    The batch of ``/community-name``, and read the same way: each guild's name
    on the billing session routed to that guild, one at a time, so the role
    reads exactly the rows it would one call each. A reference that names no
    guild, or one deleted since, is left out; when none of them names one,
    nothing was read and the jti stays unredeemed, like the single read's 404.
    """
    claims, payload = await _verify_and_parse(request, BillingCommunityNamesRequest)
    refs = list(dict.fromkeys(payload.community_refs))
    guild_ids = await identity_refs.resolve_billing_refs(refs, IdentityEntity.guild)

    names: list[BillingCommunityNameRead] = []
    burned = False
    for ref in refs:
        guild_id = guild_ids.get(ref)
        if guild_id is None:
            continue
        await set_rls_context(session, Billing(guild_id))
        if not burned:
            await _burn_jti(session, claims)
            burned = True
        name = await billing_service.guild_display_name(session, guild_id)
        if name is not None:
            names.append(BillingCommunityNameRead(community_ref=ref, name=name))
    if burned:
        await session.commit()  # persist the one-shot jti redemption
    return BillingCommunityNamesRead(names=names)


@router.post("/community-status", response_model=BillingCommunityStatusRead)
async def community_status(
    request: Request, session: SessionDep
) -> BillingCommunityStatusRead:
    """Signed read: one guild's lifecycle status, ``deleted`` included.

    Only a purged guild 404s, with the jti unredeemed.
    """
    claims, payload = await _verify_and_parse(request, BillingCommunityStatusRequest)
    guild_id = await _resolve_guild(payload.community_ref)
    await set_rls_context(session, Billing(guild_id))
    await _burn_jti(session, claims)

    guild_status = await billing_service.guild_lifecycle_status(session, guild_id)
    if guild_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.COMMUNITY_NOT_FOUND,
        )
    await session.commit()  # persist the one-shot jti redemption
    return BillingCommunityStatusRead(
        community_ref=payload.community_ref, status=guild_status
    )


@router.post("/usage", response_model=BillingUsageRead)
async def community_usage(request: Request, session: SessionDep) -> BillingUsageRead:
    """Signed read: current stored bytes and member count for one guild.

    Envelope-verified and jti-burned on the billing session like the other
    reads; the actual ``SUM(uploads.size_bytes)`` and membership count run on a
    system session from the guild's cohort (the billing role can reach neither).
    A missing guild 404s with the jti unredeemed (retryable).
    """
    claims, payload = await _verify_and_parse(request, BillingUsageRequest)
    guild_id = await _resolve_guild(payload.community_ref)
    await set_rls_context(session, Billing(guild_id))
    await _burn_jti(session, claims)
    usage = await billing_service.guild_usage(guild_id)
    await session.commit()  # persist the one-shot jti redemption
    return BillingUsageRead(
        community_ref=payload.community_ref,
        usage_bytes=usage.usage_bytes,
        member_count=usage.member_count,
        guest_count=usage.guest_count,
    )


@router.post("/plugin-entitlement", response_model=BillingPluginEntitlementRead)
async def plugin_entitlement(
    request: Request, session: SessionDep
) -> BillingPluginEntitlementRead:
    """The current entitlement statement for one community and listing.

    The body is ``{"statement": "<jws>"}``, a statement the issuer signed. Its
    claims name the community, the listing, the version and the values; the
    signature is left to the plug-in, which holds the issuer's key. A statement
    that is not one (wrong header, issuer or claims) is refused (422
    ``INVALID_STATEMENT``) with nothing consumed.

    Taken only for a listing whose package names terms for it here: any other
    listing is refused (409) with nothing consumed. A version higher than the
    one held replaces it, and the statement is handed, exactly as sent, to the
    installed plug-in as its ``entitlement`` hook; an equal or lower one
    changes nothing (``applied: false``), so a retry is harmless. A plug-in
    that is not installed is handed it when it is.

    The jti is burned and committed on the billing session first; the
    statement is written on the system engine, which the billing role does not
    reach.
    """
    claims, payload = await _verify_and_parse(request, BillingPluginEntitlementApply)
    issued = payload.claims
    guild_id = await _resolve_guild(issued.community_ref)
    if await plugin_entitlements.listing_terms(issued.listing_uid) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=BillingMessages.LISTING_HAS_NO_TERMS,
        )
    await set_rls_context(session, Billing(guild_id))
    await _burn_jti(session, claims)
    if await billing_service.guild_lifecycle_status(session, guild_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.COMMUNITY_NOT_FOUND,
        )
    await session.commit()  # persist the one-shot jti redemption
    stored = await plugin_entitlements.store_statement(
        guild_id,
        issued.listing_uid,
        statement=payload.statement,
        version=issued.version,
        values=issued.values,
    )
    if stored.applied:
        post_commit.spawn(
            plugin_entitlements.deliver_entitlement(guild_id, issued.listing_uid)
        )
    return BillingPluginEntitlementRead(
        listing_uid=issued.listing_uid,
        version=stored.version,
        applied=stored.applied,
    )
