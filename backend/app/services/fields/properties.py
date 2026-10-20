"""The property datasets — an initiative's custom properties, and their values.

A property belongs to the initiative rather than to any one tool: one
definition, and a value for it on whatever in the initiative carries one. So the
values are one dataset across every tool, and a report on story points or a
release is a report on the initiative, grouped by the property's own name.

Who may read a value is who may read the thing it is on, and the initiative a
dashboard sits on narrows both, in the database (``property_values_path``).
"""

from __future__ import annotations

from app.models.tenant.property import PropertyDefinition, PropertyValue
from app.services.fields.derive import derive_fields
from app.services.fields.spec import ControlKind, Dataset, Hop, Relation, column


def build_property_definitions() -> Dataset:
    return Dataset(
        model=PropertyDefinition,
        # No tool: a definition is the initiative's, and sharing governs things.
        name_override="property_definitions",
        fields=derive_fields(PropertyDefinition),
    )


def build_property_values() -> Dataset:
    return Dataset(
        model=PropertyValue,
        name_override="property_values",
        # A person-valued property holds an account id with no foreign key to
        # say so. Saying it here is what lets ``value_user_id = me`` read.
        fields=derive_fields(PropertyValue, references={"value_user_id": "users"})
        + (
            # A multi-select's choices, which live only here. Read out as the
            # document's text (``["a", "b"]``); ``value_json @> '["a"]'`` counts
            # one choice. A document is not something a filter compares.
            column(
                "value_json",
                PropertyValue.value_json,
                kind=ControlKind.text,
                filterable=False,
                offer=False,
            ),
        ),
        relations=(
            Relation(
                name="property",
                hops=(
                    Hop(dataset="property_definitions", left="property_id", right="id"),
                ),
            ),
        ),
    )
