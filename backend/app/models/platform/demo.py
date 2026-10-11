"""The demo deployment's copies. A link handing a pitch out is a guest invite
into the pitch, and the visitor it lets in is a guest of their copy.

Only a deployment started with ``DEMO_MODE`` writes this; everywhere else it
stays empty. It is the system engine's alone: no request-path role reaches it.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlmodel import Field, SQLModel


class DemoSandboxState(str, Enum):
    #: Built and waiting for a visitor.
    pooled = "pooled"
    #: Claimed by a link; deleted once its guest's time is up.
    live = "live"


class DemoSandbox(SQLModel, table=True):
    """A community built for the pool, and once claimed, a visitor's copy."""

    __tablename__ = "demo_sandboxes"
    __table_args__ = (
        CheckConstraint("state IN ('pooled', 'live')", name="ck_demo_sandboxes_state"),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
        )
    )
    state: DemoSandboxState = Field(
        default=DemoSandboxState.pooled,
        sa_column=Column(String, nullable=False, index=True, server_default="pooled"),
    )
    #: The invite into the pitch that opened the copy.
    invite_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("guild_invites.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    claimed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: The import filling the copy, in the copy's own schema.
    import_job_id: Optional[int] = Field(default=None)
