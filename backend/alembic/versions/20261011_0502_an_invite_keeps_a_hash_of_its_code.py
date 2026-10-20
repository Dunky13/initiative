"""an invite keeps a hash of its code

``guild_invites.code`` becomes ``code_hash``: the SHA-256 of the code, in hex.
The code is shown once, when the invite is made, and a link handed out before
this revision still works, because its code hashes to the stored value.

Revision ID: 20261011_0502
Revises: 20261011_0501
Create Date: 2026-10-11
"""

from alembic import op

revision = "20261011_0502"
down_revision = "20261011_0501"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.guild_invites RENAME COLUMN code TO code_hash")
    op.execute(
        "ALTER INDEX IF EXISTS public.ix_guild_invites_code RENAME TO ix_guild_invites_code_hash"
    )
    op.execute("ALTER TABLE public.guild_invites NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "UPDATE public.guild_invites"
            " SET code_hash = encode(sha256(convert_to(code_hash, 'UTF8')), 'hex')"
        )
    finally:
        op.execute("ALTER TABLE public.guild_invites FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # A hash cannot be turned back into its code, so the invites go.
    op.execute("ALTER TABLE public.guild_invites NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM public.guild_invites")
    finally:
        op.execute("ALTER TABLE public.guild_invites FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER INDEX IF EXISTS public.ix_guild_invites_code_hash RENAME TO ix_guild_invites_code"
    )
    op.execute("ALTER TABLE public.guild_invites RENAME COLUMN code_hash TO code")
