"""Schemas for stars on tools."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import ConfigDict

from app.core.tools import Tool
from app.schemas.base import SanitizedBaseModel


class FavoriteItemRead(SanitizedBaseModel):
    """One starred tool, as a list of them shows it: enough to draw its icon
    and link to it without a fetch per kind, and nothing of its content."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    entity_type: Tool
    entity_id: int
    community_id: int
    # The initiative it lives in, which its URL addresses. NULL for a
    # community-level tool — only calendars have any.
    initiative_id: Optional[int] = None
    name: str
    favorited_at: datetime
    # Projects: the emoji on the project itself.
    icon: Optional[str] = None
    # Files: what picks the file's own icon and colour.
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    original_filename: Optional[str] = None
