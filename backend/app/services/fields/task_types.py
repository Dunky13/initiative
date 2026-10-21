"""The task-type dataset: what kinds of task a project holds, by name."""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.task import TaskType
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset


def build() -> Dataset:
    return Dataset(
        model=TaskType,
        # Sharing is the project's, the way a task's is.
        tool=Tool.project,
        name_override="task_types",
        fields=derive_fields(TaskType),
    )
