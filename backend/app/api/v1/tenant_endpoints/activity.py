"""The community's activity feed."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import GuildContextDep, RLSSessionDep
from app.schemas.tenant.activity import ActivityEntry, ActivityFeedPage, ActivityQuery
from app.services.tenant import activity_feed

router = APIRouter()


@router.get("/", response_model=ActivityFeedPage)
async def read_activity(
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    query: Annotated[ActivityQuery, Query()],
) -> ActivityFeedPage:
    """What people changed lately in what the reader can open, one entry per
    item, ordered for the reader."""
    entries, has_next = await activity_feed.feed(
        session,
        reader_id=guild_context.user_id,
        view=query.view,
        initiative_id=query.initiative_id,
        tool=query.tool,
        tool_id=query.tool_id,
        page=query.page,
        page_size=query.page_size,
    )
    return ActivityFeedPage(
        items=[ActivityEntry.model_validate(entry) for entry in entries],
        page=query.page,
        page_size=query.page_size,
        has_next=has_next,
    )
