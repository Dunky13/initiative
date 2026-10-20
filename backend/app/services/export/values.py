"""A list's values as table cells, written by the kind of value they are.

Every table export (tasks, a project's report, a queue, a counter group)
draws ``columns`` and fills each cell from its row: one :class:`Column` per
field, named for the field as the field registry names it (``fields.<name>``
in the exports catalogue). What a cell holds is decided by the kind of value,
once, here: a date as a date, a person by name, an option by its label. So the
same field reads the same in every export.

Cells are text, except numbers, which stay numbers so a spreadsheet keeps them
typed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date as Date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.core.user_display import display_name
from app.models.tenant.property import PropertyType
from app.services.export.i18n import et


@dataclass(frozen=True)
class Column:
    """One column of a table export: its key in a row, its header, how wide
    the PDF draws it, and what fills its cell from a row."""

    key: str
    label: str
    cell: Callable[[Any], Any]
    width: str = "1fr"


def head(columns: Sequence[Column]) -> list[dict[str, str]]:
    """The ``columns`` a template draws."""
    return [{"key": c.key, "label": c.label, "width": c.width} for c in columns]


def cells(columns: Sequence[Column], row: Any) -> dict[str, Any]:
    """One row's cells, by column key; a value there is none of empty."""
    return {
        column.key: "" if (value := column.cell(row)) is None else value
        for column in columns
    }


def label(field: str, locale: str) -> str:
    """A field's header, by the name the field registry gives it."""
    return et(f"fields.{field}", locale)


def text(value: Any) -> str:
    return "" if value is None else str(value)


def number(value: Any) -> int | float | None:
    """A number as a spreadsheet keeps it: integral values as ints, the rest
    as floats. ``NUMERIC`` arrives as ``Decimal``, which neither JSON nor a
    sheet takes, and reads badly as text (``5.0000000000``)."""
    if value is None or isinstance(value, bool):
        return None
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    if decimal == decimal.to_integral_value():
        return int(decimal)
    return float(decimal)


def date(value: Any) -> str:
    """A date, or the day a moment falls on, as ``YYYY-MM-DD``."""
    if isinstance(value, (datetime, Date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str) and value:
        return value[:10]
    return ""


def yes_no(value: Any, locale: str) -> str:
    return et("values.yes" if value else "values.no", locale)


def property_value(summary: Any, locale: str) -> Any:
    """A custom property's value as its type shows it: an option by its
    label, a person by name, a checkbox as yes or no."""
    if summary is None or summary.value is None:
        return ""
    value = summary.value
    labels = {o.value: o.label for o in summary.options or ()}
    kind = summary.type
    if kind is PropertyType.select:
        return labels.get(value, value)
    if kind is PropertyType.multi_select:
        return ", ".join(labels.get(each, each) for each in value)
    if kind is PropertyType.user_reference:
        if not isinstance(value, dict):
            return ""
        return display_name(
            SimpleNamespace(
                username=value.get("username") or "",
                discriminator=value.get("discriminator") or 0,
                display_name=value.get("display_name"),
            )
        )
    if kind is PropertyType.checkbox:
        return yes_no(value, locale)
    if kind in (PropertyType.date, PropertyType.datetime):
        return date(value)
    if kind is PropertyType.number:
        return number(value)
    return text(value)


def plugin_value(value: Any, kind: str, locale: str) -> Any:
    """A plug-in field's value as text: a list's elements one after another,
    a value kept beside a state by its value."""
    if isinstance(value, list):
        return ", ".join(
            str(cell) for cell in (plugin_value(v, kind, locale) for v in value) if cell
        )
    if isinstance(value, dict):
        for key in ("value", "title", "label", "name", "url"):
            if value.get(key) is not None:
                return plugin_value(value[key], kind, locale)
        return ""
    if kind == "checkbox":
        return yes_no(value, locale)
    if kind in ("number", "progress"):
        return number(value)
    if kind in ("date", "datetime"):
        return date(value)
    return text(value)
