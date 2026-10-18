"""How far through the change log subscribers have been told.

One row per community, written by the sweep that tells them
(``app.services.tenant.subscription_notices``) once the people a batch
concerned were told. A transaction-id snapshot rather than a position:
change-log ids are taken at insert and seen at commit, so a transaction that
began earlier can be seen after a later one, and a position would pass over
it. Every transaction below ``told_xmin`` was told or never committed, and
``told_above`` names the few at or above it already told.
"""

from sqlalchemy import BigInteger, CheckConstraint, Column, Integer
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel


class SubscriptionProgress(SQLModel, table=True):
    __tablename__ = "subscription_progress"
    __table_args__ = (CheckConstraint("id = 1", name="ck_subscription_progress_one"),)

    #: Always 1: there is one row.
    id: int = Field(default=1, sa_column=Column(Integer, primary_key=True))
    told_xmin: int = Field(sa_column=Column(BigInteger, nullable=False))
    told_above: list[int] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(BigInteger), nullable=False, server_default="{}"),
    )
