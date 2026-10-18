"""no starred people

``profile_favorites``, the people one account starred to keep at the top of its
people lists, goes. Messages lists conversations newest first, and somebody
is found by searching for them. The table's policies go with it; the registry
no longer names it.

The downgrade puts the table back empty, with its constraint, index and grants
as ``20260904_0217`` made them; its policies are rendered from the registry of
the release that names them.

Revision ID: 20261018_0518
Revises: 20261017_0517
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261018_0518"
down_revision = "20261017_0517"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("profile_favorites")


def downgrade() -> None:
    op.create_table(
        "profile_favorites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("favorite_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["favorite_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "favorite_user_id"),
        sa.CheckConstraint(
            "user_id <> favorite_user_id", name="ck_profile_favorites_not_self"
        ),
    )
    op.create_index(
        "ix_profile_favorites_favorite_user",
        "profile_favorites",
        ["favorite_user_id"],
    )
    base = f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"'
    for statement in (
        "ALTER TABLE public.profile_favorites ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.profile_favorites FORCE ROW LEVEL SECURITY",
        "REVOKE ALL ON TABLE public.profile_favorites"
        f" FROM app_guild_base, {base}, app_user",
        f"GRANT SELECT, INSERT, DELETE ON TABLE public.profile_favorites TO {base}",
        "GRANT SELECT, DELETE ON TABLE public.profile_favorites TO app_admin",
    ):
        op.execute(statement)
