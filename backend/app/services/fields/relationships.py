"""The link dataset — what two things are to each other.

A link names each end as a kind and an id (``source_type = 'task'``,
``source_id = 12``), so it is joined by both: a subtask finds its parent where
``relationship_type = 'part_of'``, its own id is the source and the parent's is
the target. No relation is declared for the same reason: an end is a task only
where its kind says so, and a declared join cannot say that.

Who may read a link is whoever may read both of the things it connects, in the
database (``relationships_path``). A link someone removed is kept as a record
that they did, and is left out of what a reader's statement returns.
"""

from __future__ import annotations

from app.models.tenant.relationship import EntityRelationship
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset


def build() -> Dataset:
    return Dataset(
        model=EntityRelationship,
        # No tool: each end is governed by its own.
        name_override="relationships",
        fields=derive_fields(
            EntityRelationship,
            # The ends packed into one integer for the index, and who removed a
            # link nobody here can see.
            internal=frozenset({"source_node", "target_node", "removed_by"}),
        ),
    )
