"""Which transactions of the change log subscribers have been told about.

A row per transaction, written by the sweep that tells them
(``app.services.tenant.subscription_notices``), in the same transaction as the
notices. The same ledger shape as ``webhook_deliveries`` and for the same
reason: change-log ids are taken at insert and seen at commit, so a position
could be passed over by a transaction that commits late, and a row per
transaction cannot. Rows go when the change log lets their transaction go.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime
from sqlmodel import Field, SQLModel


class SubscriptionNotice(SQLModel, table=True):
    __tablename__ = "subscription_notices"

    #: The writing transaction's ``txid_current()``, as its change-log rows
    #: carry it.
    txn_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    settled_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
