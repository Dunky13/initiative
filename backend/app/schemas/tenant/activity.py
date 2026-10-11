"""The activity feed's entries, as the API sends them."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict

from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.schemas.base import MentionStr, SanitizedBaseModel
from app.schemas.platform.user import UserPublic
from app.services.tenant.activity_feed import Verb


class ActivityEntry(SanitizedBaseModel):
    """One item, and what people did to it lately."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    entity_type: SearchEntityType
    entity_id: int
    title: MentionStr
    initiative_id: Optional[int] = None
    initiative_name: Optional[str] = None
    #: The tool it is in, and what that is called. ``tool_title`` is None for an
    #: item that IS a tool.
    tool: Optional[Tool] = None
    tool_id: Optional[int] = None
    tool_title: Optional[str] = None
    #: When the latest of it happened.
    latest: datetime
    #: What happened, each once.
    verbs: List[Verb]
    #: The people who did it, latest first, up to three.
    actors: List[UserPublic]
    #: How many people did, the ones named included.
    actor_count: int


class ActivityFeedPage(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[ActivityEntry]
    page: int
    page_size: int
    has_next: bool
