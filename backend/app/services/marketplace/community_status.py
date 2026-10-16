"""Where a community stands, as every token Initiative signs for a plug-in says.

Each context token and page handoff carries ``community_status``: the
community's status (``CommunityStatus``) when the token was minted. A plug-in
that missed a ``community_status`` hook learns the current one on its next
call, and treats anything but ``active`` as paused.

Read at mint time rather than from a value the caller held, so the claim is
the status now and not the one a long request began under.
"""

from __future__ import annotations

from sqlmodel import select

from app.db import cohorts
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityStatus, Guild

__all__ = ["community_status"]


async def community_status(guild_id: int) -> str:
    """The community's status now, as a ``CommunityStatus`` value.

    A system-engine session of its own from the guild's cohort: the callers
    are request handlers routed into other roles and workers holding none. A
    community whose row is gone is ``deleted``.
    """
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, Unattributed())
        status = (
            await session.exec(select(Guild.status).where(Guild.id == guild_id))
        ).first()
    return CommunityStatus(status).value if status else CommunityStatus.deleted.value
