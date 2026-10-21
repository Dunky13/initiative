"""A task has a type, and each type its own page.

Creates ``task_types`` (one project's kinds of task), gives every project the
four it starts with — named in the language of whoever made the project — and
points every task at its project's first, Task. A project's task page becomes
one per type: ``tool_layouts.task_type_id`` names it, and a page a project had
already changed goes to its Task type.

Order is create -> fill -> constrain. Row security, its policies and the grants
for the new table are not written here: provisioning renders those from the
registries, and the boot backfill re-applies them to every guild whose stamp
this revision made stale. The two tables written that already exist (``tasks``,
``tool_layouts``) have their policies and request triggers held while their
rows change; nothing restores them on failure, because the transaction rolls
the whole revision back.

Revision ID: 20261020_0531
Revises: 20261020_0530
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261020_0531"
down_revision = "20261020_0530"
branch_labels = None
depends_on = None


#: ``(shape, colour, icon)`` of the four types, in order; the first is the
#: default. Stated here rather than read from ``app.core.task_types``, so a
#: later change to what a new project starts with does not change what this
#: revision gave the projects already there.
_DEFAULTS = (
    ("task", "plain", "#94A3B8", "square-check"),
    ("bug", "fix", "#F87171", "bug"),
    ("idea", "discussion", "#FBBF24", "lightbulb"),
    ("milestone", "dates", "#A78BFA", "flag"),
)

#: Their names in each language the app spoke as of this revision. Frozen for
#: the same reason: the catalogue (``app/locales/*/projects.json``) may move on.
_NAMES: dict[str, dict[str, str]] = {
    "en": {"task": "Task", "bug": "Bug", "idea": "Idea", "milestone": "Milestone"},
    "de": {
        "task": "Aufgabe",
        "bug": "Fehler",
        "idea": "Idee",
        "milestone": "Meilenstein",
    },
    "es": {"task": "Tarea", "bug": "Error", "idea": "Idea", "milestone": "Hito"},
    "fr": {"task": "Tâche", "bug": "Bug", "idea": "Idée", "milestone": "Jalon"},
}

#: The shapes a type could take as of this revision.
_SHAPES = ("plain", "fix", "discussion", "dates", "repeat", "checklist")


def _names(locale: str | None) -> dict[str, str]:
    """The four names in a locale, English for one the app does not speak.
    ``de-AT`` reads as ``de``."""
    language = (locale or "en").split("-")[0].split("_")[0].lower()
    return _NAMES.get(language, _NAMES["en"])


def _creator_locales(bind: sa.Connection) -> dict[int, str]:
    # A migration carries no request context, so the owner's policies are
    # lifted while the profile languages are read.
    bind.execute(sa.text("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY"))
    rows = bind.execute(sa.text("SELECT id, locale FROM public.users")).all()
    bind.execute(sa.text("ALTER TABLE public.users FORCE ROW LEVEL SECURITY"))
    return {user_id: locale for user_id, locale in rows}


def _create_table() -> None:
    shapes = ", ".join(f"'{shape}'" for shape in _SHAPES)
    op.create_table(
        "task_types",
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "color", sa.String(length=9), server_default="#94A3B8", nullable=False
        ),
        sa.Column(
            "icon", sa.String(length=64), server_default="square-check", nullable=False
        ),
        sa.Column(
            "layout_preset",
            sa.String(length=32),
            server_default="plain",
            nullable=False,
        ),
        sa.CheckConstraint(
            f"layout_preset IN ({shapes})", name="ck_task_types_layout_preset"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_types_project_id", "task_types", ["project_id"])
    op.create_index(
        "uq_task_types_project_name",
        "task_types",
        ["project_id", sa.text("lower(name)")],
        unique=True,
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER tr_task_types_set_created_by "
        "BEFORE INSERT ON task_types "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
    )


def _seed_types(bind: sa.Connection, locales: dict[int, str]) -> None:
    """The four types for every project, trashed and archived ones included:
    their tasks need a type to come back with."""
    op.execute("ALTER TABLE projects NO FORCE ROW LEVEL SECURITY")
    projects = bind.execute(sa.text("SELECT id, created_by FROM projects")).all()
    op.execute("ALTER TABLE projects FORCE ROW LEVEL SECURITY")
    rows = [
        {
            "project_id": project_id,
            "name": _names(locales.get(created_by))[key],
            "position": position,
            "is_default": position == 0,
            "color": color,
            "icon": icon,
            "layout_preset": shape,
            "created_by": created_by,
        }
        for project_id, created_by in projects
        for position, (key, shape, color, icon) in enumerate(_DEFAULTS)
    ]
    if rows:
        bind.execute(
            sa.text(
                "INSERT INTO task_types (project_id, name, position, is_default,"
                " color, icon, layout_preset, created_by)"
                " VALUES (:project_id, :name, :position, :is_default, :color,"
                " :icon, :layout_preset, :created_by)"
            ),
            rows,
        )


_DEFAULT_TYPE_OF = (
    "(SELECT tt.id FROM task_types tt"
    " WHERE tt.project_id = {project} AND tt.is_default)"
)


def _type_tasks() -> None:
    op.add_column("tasks", sa.Column("task_type_id", sa.Integer(), nullable=True))
    # Every task, in every lifecycle state, is a Task; the freeze and the
    # change capture are held, because no task changed in a way anyone did.
    op.execute("ALTER TABLE tasks NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tasks DISABLE TRIGGER USER")
    op.execute(
        "UPDATE tasks SET task_type_id = "
        + _DEFAULT_TYPE_OF.format(project="tasks.project_id")
    )
    op.execute("ALTER TABLE tasks ENABLE TRIGGER USER")
    op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")
    op.alter_column("tasks", "task_type_id", nullable=False)
    op.create_foreign_key(
        "tasks_task_type_id_fkey",
        "tasks",
        "task_types",
        ["task_type_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_tasks_task_type_id", "tasks", ["task_type_id"])


def _type_layouts() -> None:
    op.add_column(
        "tool_layouts", sa.Column("task_type_id", sa.Integer(), nullable=True)
    )
    op.execute("ALTER TABLE tool_layouts NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tool_layouts DISABLE TRIGGER USER")
    # A project's changed task page is its Task type's. One whose project is
    # gone has no type to be, and nothing draws it.
    op.execute(
        "UPDATE tool_layouts SET task_type_id = "
        + _DEFAULT_TYPE_OF.format(project="tool_layouts.tool_id")
        + " WHERE tool = 'project' AND kind = 'task'"
    )
    op.execute(
        "DELETE FROM tool_layouts"
        " WHERE tool = 'project' AND kind = 'task' AND task_type_id IS NULL"
    )
    op.execute("ALTER TABLE tool_layouts ENABLE TRIGGER USER")
    op.execute("ALTER TABLE tool_layouts FORCE ROW LEVEL SECURITY")
    op.create_foreign_key(
        "tool_layouts_task_type_id_fkey",
        "tool_layouts",
        "task_types",
        ["task_type_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_tool_layouts_task_type_id", "tool_layouts", ["task_type_id"])
    op.drop_index("uq_tool_layouts_kind", table_name="tool_layouts")
    op.create_index(
        "uq_tool_layouts_kind",
        "tool_layouts",
        ["initiative_id", "tool", "tool_id", "kind", "task_type_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_check_constraint(
        "ck_tool_layouts_typed",
        "tool_layouts",
        "((tool = 'project' AND kind = 'task')) = (task_type_id IS NOT NULL)",
    )


def _apply_upgrade(bind: sa.Connection, locales: dict[int, str]) -> None:
    _create_table()
    _seed_types(bind, locales)
    _type_tasks()
    _type_layouts()


def upgrade() -> None:
    bind = op.get_bind()
    locales = _creator_locales(bind)
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(bind, locales))


def _apply_downgrade() -> None:
    # The task page goes back to being one per project: its Task type's.
    op.execute("ALTER TABLE tool_layouts NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tool_layouts DISABLE TRIGGER USER")
    op.execute(
        "DELETE FROM tool_layouts t USING task_types tt"
        " WHERE t.task_type_id = tt.id AND NOT tt.is_default"
    )
    op.execute("ALTER TABLE tool_layouts ENABLE TRIGGER USER")
    op.execute("ALTER TABLE tool_layouts FORCE ROW LEVEL SECURITY")
    op.drop_constraint("ck_tool_layouts_typed", "tool_layouts", type_="check")
    op.drop_index("uq_tool_layouts_kind", table_name="tool_layouts")
    op.drop_index("ix_tool_layouts_task_type_id", table_name="tool_layouts")
    op.drop_constraint(
        "tool_layouts_task_type_id_fkey", "tool_layouts", type_="foreignkey"
    )
    op.drop_column("tool_layouts", "task_type_id")
    op.create_index(
        "uq_tool_layouts_kind",
        "tool_layouts",
        ["initiative_id", "tool", "tool_id", "kind"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.drop_index("ix_tasks_task_type_id", table_name="tasks")
    op.drop_constraint("tasks_task_type_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "task_type_id")
    op.drop_table("task_types")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
