from typing import List, Optional

from pydantic import ConfigDict, Field

from app.core.task_types import LAYOUT_SHAPES
from app.schemas.base import SanitizedBaseModel
from app.schemas.tenant.task_status import HEX_COLOR_PATTERN

#: One of :data:`app.core.task_types.LAYOUT_SHAPES`.
_SHAPE_PATTERN = "^(" + "|".join(LAYOUT_SHAPES) + ")$"


class TaskTypeRead(SanitizedBaseModel):
    """One kind of task in a project, and the shape its page is drawn as until
    the page is changed."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    project_id: int
    name: str
    position: int
    is_default: bool
    color: str
    icon: str
    layout_preset: str


class TaskTypeCreate(SanitizedBaseModel):
    name: str = Field(min_length=1, max_length=100)
    position: Optional[int] = Field(default=None, ge=0)
    is_default: bool = False
    color: Optional[str] = Field(
        default=None, min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN
    )
    icon: Optional[str] = Field(default=None, min_length=1, max_length=64)
    #: Another of the project's types to start from: its shape, colour and icon
    #: unless given, and its page as it is laid out.
    start_from_type_id: Optional[int] = Field(default=None, gt=0)
    layout_preset: Optional[str] = Field(default=None, pattern=_SHAPE_PATTERN)


class TaskTypeUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    position: Optional[int] = Field(default=None, ge=0)
    is_default: Optional[bool] = None
    color: Optional[str] = Field(
        default=None, min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN
    )
    icon: Optional[str] = Field(default=None, min_length=1, max_length=64)
    layout_preset: Optional[str] = Field(default=None, pattern=_SHAPE_PATTERN)


class TaskTypeDeleteRequest(SanitizedBaseModel):
    #: Where its tasks go; the project's default (or, deleting the default, the
    #: first other type) when not given.
    fallback_type_id: Optional[int] = None


class TaskTypeReorderItem(SanitizedBaseModel):
    id: int
    position: int


class TaskTypeReorderRequest(SanitizedBaseModel):
    items: List[TaskTypeReorderItem]
