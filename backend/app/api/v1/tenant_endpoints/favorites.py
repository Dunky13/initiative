"""Stars on tools: any tool, in any community the reader is in.

Starring is community-addressed (``/c/{community_id}/favorites/{tool}/{id}``):
per-schema ids are only unique within a community, and starring takes read
access, the same the tool's own page takes. A community's own list serves its
sidebar and the stars on its pages; ``/me/favorites`` gathers every
community's for the home page, the way the recents bar does — names and icons
only, each community's read inside that community's routed session.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, status
from sqlmodel import select

from app.api import resource_access
from app.api.deps import CurrentUser, GuildContextDep, RLSSessionDep, UserSessionDep
from app.core.tools import Tool
from app.db.session import require_guild_context
from app.models.platform.guild import GuildMembership
from app.schemas.tenant.favorite import FavoriteItemRead
from app.services.cross_guild import gather_across_guilds
from app.services.tenant import favorites as favorites_service
from app.services.tenant.tool_items import load_tool_items

#: ``/c/{community_id}/favorites``: one community's stars, and starring.
guild_router = APIRouter()
#: ``/me/favorites``: every community's.
me_router = APIRouter()


async def _community_favorites(session, user_id: int) -> List[FavoriteItemRead]:
    """This community's stars that the reader may still read, newest first.
    Must run in the community's routed session."""
    context = require_guild_context(session)
    rows = await favorites_service.list_favorites(session, user_id=user_id)
    if not rows:
        return []
    loaded = await load_tool_items(
        session, ((row.entity_type, row.entity_id) for row in rows)
    )
    items: List[FavoriteItemRead] = []
    for row in rows:
        item = loaded.get((row.entity_type, row.entity_id))
        if item is None:
            continue
        items.append(
            # Trusted columns, already sanitized on the way in: constructed so
            # they are not escaped a second time on the way out.
            FavoriteItemRead.model_construct(
                entity_type=item.tool,
                entity_id=item.entity_id,
                community_id=context.guild_id,
                initiative_id=item.initiative_id,
                name=item.name,
                favorited_at=row.created_at,
                **item.extra,
            )
        )
    return items


@guild_router.get("", response_model=List[FavoriteItemRead])
async def list_community_favorites(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> List[FavoriteItemRead]:
    """The reader's stars in this community, newest first."""
    del guild_context  # validation + routing happen in the dependency
    return await _community_favorites(session, current_user.id)


@guild_router.post("/{tool}/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_favorite(
    tool: Tool,
    entity_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Star a tool. Takes read access, as the tool's page does, and refuses in
    its tool's own words. Starring one already starred changes nothing. A
    platform grantee is not a member, so nothing is kept for them."""
    row = await resource_access.load_authorized(
        session, tool, entity_id, current_user, guild_context
    )
    if guild_context.is_pam:
        return
    await favorites_service.add(
        session, user_id=current_user.id, tool=tool, entity_id=row.id
    )


@guild_router.delete("/{tool}/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    tool: Tool,
    entity_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Take a star off. Idempotent, and asks nothing of the tool: a star on
    something the reader can no longer open can still be taken off."""
    del guild_context
    await favorites_service.remove(
        session, user_id=current_user.id, tool=tool, entity_id=entity_id
    )


@me_router.get("/favorites", response_model=List[FavoriteItemRead])
async def list_my_favorites(
    session: UserSessionDep,
    current_user: CurrentUser,
) -> List[FavoriteItemRead]:
    """The reader's stars in every community they are in, newest first."""
    member_guilds = list(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == current_user.id
                )
            )
        ).all()
    )

    async def _fetch(guild_session, guild_id: int) -> List[FavoriteItemRead]:  # type: ignore[no-untyped-def]
        del guild_id
        return await _community_favorites(guild_session, current_user.id)

    items = await gather_across_guilds(session, current_user.id, member_guilds, _fetch)
    items.sort(key=lambda item: item.favorited_at, reverse=True)
    return items
