"""The community's activity feed."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import GuildContextDep, RLSSessionDep
from app.core.messages import ActivityMessages
from app.core.tools import Tool
from app.schemas.tenant.activity import ActivityEntry, ActivityFeedPage
from app.services.tenant import activity_feed
from app.services.tenant.activity_feed import FeedView

router = APIRouter()


@router.get("/", response_model=ActivityFeedPage)
async def read_activity(
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    view: FeedView = FeedView.all,
    initiative_id: Optional[int] = Query(default=None),
    tool: Optional[Tool] = Query(default=None),
    tool_id: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=activity_feed.PAGE_SIZE, ge=1, le=50),
) -> ActivityFeedPage:
    """What people changed lately in what the reader can open, one entry per
    item, ordered for the reader. Narrowed to one initiative, or to one tool
    (``tool`` with ``tool_id``)."""
    if (tool is None) != (tool_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ActivityMessages.TOOL_NEEDS_ITS_ID,
        )
    entries, has_next = await activity_feed.feed(
        session,
        reader_id=guild_context.user_id,
        view=view,
        initiative_id=initiative_id,
        tool=tool,
        tool_id=tool_id,
        page=page,
        page_size=page_size,
    )
    return ActivityFeedPage(
        items=[ActivityEntry.model_validate(entry) for entry in entries],
        page=page,
        page_size=page_size,
        has_next=has_next,
    )
