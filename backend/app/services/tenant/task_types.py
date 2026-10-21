"""A project's task types: the ones it starts with, which is its default, and
where a task's type goes when the task moves.

Nothing here commits, so a caller can compose it into a larger transaction.
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import col, delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.core.task_types import DEFAULT_TASK_TYPES
from app.models.tenant.task import TaskType
from app.services.tenant.task_statuses import REPAIR_LOCALE


def default_name(key: str, locale: str) -> str:
    """One of the starting types' names, in ``locale`` (English for a
    language the app does not speak)."""
    return translate(f"taskTypes.defaults.{key}", locale, namespace="projects")


async def list_types(session: AsyncSession, project_id: int) -> list[TaskType]:
    result = await session.exec(
        select(TaskType)
        .where(TaskType.project_id == project_id)
        .order_by(col(TaskType.position).asc(), col(TaskType.id).asc())
    )
    return list(result.all())


async def ensure_default_types(
    session: AsyncSession, project_id: int, *, locale: str
) -> list[TaskType]:
    """The project's types, giving it the four it starts with if it has none,
    named in ``locale``: the language of whoever is making the project."""
    existing = await list_types(session, project_id)
    if existing:
        return existing
    created = [
        TaskType(
            project_id=project_id,
            name=default_name(spec.key, locale),
            position=position,
            is_default=position == 0,
            color=spec.color,
            icon=spec.icon,
            layout_preset=spec.shape,
        )
        for position, spec in enumerate(DEFAULT_TASK_TYPES)
    ]
    session.add_all(created)
    await session.flush()
    return created


async def get_default_type(session: AsyncSession, project_id: int) -> TaskType:
    """What a new task in the project is unless it says otherwise. A project
    found with no types is given its starting ones, as it is its statuses: a
    repair, where nobody's language is known."""
    types = await ensure_default_types(session, project_id, locale=REPAIR_LOCALE)
    return next((t for t in types if t.is_default), types[0])


async def get_project_type(
    session: AsyncSession, type_id: int, project_id: int
) -> Optional[TaskType]:
    result = await session.exec(
        select(TaskType).where(
            TaskType.id == type_id, TaskType.project_id == project_id
        )
    )
    return result.one_or_none()


async def name_taken(
    session: AsyncSession,
    project_id: int,
    name: str,
    *,
    excluding: Optional[int] = None,
) -> bool:
    """Whether another of the project's types has this name, whatever its
    case."""
    stmt = select(TaskType.id).where(
        TaskType.project_id == project_id,
        func.lower(TaskType.name) == name.strip().lower(),
    )
    if excluding is not None:
        stmt = stmt.where(TaskType.id != excluding)
    return (await session.exec(stmt)).first() is not None


async def type_for_move(
    session: AsyncSession, task_type_id: int, destination_project_id: int
) -> int:
    """The type a task takes into another project: the one there with the same
    name, or that project's default."""
    name = (
        await session.exec(select(TaskType.name).where(TaskType.id == task_type_id))
    ).one_or_none()
    if name is not None:
        match = (
            await session.exec(
                select(TaskType.id).where(
                    TaskType.project_id == destination_project_id,
                    func.lower(TaskType.name) == name.lower(),
                )
            )
        ).first()
        if match is not None:
            return match
    default = await get_default_type(session, destination_project_id)
    assert default.id is not None
    return default.id


async def clone_types(
    session: AsyncSession, *, source_project_id: int, target_project_id: int
) -> dict[int, int]:
    """Give the target the source's types in place of its own; each source
    type's id mapped to its copy's."""
    source_types = await list_types(session, source_project_id)
    if not source_types:
        return {}
    await session.exec(
        delete(TaskType).where(col(TaskType.project_id) == target_project_id)
    )
    await session.flush()
    mapping: dict[int, int] = {}
    for source in source_types:
        clone = TaskType(
            project_id=target_project_id,
            name=source.name,
            position=source.position,
            is_default=source.is_default,
            color=source.color,
            icon=source.icon,
            layout_preset=source.layout_preset,
        )
        session.add(clone)
        await session.flush()
        assert source.id is not None and clone.id is not None
        mapping[source.id] = clone.id
    return mapping


def resequence(types: list[TaskType]) -> None:
    for index, task_type in enumerate(types):
        task_type.position = index


def ensure_one_default(types: list[TaskType]) -> None:
    """Exactly one default: the first marked, or the first."""
    marked = [t for t in types if t.is_default]
    if not marked and types:
        types[0].is_default = True
    for extra in marked[1:]:
        extra.is_default = False
