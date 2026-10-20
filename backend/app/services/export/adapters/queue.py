"""Queue source adapter: importable backup envelope (json) and turn-order
reports (pdf/csv/xlsx/md).

The json envelope round-trips the queue's own state — its tags by name, and
items with rotation order, colors, notes, visibility, held/current markers and
tags by name.
Member assignments and linked files/tasks ship as display text only
(names and titles): they reference guild-local rows that won't exist wherever
the envelope is imported, so an import can't rebind them.

The report formats list every item in rotation order (position descending,
matching the on-screen timeline) with hidden/held/current flagged in a status
column, so the printout is the full queue, not just the visible rotation.
Markdown renders as a numbered turn-order list rather than a table.

Access rule for every format: READ on the queue (exporting is a formatted
read), enforced by ``ToolExportAdapter.fetch`` at both count and build time,
under the caller's RLS session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import Related, RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.file import File
from app.models.tenant.task import Task
from app.services.tenant import relationships
from app.models.tenant.queue import Queue, QueueItem
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
    export_stem,
    related_reach,
)
from app.schemas.tenant.tag import annotated_tags
from app.services.export.contract import RenderItem
from app.services.export.property_values import exported_properties
from app.services.export import values
from app.services.export.i18n import et, export_locale
from app.core.user_display import display_name


class QueueAdapter(ToolExportAdapter):
    tool = Tool.queue
    formats = ("json", "pdf", "csv", "xlsx", "md")

    def rows(self, queue: Queue, /) -> int:
        return len(queue.items)

    async def prepare(
        self, session: AsyncSession, queues: list[Queue], ctx: BuildContext, /
    ) -> "Attachments":
        # Every item across every queue, in one pass: the payload builders below
        # are synchronous and hold no session, and an export of a dozen queues
        # is exactly where a per-item fetch would show.
        return await queue_attachments_for(
            session, [item for queue in queues for item in queue.items]
        )

    async def prepared_reach(
        self, session: AsyncSession, ctx: BuildContext, /
    ) -> set[int]:
        # Only the envelope names what is attached; the reports do not.
        if ctx.format != "json":
            return set()
        attachments: Attachments = ctx.prepared
        return await related_reach(
            session,
            (
                related
                for by_item in (attachments.files, attachments.tasks)
                for items in by_item.values()
                for related in items
            ),
        )

    def item(self, queue: Queue, ctx: BuildContext, /) -> RenderItem:
        return build_queue_item(queue, ctx.format, ctx.user, ctx.now, ctx.prepared)


async def queue_attachments_for(
    session: AsyncSession, items: list[QueueItem]
) -> "Attachments":
    """Files and tasks for many queue items, two queries each."""
    ids = [item.id for item in items if item.id is not None]
    files = await relationships.related_for_many(
        session,
        SearchEntityType.queue_item,
        ids,
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.file,
        model=File,
    )
    tasks = await relationships.related_for_many(
        session,
        SearchEntityType.queue_item,
        ids,
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.task,
        model=Task,
    )
    return Attachments(files=files, tasks=tasks)


@dataclass(frozen=True)
class Attachments:
    """What each queue item has pinned to it, keyed by item id."""

    files: dict[int, list[Related]]
    tasks: dict[int, list[Related]]


def build_queue_item(
    queue: Queue, format: str, user: User, now: datetime, attachments: Attachments
) -> RenderItem:
    items = _rotation_order(queue.items)
    date = now.strftime("%Y-%m-%d")
    if format == "json":
        # The envelope is importable machine data — stays canonical, never
        # localized (translating field keys / enum values breaks import).
        return RenderItem(
            key=envelope_key(Tool.queue, queue.name, date),
            data=_envelope(queue, items, attachments),
        )
    return RenderItem(
        key=export_stem(queue.name, date), data=_report_payload(queue, items, user)
    )


def _rotation_order(items: list[QueueItem]) -> list[QueueItem]:
    """Position descending — the rotation's acting order (see
    ``queues.py:_visible_items_desc``), with id as the deterministic
    tiebreaker the timeline also uses."""
    return sorted(items, key=lambda i: (-i.position, i.id or 0))


def _envelope(
    queue: Queue, items: list[QueueItem], attachments: Attachments
) -> dict[str, Any]:
    return {
        "type": tool_envelope_type(Tool.queue),
        "schema_version": 1,
        "name": queue.name,
        "description": queue.description,
        "is_active": queue.is_active,
        "current_round": queue.current_round,
        "tags": _tags(queue),
        "properties": exported_properties(queue),
        "items": [
            {
                "label": item.label,
                "position": item.position,
                "color": item.color,
                "notes": item.notes,
                "is_visible": item.is_visible,
                "held_at_round": item.held_at_round,
                "is_current": item.id == queue.current_item_id,
                # Informational only: user/file/task ids are guild-local,
                # so an import can't rebind them — names and titles it is.
                "member": _member(item),
                "tags": _tags(item),
                "properties": exported_properties(item),
                "files": sorted(
                    related.entity.name
                    for related in attachments.files.get(item.id, [])
                    if related.entity is not None
                ),
                "tasks": sorted(
                    related.entity.title
                    for related in attachments.tasks.get(item.id, [])
                    if related.entity is not None
                ),
                # What a reference to this item points at across one import.
                "external_ref": f"queue_item:{item.id}",
            }
            for item in items
        ],
    }


def _report_payload(queue: Queue, items: list[QueueItem], user: User) -> dict[str, Any]:
    loc = export_locale(user)
    # Where each item falls in the turn order, its own fields, then what the
    # rotation says of it.
    order = {item.id: n for n, item in enumerate(items, 1)}

    def status(item: QueueItem) -> str:
        flags = []
        if item.id == queue.current_item_id:
            flags.append(et("status.current", loc))
        if item.held_at_round is not None:
            flags.append(et("status.held", loc))
        if not item.is_visible:
            flags.append(et("status.hidden", loc))
        return ", ".join(flags)

    columns = [
        values.Column(
            "order", values.label("order", loc), lambda i: order[i.id], "auto"
        ),
        values.Column("title", values.label("label", loc), lambda i: i.label, "2fr"),
        values.Column(
            "member", values.label("user_id", loc), lambda i: _member(i) or ""
        ),
        values.Column(
            "tags", values.label("tag_ids", loc), lambda i: ", ".join(_tags(i))
        ),
        values.Column(
            "notes",
            values.label("notes", loc),
            lambda i: values.text(i.notes),
            "2fr",
        ),
        values.Column("status", values.label("status", loc), status, "auto"),
    ]
    parts = [et("summary.items", loc, count=len(items))]
    if queue.is_active:
        parts.append(et("round", loc, round=queue.current_round))
    return {
        # The queue name is user data — never translated.
        "title": queue.name,
        "subtitle": " · ".join(parts),
        "footer": et("footer.queue", loc, name=queue.name),
        "page_of": et("pageOf", loc),
        "description": queue.description or "",
        # Markdown renders the rotation as a numbered turn-order list; the
        # other formats consume the columns/rows table.
        "layout": "numbered",
        "columns": values.head(columns),
        "empty_message": et("empty.generic", loc),
        "untitled": et("fallback.untitled", loc),
        "rows": [
            values.cells(columns, item)
            # Not a column: the numbered layout's current marker.
            | {"current": item.id == queue.current_item_id}
            for item in items
        ],
    }


def _member(item: QueueItem) -> str | None:
    if item.user is None:
        return None
    return display_name(item.user) or None


def _tags(row: Queue | QueueItem) -> list[str]:
    return sorted(tag.name for tag in annotated_tags(row))
