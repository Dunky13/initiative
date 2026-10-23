"""Shared query schemas for filtering, sorting, and pagination."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel


class FilterOp(str, Enum):
    """Comparison operators for filter conditions.

    Negation is handled by the ``negate`` flag on FilterCondition,
    not by separate operators.
    """

    eq = "eq"
    lt = "lt"
    lte = "lte"
    gt = "gt"
    gte = "gte"
    in_ = "in_"
    ilike = "ilike"
    is_null = "is_null"


class DateBucket(str, Enum):
    """What a date is grouped by: the calendar's day, week, month, quarter or
    year it falls in. A week starts on Monday, as Postgres counts one."""

    day = "day"
    week = "week"
    month = "month"
    quarter = "quarter"
    year = "year"


class GroupRead(SanitizedBaseModel):
    """One group of a grouped list."""

    #: What names it: a row id (a status's, a tag's, a person's), an option, a
    #: bucket's first day, or ``""`` for the rows with no value.
    key: str
    #: What it is called where that is somebody's text (a tag's name, a
    #: person's); ``null`` where the reader's language names it.
    label: str | None = None


class GroupsResponse(SanitizedBaseModel):
    """A list's groups by one field, and the groups each row is in."""

    #: Every group, in the order the list shows them: the ones a row is in,
    #: and the ones a closed vocabulary has whether or not one is.
    groups: list[GroupRead]
    #: The keys of the groups each row is in, by row id. A row that is in
    #: none is in the ``""`` group.
    rows: dict[int, list[str]]


class SortDir(str, Enum):
    asc = "asc"
    desc = "desc"


class FilterCondition(SanitizedBaseModel):
    """A single field comparison.

    Set ``negate=True`` to invert the result::

        # name != 'bob'
        FilterCondition(field="name", value="bob", negate=True)

        # priority NOT IN ('low', 'medium')
        FilterCondition(field="priority", op=FilterOp.in_, value=["low", "medium"], negate=True)
    """

    field: str
    op: FilterOp = FilterOp.eq
    value: Any = None
    negate: bool = False


class FilterGroup(SanitizedBaseModel):
    """Group of conditions combined with AND or OR logic.

    Set ``negate=True`` to invert the entire group::

        # NOT (status = 'archived' OR status = 'deleted')
        FilterGroup(
            logic="or",
            negate=True,
            conditions=[
                FilterCondition(field="status", value="archived"),
                FilterCondition(field="status", value="deleted"),
            ],
        )

    Groups can be nested::

        # is_active = true AND (role = 'operator' OR role = 'owner')
        FilterGroup(
            logic="and",
            conditions=[
                FilterCondition(field="is_active", value=True),
                FilterGroup(
                    logic="or",
                    conditions=[
                        FilterCondition(field="role", value="operator"),
                        FilterCondition(field="role", value="owner"),
                    ],
                ),
            ],
        )
    """

    logic: Literal["and", "or"] = "and"
    negate: bool = False
    conditions: list[FilterCondition | FilterGroup]


class SortField(SanitizedBaseModel):
    field: str
    dir: SortDir = SortDir.asc


class PageMeta(SanitizedBaseModel):
    """The page fields of every paginated list response — the keys
    ``app.db.query.build_paginated_response`` fills. A subclass declares its
    ``items`` and any extras."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool
