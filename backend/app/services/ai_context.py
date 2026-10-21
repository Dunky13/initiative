"""What an AI feature tells the model about the task it is asked about.

Everything is read on the member's own session, so what they cannot read never
reaches a prompt. The reads are the app's own read shapes, trimmed as the MCP
server trims its results (:mod:`app.services.compact`), and sent as compact
JSON.

The task, its project and the open tasks linked to it always go in. Its
comments fill what is left of the budget, newest first; when they do not all
fit, the result says how many were read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.identity_boundary import STORED_MENTION
from app.core.search import SearchEntityType
from app.core.user_display import display_name
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.schemas.tenant.task import TaskRead
from app.services import compact
from app.services.tenant import comments as comments_service
from app.services.tenant import relationships as relationships_service
from app.services.tenant import task_queries

#: Roughly how many characters a token holds, to keep a prompt near its budget.
_CHARS_PER_TOKEN = 4
_COMMENT_PAGE = 100

#: What a model is told of a task: the fields that describe the work.
_TASK_FIELDS: dict[str, Any] = {
    "title": True,
    "description": True,
    "priority": True,
    "start_date": True,
    "due_date": True,
    "task_status": {"name", "category"},
    "task_type": {"name"},
    "assignees": {"__all__": {"username", "display_name"}},
    "checklist": {"__all__": {"text", "done"}},
    "tags": {"__all__": {"name"}},
    "properties": {"__all__": {"name", "value"}},
}
#: A property's value is the member's own, passed through as it is.
_FREE_FORM = frozenset({"value"})


@dataclass(frozen=True)
class TaskContext:
    """The task as the prompt carries it."""

    #: Compact JSON: the task, its project, its open linked tasks and the
    #: comments that fit.
    data: str
    comments_read: int
    comments_total: int


async def task_context(
    session: AsyncSession,
    task: Task,
    *,
    user: User,
    guild_id: int,
    budget: int,
) -> TaskContext:
    """``task`` as ``user`` reads it, within about ``budget`` tokens."""
    loaded = await task_queries.load_task(session, task.id)  # type: ignore[arg-type]
    read = TaskRead.model_validate(loaded)
    parts: dict[str, Any] = {
        "task": read.model_dump(mode="json", include=_TASK_FIELDS),
        "project": {"name": task.project.name, "description": task.project.description},
        "linked_tasks": await _open_linked_tasks(session, task.id),  # type: ignore[arg-type]
    }
    room = budget * _CHARS_PER_TOKEN - len(_dumps(compact.trim(parts, _FREE_FORM)))
    comments, finished = await _recent_comments(
        session, task, user=user, guild_id=guild_id, room=room
    )
    parts["comments"] = comments
    data = await _named(session, _dumps(compact.trim(parts, _FREE_FORM)))
    return TaskContext(
        data=data,
        comments_read=len(comments),
        comments_total=len(comments) if finished else read.comment_count,
    )


def _dumps(value: Any) -> str:
    """Compact JSON that cannot close the tag it is sent in."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


async def _open_linked_tasks(session: AsyncSession, task_id: int) -> list[str]:
    """The unfinished tasks linked to this one, each as how it is linked."""
    anchor = relationships_service.Endpoint(SearchEntityType.task, task_id)
    edges = await relationships_service.list_for_entity(
        session, anchor, other_kind=SearchEntityType.task
    )
    links: dict[int, list[str]] = {}
    for edge in edges:
        outbound = edge.source_node == anchor.node
        other = edge.target_id if outbound else edge.source_id
        links.setdefault(other, []).append(
            f"this task {edge.relationship_type} it"
            if outbound
            else f"it {edge.relationship_type} this task"
        )
    if not links:
        return []
    rows = await session.exec(
        select(Task.id, Task.title)
        .join(TaskStatus, col(TaskStatus.id) == Task.task_status_id)
        .where(
            col(Task.id).in_(links),
            TaskStatus.category != TaskStatusCategory.done,
            col(Task.archived_at).is_(None),
            col(Task.deleted_at).is_(None),
        )
        .order_by(col(Task.id))
    )
    return [
        f"{title} ({'; '.join(links[other])})"
        for other, title in rows.all()  # type: ignore[misc]
    ]


async def _recent_comments(
    session: AsyncSession, task: Task, *, user: User, guild_id: int, room: int
) -> tuple[list[dict[str, Any]], bool]:
    """The newest comments that fit in ``room`` characters, oldest first, and
    whether that is all of them."""
    taken: list[tuple[datetime, int, dict[str, Any]]] = []
    cursor: str | None = None
    while True:
        page = await comments_service.list_comments(
            session,
            user=user,
            guild_id=guild_id,
            targets={"task_id": task.id},
            limit=_COMMENT_PAGE,
            cursor=cursor,
        )
        for comment in reversed(page.comments):
            read = comments_service.serialize_comment(comment, viewer_id=user.id)
            if read.removed is not None:
                continue
            row = compact.trim(
                {
                    "by": read.imported_author_name or display_name(read.author),
                    "at": read.created_at.isoformat(timespec="minutes"),
                    "text": read.content,
                }
            )
            room -= len(_dumps(row)) + 1
            if room < 0:
                return _oldest_first(taken), False
            taken.append((read.created_at, read.id, row))
        if page.next_cursor is None:
            return _oldest_first(taken), True
        cursor = page.next_cursor


def _oldest_first(
    taken: list[tuple[datetime, int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    return [row for *_, row in sorted(taken, key=lambda t: (t[0], t[1]))]


async def _named(session: AsyncSession, data: str) -> str:
    """``data`` with each mention as the name the person goes by here."""
    ids = {int(user_id) for _, user_id in STORED_MENTION.findall(data)}
    if not ids:
        return data
    profiles = await session.exec(
        select(MemberProfile).where(col(MemberProfile.id).in_(ids))
    )
    names = {profile.id: display_name(profile) for profile in profiles.all()}

    def name(match: Any) -> str:
        shown = names.get(int(match.group(2))) or match.group(1) or "someone"
        return "@" + _dumps(shown)[1:-1]

    return STORED_MENTION.sub(name, data)
