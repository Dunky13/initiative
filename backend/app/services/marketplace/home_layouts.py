"""What a home-layout listing is allowed to publish.

A home layout is a page of widgets somebody can add to their own home as a new
view: which widgets, where each sits on the twelve-column grid, and the few
options that mean the same on anybody's page (how far ahead to look, which
tools to list, whether the clock is a timer). It carries no data and points at
nothing — the widgets read the reader's own things when they draw.

Checked against :mod:`app.core.home_widgets`, the server's copy of the
widgets the client draws. A widget this build does not know, an option that
would point at one person's community or list, or two widgets on the same
cells are refused rather than dropped: a publisher should learn their layout
does not fit, not find half of it missing.
"""

from __future__ import annotations

from typing import Any

from app.core.home_widgets import (
    HOME_GRID_COLUMNS,
    HOME_MAX_ROWS,
    HOME_WIDGET_SPECS,
    MAX_HOME_WIDGETS,
    HomeOptionError,
)
from app.services.marketplace.manifest_values import (
    ListingDefinitionError,
    fail,
    require_list,
    require_mapping,
)

__all__ = ["normalize_home_layout_definition"]

#: What a widget's id may be made of: the client keys tiles by it.
_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)
_MAX_ID_LENGTH = 40


def _whole(value: Any, *, what: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        fail(f"{what} must be a whole number")
    if not low <= value <= high:
        fail(f"{what} must be between {low} and {high}")
    return value


def _widget(
    raw: Any, *, index: int, ids: set[str], singles: set[str]
) -> dict[str, Any]:
    what = f"widgets[{index}]"
    entry = require_mapping(raw, what)

    widget_id = entry.get("id")
    if (
        not isinstance(widget_id, str)
        or not 0 < len(widget_id) <= _MAX_ID_LENGTH
        or not set(widget_id) <= _ID_CHARS
    ):
        fail(f"{what}.id must be a short name of letters, digits, - and _")
    if widget_id in ids:
        fail(f"{what}.id: {widget_id!r} appears twice")
    ids.add(widget_id)

    widget_type = entry.get("type")
    spec = HOME_WIDGET_SPECS.get(widget_type) if isinstance(widget_type, str) else None
    if spec is None:
        fail(f"{what}.type: {widget_type!r} is not a home widget")
    if spec.single:
        if widget_type in singles:
            fail(f"{what}.type: a page holds one {widget_type} widget")
        singles.add(widget_type)

    grid = require_mapping(entry.get("grid"), f"{what}.grid")
    w = _whole(
        grid.get("w"), what=f"{what}.grid.w", low=spec.min_w, high=HOME_GRID_COLUMNS
    )
    h = _whole(grid.get("h"), what=f"{what}.grid.h", low=spec.min_h, high=HOME_MAX_ROWS)
    x = _whole(grid.get("x"), what=f"{what}.grid.x", low=0, high=HOME_GRID_COLUMNS - w)
    y = _whole(
        grid.get("y"),
        what=f"{what}.grid.y",
        low=0,
        high=HOME_MAX_ROWS * MAX_HOME_WIDGETS,
    )

    cleaned: dict[str, Any] = {
        "id": widget_id,
        "type": widget_type,
        "grid": {"x": x, "y": y, "w": w, "h": h},
    }

    options = entry.get("options")
    if options is not None:
        options = require_mapping(options, f"{what}.options")
        kept: dict[str, Any] = {}
        for key, value in options.items():
            check = spec.options.get(key)
            if check is None:
                fail(
                    f"{what}.options.{key}: a published {widget_type} widget carries no {key}"
                )
            try:
                kept[key] = check(value)
            except HomeOptionError as exc:
                fail(f"{what}.options.{key}: {exc}")
        # Written only when there are some, so a plain widget stays plain.
        if kept:
            cleaned["options"] = kept
    return cleaned


def _check_overlaps(widgets: list[dict[str, Any]]) -> None:
    taken: dict[tuple[int, int], str] = {}
    for widget in widgets:
        grid = widget["grid"]
        for cx in range(grid["x"], grid["x"] + grid["w"]):
            for cy in range(grid["y"], grid["y"] + grid["h"]):
                other = taken.get((cx, cy))
                if other is not None:
                    fail(
                        f"widgets {other!r} and {widget['id']!r} sit on the same cells"
                    )
                taken[(cx, cy)] = widget["id"]


def normalize_home_layout_definition(definition: Any) -> dict[str, Any]:
    """Validate and canonicalize a home layout's definition."""
    body = require_mapping(definition, "definition")

    schema_version = body.get("schema_version")
    if schema_version != 1:
        raise ListingDefinitionError(
            f"unsupported home layout schema_version {schema_version!r}"
        )
    kind = body.get("kind")
    if kind != "home_layout":
        raise ListingDefinitionError(
            f"definition.kind {kind!r} does not match the listing kind"
        )

    raw = require_list(body.get("widgets"), "widgets", MAX_HOME_WIDGETS)
    if not raw:
        raise ListingDefinitionError("a home layout holds at least one widget")

    ids: set[str] = set()
    singles: set[str] = set()
    widgets = [
        _widget(entry, index=index, ids=ids, singles=singles)
        for index, entry in enumerate(raw)
    ]
    _check_overlaps(widgets)
    return {"schema_version": 1, "kind": "home_layout", "widgets": widgets}
