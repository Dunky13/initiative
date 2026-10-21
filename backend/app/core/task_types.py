"""What a project's task types start as, and the shapes their pages take.

A task type says what kind of thing a task is and how its page is laid out.
Each project holds its own (``app.models.tenant.task.TaskType``); every project
starts with the four below, named in the language of whoever made it.

A type's page is drawn as shipped until it is changed. What it is drawn as is
its shape (``layout_preset``): the handful of ways a task's page leads with
something different, rather than one layout per name. The frontend draws each
(``frontend/src/lib/layouts/tasks.ts``); the column's CHECK derives from
:data:`LAYOUT_SHAPES`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Every shape a type's page can take until it is changed: today's task page;
#: one that leads with what needs fixing; one that is mostly the conversation;
#: one that leads with its dates; one that leads with how it repeats; and one
#: that leads with its checklist. Append-only: a stored type names one.
LAYOUT_SHAPES: tuple[str, ...] = (
    "plain",
    "fix",
    "discussion",
    "dates",
    "repeat",
    "checklist",
)

#: How many types one project may hold.
MAX_TASK_TYPES = 20


@dataclass(frozen=True)
class DefaultTaskType:
    """One of the types every project starts with."""

    #: Its key in the ``projects`` catalogue (``taskTypes.defaults.<key>``).
    key: str
    shape: str
    color: str
    icon: str


#: The types every project starts with, in order; the first is the default.
DEFAULT_TASK_TYPES: tuple[DefaultTaskType, ...] = (
    DefaultTaskType("task", "plain", "#94A3B8", "square-check"),
    DefaultTaskType("bug", "fix", "#F87171", "bug"),
    DefaultTaskType("idea", "discussion", "#FBBF24", "lightbulb"),
    DefaultTaskType("milestone", "dates", "#A78BFA", "flag"),
)
