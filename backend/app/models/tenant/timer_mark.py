from datetime import datetime

from sqlalchemy import Column, DateTime, Text
from sqlmodel import Field, SQLModel


class TimerMark(SQLModel, table=True):
    """The earliest timer this community already has waiting, per sweep.

    ``public.arm_timer`` reads it before adding a timer, so a busy community
    adds one row to ``public.community_timers`` per sweep until it fires
    rather than one per write. The worker clears a sweep's mark when it takes
    the timer. Bookkeeping only: nobody reads it but that function.
    """

    __tablename__ = "timer_marks"

    kind: str = Field(sa_column=Column(Text, primary_key=True, nullable=False))
    due_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
