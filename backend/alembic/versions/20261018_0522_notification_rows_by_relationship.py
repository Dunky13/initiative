"""notification rows by relationship

The settings page's eighteen rows become nine, grouped by how the reader
relates to what happened rather than by what kind of thing it was, and each
community's dial becomes a mute and a switch per row.

Where several rows become one, one of them decides, so a choice nobody made
for the new row doesn't silence it: Mentions for "Mentions and replies", Task
assignments for "Assigned to you", Comments for "Subscribed", Posts for "New in
your communities". The other rows keep their own choices; the rest go. A
community at "Nothing" is muted; one at "Only what names me" has Subscribed and
New switched off there, which is what that level kept.

Waiting mail keeps its place under the row its category became. The two types
that go (an event's update, now told from the change log, and one that was
never sent) take their unread lines and waiting notices with them.

The downgrade leaves the settings as they are: a build that reads the old rows
finds them at their defaults.

Revision ID: 20261018_0522
Revises: 20261018_0521
Create Date: 2026-10-18
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import sqlalchemy as sa
from alembic import op

revision = "20261018_0522"
down_revision = "20261018_0521"
branch_labels = None
depends_on = None

#: Each new row, and the old row whose choice it takes.
_DECIDED_BY = {
    "mentions": "mentions",
    "assignments": "assignments",
    "subscriptions": "comments",
    "news": "posts",
}
#: Rows that stay as they were.
_KEPT = ("approvals", "moderation", "direct_messages", "jobs", "account")
#: The rows a community switches on its own.
_PER_COMMUNITY = tuple(_DECIDED_BY)
_CHANNELS = ("in_app", "email", "push", "desktop")
#: Waiting mail's category, from the row it was under to the row that became.
_MAIL = {
    "replies": "mentions",
    "reactions": "mentions",
    "comments": "subscriptions",
    "due_dates": "assignments",
    "events": "assignments",
    "event_reminders": "assignments",
    "membership": "news",
    "posts": "news",
    "connections": "direct_messages",
}
_GONE_TYPES = ("event_updated", "user_pending_approval")


def _rows(section: dict[str, Any], keep: tuple[str, ...]) -> dict[str, Any]:
    old = section.get("categories")
    old = old if isinstance(old, dict) else {}
    new = {name: old[name] for name in keep if name in old}
    for name, source in _DECIDED_BY.items():
        if source in old:
            new[name] = old[source]
    return {name: value for name, value in new.items() if value}


def regroup(doc: dict[str, Any]) -> dict[str, Any]:
    """One account's settings, on the nine rows."""
    out = {
        key: value for key, value in doc.items() if key not in ("categories", "guilds")
    }
    rows = _rows(doc, _KEPT)
    if rows:
        out["categories"] = rows
    guilds = doc.get("guilds")
    regrouped: dict[str, Any] = {}
    for guild_id, section in (guilds if isinstance(guilds, dict) else {}).items():
        if not isinstance(section, dict):
            continue
        here = {
            key: value
            for key, value in section.items()
            if key not in ("categories", "level")
        }
        level = section.get("level")
        # A community switches a whole row, so only a row that was off on
        # every channel there stays off; a channel or two goes.
        community_rows = {
            name: value
            for name, value in _rows(section, ()).items()
            if name in _PER_COMMUNITY
            and all(value.get(channel) is False for channel in _CHANNELS)
        }
        if level == "personal":
            for name in ("subscriptions", "news"):
                community_rows[name] = {channel: False for channel in _CHANNELS}
        if community_rows:
            here["categories"] = community_rows
        if level == "nothing":
            here["muted"] = True
        if here:
            regrouped[guild_id] = here
    if regrouped:
        out["guilds"] = regrouped
    return out


@contextmanager
def _writing(table: str) -> Iterator[None]:
    # A FORCE-RLS table the migration role owns binds it to policies keyed on
    # request settings a migration has no value for, so a forced table has
    # the force lifted for the write and restored with it.
    conn = op.get_bind()
    forced = conn.execute(
        sa.text(
            "SELECT relforcerowsecurity FROM pg_class"
            " WHERE oid = CAST(:table AS regclass)"
        ),
        {"table": f"public.{table}"},
    ).scalar_one()
    if forced:
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    try:
        yield
    finally:
        if forced:
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    conn = op.get_bind()
    with _writing("user_notification_prefs"):
        rows = conn.execute(
            sa.text("SELECT user_id, prefs FROM public.user_notification_prefs")
        ).all()
        for user_id, prefs in rows:
            doc = prefs if isinstance(prefs, dict) else json.loads(prefs or "{}")
            moved = regroup(doc)
            if moved != doc:
                conn.execute(
                    sa.text(
                        "UPDATE public.user_notification_prefs"
                        " SET prefs = CAST(:prefs AS jsonb), updated_at = now()"
                        " WHERE user_id = :user_id"
                    ),
                    {"prefs": json.dumps(moved), "user_id": user_id},
                )
    with _writing("email_outbox"):
        for old, new in _MAIL.items():
            conn.execute(
                sa.text(
                    "UPDATE public.email_outbox SET category = :new"
                    " WHERE category = :old"
                ),
                {"old": old, "new": new},
            )
    for table in ("notifications", "notice_outbox"):
        with _writing(table):
            conn.execute(
                sa.text(f"DELETE FROM public.{table} WHERE type = ANY (:types)"),
                {"types": list(_GONE_TYPES)},
            )


def downgrade() -> None:
    pass
