"""`/api/v1/recents` — mixed-type recent items for the header tabs bar.

The tabs bar is special-cased by design (guild-context design doc §3.5a): it
renders entities from ANY of the user's guilds regardless of the current
context, but only their render metadata (name/icon/type) — never their
content. So the list runs under USER context and gathers each member guild's
``recent_views`` from its own schema, enriches + permission-filters inside
that guild's routed context, and merges by ``last_viewed_at``. Opening a tab
navigates into the entity's guild (which sets the server-held context) before
any content is fetched.

Opening and closing a tab are guild-addressed (``/c/{community_id}/recents/…``):
per-schema ids are only unique within a guild.
"""

from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, status
from sqlmodel import select

from app.api import resource_access
from app.db.session import require_guild_context
from app.api.deps import (
    RLSSessionDep,
    UserSessionDep,
    get_current_active_user,
    GuildContextDep,
)
from app.models.platform.guild import GuildMembership
from app.models.tenant.recent_view import RecentView, ViewSource
from app.models.platform.user import User
from app.schemas.tenant.recent_view import RecentItemRead, RecentKind, RecentViewWrite
from app.services.tenant import recent_views as recent_views_service
from app.services.cross_guild import gather_across_guilds
from app.services.tenant.tool_items import load_tool_items
from app.services.tenant.recent_views import RecentEntityType


router = APIRouter()
# Guild-scoped sub-router: opening and closing a tab mount under
# /c/{community_id}/recents. The cross-guild tabs-bar list stays on the top-level
# router above — fully separate endpoints.
guild_router = APIRouter()


async def _enrich_recent_rows(
    session,
    current_user: User,
    rows: List[RecentView],
) -> List[RecentItemRead]:
    """Resolve one guild's recent_views rows into render-only tab items.

    Must run inside that guild's routed context — ids are per-schema, and the
    routed session is what decides: a thing the reader may not read does not
    load, so its tab is dropped, the same verdict its detail page reaches.
    """
    context = require_guild_context(session)
    loaded = await load_tool_items(
        session, ((row.entity_type, row.entity_id) for row in rows)
    )
    items: List[RecentItemRead] = []
    for row in rows:
        item = loaded.get((row.entity_type, row.entity_id))
        if item is None:
            continue
        items.append(
            # ``model_construct`` skips the SanitizedBaseModel validator so
            # trusted DB columns (already sanitized on input) aren't
            # double-escaped on the way out — e.g. ``Foo & Bar`` would
            # otherwise round-trip as ``Foo &amp; Bar``.
            RecentItemRead.model_construct(
                # The member, not its value: ``model_construct`` skips
                # validation, so whatever is passed is what the field holds and
                # what the serializer is later handed.
                entity_type=RecentEntityType(item.tool.value),
                entity_id=item.entity_id,
                community_id=context.guild_id,
                initiative_id=item.initiative_id,
                name=item.name,
                last_viewed_at=row.last_viewed_at,
                **item.extra,
            )
        )
    return items


@router.get("/", response_model=List[RecentItemRead])
async def list_recents(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[RecentItemRead]:
    """Recent tabs across every guild the user belongs to (names only).

    Works identically with a guild context or in personal mode: the result
    depends only on who is asking, never on what they're currently viewing.
    """
    # The guilds to visit, from the shared memberships table (the user context
    # shows the caller's own rows).
    member_guilds = [
        gid
        for gid in (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == current_user.id
                )
            )
        ).all()
    ]

    limit = recent_views_service.clamp_recent_limit(current_user.recent_tabs_limit)

    async def _fetch(guild_session, guild_id: int) -> List[RecentItemRead]:  # type: ignore[no-untyped-def]
        rows = await recent_views_service.list_recent_views(
            guild_session, user_id=current_user.id, limit=limit
        )
        if not rows:
            return []
        return await _enrich_recent_rows(guild_session, current_user, list(rows))

    items = await gather_across_guilds(session, current_user.id, member_guilds, _fetch)
    items.sort(key=lambda item: item.last_viewed_at, reverse=True)
    return items[:limit]


@guild_router.post("/{entity_type}/{entity_id}", response_model=RecentViewWrite)
async def record_recent(
    entity_type: RecentKind,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    source: ViewSource = ViewSource.direct,
) -> RecentViewWrite:
    """Record that the caller opened this: a tool, which becomes a tab, or
    something inside one, which does not.

    Takes read access, the same the thing's own page takes, and refuses in its
    tool's own words. A PAM grantee's browsing is transient by design and is
    not stored.
    """
    row = await resource_access.load_kind(
        session, entity_type.value, entity_id, current_user, guild_context
    )
    record = await recent_views_service.record_view(
        session,
        user_id=current_user.id,
        entity_type=entity_type.value,
        entity_id=row.id,
        source=source,
        persist=not guild_context.is_pam,
    )
    return RecentViewWrite(
        entity_type=entity_type,
        entity_id=row.id,
        last_viewed_at=record.last_viewed_at,
        source=source,
    )


@guild_router.delete(
    "/{entity_type}/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_recent(
    entity_type: RecentEntityType,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Close a tab: delete the caller's own recent-view row.

    Guild-scoped — mounted under /c/{community_id}/recents because a tab can belong
    to any of the user's guilds and per-schema ids are only unique within a
    guild. Idempotent.
    """
    del guild_context  # validation + routing happen in the dependency
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
