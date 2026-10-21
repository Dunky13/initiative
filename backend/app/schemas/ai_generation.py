"""AI Generation request and response schemas."""

from pydantic import ConfigDict

from app.schemas.base import RawTextStr, SanitizedBaseModel


class _WrittenFromComments(SanitizedBaseModel):
    """How many of the task's comments a suggestion was written from: the
    newest, as many as fit. Fewer than ``comments_total`` when some did not."""

    comments_read: int
    comments_total: int


class GenerateChecklistResponse(_WrittenFromComments):
    """Suggested checklist lines, as text — the caller decides which to keep."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[str]


class GenerateDescriptionResponse(_WrittenFromComments):
    """A description for the reader to start from."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    description: RawTextStr


class GenerateFileSummaryResponse(SanitizedBaseModel):
    """Response schema for file summarization."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    summary: RawTextStr
