from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Text
from sqlmodel import Field, SQLModel

from app.core.tools import Tool
from app.db.registry_checks import FROM_REGISTRY

#: What can be starred: every tool. The CHECK below is rendered from these at
#: boot (``app.db.registry_checks``), so a tool added later is starrable with
#: no edit here.
FAVORITE_TYPES: tuple[str, ...] = tuple(t.value for t in Tool)

_ENTITY_TYPE_VALUES = ", ".join(f"'{kind}'" for kind in FAVORITE_TYPES)


class Favorite(SQLModel, table=True):
    """One member's star on one tool, in the tool's community.

    Polymorphic like ``recent_views``: ``(user_id, entity_type, entity_id)``,
    the row in its community's schema, its initiative resolved through the
    tool it names. ``entity_id`` is a weak reference, so purging the tool
    purges its stars (``soft_delete``) rather than a foreign key doing it.
    """

    __tablename__ = "favorites"
    __table_args__ = (
        CheckConstraint(
            f"entity_type IN ({_ENTITY_TYPE_VALUES})",
            name="ck_favorites_entity_type",
            info={FROM_REGISTRY: True},
        ),
    )

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    entity_type: str = Field(sa_column=Column(Text, primary_key=True, nullable=False))
    entity_id: int = Field(primary_key=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
