"""Under the minimum for an account, answered late.

Sign-up refuses a date of birth under the minimum age for an account in the
country the request comes from (``users.ACCOUNT_MINIMUM_AGE``: 13 in the US,
16 in Germany, the highest where the country is not known), and makes no
account. An account made without a date — a sign-in provider asked for none,
or the field was left empty — answers the same question later, through
``POST /me/age-confirmation``, and until now that path applied only the
directory's minimum of sixteen: a twelve-year-old in the US was kept out of
the directory and kept their account, which is the case COPPA is about.

``users.age_below_account_minimum_at`` records that late answer. While it
stands the account is scheduled for erasure like any deleted account, but
signing in does not call the deletion off (``users.may_sign_in``); the
support ticket every under-age answer has, ``users.age_unblock``, clears it.
A timestamp beside ``age_below_minimum_at`` rather than a flag, for the same
reason that one is: the record of *when* is the point.

``ck_users_age_account_answer`` keeps the pair honest: under the minimum for
an account is under the directory's minimum too, so the new mark never stands
without the older one.

``public.users`` grants its request-path UPDATE per column (0144), so the
column is granted to the two floors that write the table, as 0222 did for its
sibling: ``platform_base`` and ``app_user``. Not ``app_guild_base``, which
0221 took off ``public.users`` altogether.

Revision ID: 20261017_0516
Revises: 20261016_0515
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261017_0516"
down_revision = "20261016_0515"
branch_labels = None
depends_on = None

COLUMN = "age_below_account_minimum_at"
CHECK = "ck_users_age_account_answer"


def _write_roles() -> tuple[str, ...]:
    """The floors that write ``public.users`` — see the note above."""
    return (
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "app_user",
    )


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        CHECK,
        "users",
        f"{COLUMN} IS NULL OR age_below_minimum_at IS NOT NULL",
    )
    if not _is_postgres():
        return
    for role in _write_roles():
        op.execute(f"GRANT UPDATE ({COLUMN}) ON TABLE public.users TO {role}")


def downgrade() -> None:
    op.drop_constraint(CHECK, "users", type_="check")
    # The grant goes with the column it names.
    op.drop_column("users", COLUMN)
