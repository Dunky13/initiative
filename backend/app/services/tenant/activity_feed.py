"""What changed lately in a community that this reader would want to know.

One entry per item: the items people changed in the last week, read from the
change log on the reader's own session, so its read policy (the initiative and
the sharing of the tool a change names) decides which changes are seen at all.
Each change counts for the item ``content_item_of`` names, the same item the
engagement levels count it for, and an item is shown only where its search
entry is readable too, which is also where its title comes from.

An entry is ordered by how recent its latest change is, the item's engagement
level, and how involved the reader is with it:

    2^(−age / HALF_LIFE) × boosted(1, level) × relevance

Only people's changes make entries, never a plug-in's, and never the reader's
own: what the reader did says the item is theirs, which lifts it, and nothing
more. Some changes are not activity at all (a reaction, a read, a vote): they
count toward the level and make no entry.

The newest :data:`CANDIDATE_CHANGES` changes are the candidates, read through
the change log's index on time, so a busy community's request reads a bounded
slice of the week. Older changes have faded by then anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import DateTime, Float, Integer, Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db.initiative_rls import CONTENT_KIND_TABLES, NAMED_PEOPLE
from app.models.platform.user_profile_view import MemberProfile
from app.services.tenant.change_log import RETENTION
from app.services.tenant.engagement_levels import BOOST

#: How far back the feed reads: the change log's own retention.
WINDOW = RETENTION
#: How fast an entry fades: one this old is ordered as if half as recent.
HALF_LIFE = timedelta(days=1)
#: The newest changes a request reads. Everything else in the window has faded.
CANDIDATE_CHANGES = 2000
#: Entries one page holds.
PAGE_SIZE = 20
#: The people an entry names; the rest are a count.
ACTORS_SHOWN = 3

#: What the reader's own involvement adds to an item's relevance.
ASSIGNED_WEIGHT = 2.0
CHANGED_WEIGHT = 1.0
OPENED_WEIGHT = 0.5
FAVOURITE_WEIGHT = 0.5


class FeedView(str, Enum):
    """What an entry has to be, to be in a view."""

    #: Everything.
    all = "all"
    #: What the reader is assigned to, made, or changed this week.
    yours = "yours"
    #: What somebody commented on.
    comments = "comments"


class Verb(str, Enum):
    """What happened to an item, as an entry says it."""

    created = "created"
    completed = "completed"
    commented = "commented"
    edited = "edited"
    moved = "moved"
    scheduled = "scheduled"
    published = "published"


#: Facets whose changes are not activity: they move an item's level and make no
#: entry. A reaction ranks an item rather than being news about it; a read and
#: an answer or a vote are a person's own business; sharing, layouts, a
#: project's statuses and plug-in values are configuration.
QUIET_FACETS: tuple[str, ...] = (
    "reactions",
    "reads",
    "poll",
    "answers",
    "sharing",
    "layouts",
    "statuses",
    "plugin_values",
)

#: The columns that say a task or an event was rescheduled.
_SCHEDULE_COLUMNS = ("start_date", "due_date", "start_at")


def _item_rows(column: str, test: str) -> str:
    """A CASE over every content kind with ``column``: whether the row of that
    kind ``test`` holds for. From the schema, so a new kind is asked the moment
    its table has the column."""
    arms = " ".join(
        f"WHEN '{kind}' THEN EXISTS (SELECT 1 FROM {table} r "  # noqa: S608
        f"WHERE r.id = i.id AND {test})"
        for kind, table in sorted(CONTENT_KIND_TABLES.items())
        if column in SQLModel.metadata.tables[table].c
    )
    return f"(CASE i.kind {arms} ELSE false END)"


def _assigned() -> str:
    """Whether a row naming the reader hangs off the item: an assignee, an
    attendee. From :data:`NAMED_PEOPLE`, the rows kept (not cleared) whose
    foreign key is a content kind's."""
    kind_of = {table: kind for kind, table in CONTENT_KIND_TABLES.items()}
    arms: dict[str, list[str]] = {}
    for named in NAMED_PEOPLE:
        if named.clear:
            continue
        for fk in SQLModel.metadata.tables[named.table].foreign_keys:
            kind = kind_of.get(fk.column.table.name)
            if kind is not None:
                arms.setdefault(kind, []).append(
                    f"EXISTS (SELECT 1 FROM {named.table} n "  # noqa: S608
                    f"WHERE n.{fk.parent.name} = i.id "
                    f"AND n.{named.column} = :reader)"
                )
    return "(CASE i.kind {} ELSE false END)".format(
        " ".join(
            f"WHEN '{kind}' THEN ({' OR '.join(tests)})"
            for kind, tests in sorted(arms.items())
        )
    )


def _verb() -> str:
    """One change as a verb, or NULL for a change that makes no entry."""
    return f"""
        CASE
            WHEN o.resource_type = 'comments' THEN
                CASE WHEN o.action = 'created' THEN '{Verb.commented.value}' END
            -- The item itself arriving: a facet is always reported as updated.
            WHEN o.action = 'created' AND o.resource_type = ANY (:item_tables)
                THEN '{Verb.created.value}'
            WHEN o.action <> 'updated' OR o.changed <@ :quiet THEN NULL
            WHEN o.resource_type = 'tasks' AND 'completed_at' = ANY (o.changed) THEN
                CASE WHEN EXISTS (SELECT 1 FROM tasks t WHERE t.id = o.resource_id
                                  AND t.completed_at IS NOT NULL)
                     THEN '{Verb.completed.value}' ELSE '{Verb.moved.value}' END
            WHEN o.resource_type = 'tasks' AND 'task_status_id' = ANY (o.changed)
                THEN '{Verb.moved.value}'
            WHEN o.resource_type = 'posts' AND 'published_at' = ANY (o.changed)
                THEN '{Verb.published.value}'
            WHEN o.resource_type IN ('tasks', 'calendar_events')
                 AND o.changed && :schedule_columns
                THEN '{Verb.scheduled.value}'
            ELSE '{Verb.edited.value}'
        END"""


def _statement(view: FeedView, *, initiative: bool, tool: bool) -> Any:
    """The feed as one statement, narrowed where the request asks."""
    narrowing = ""
    if initiative:
        narrowing += " AND o.initiative_id = :initiative_id"
    if tool:
        narrowing += " AND o.dac_tool = :tool AND o.dac_id = :tool_id"
    wanted = {
        FeedView.all: "true",
        FeedView.yours: "(i.assigned OR i.made OR i.changed_by_reader)",
        FeedView.comments: f"'{Verb.commented.value}' = ANY (i.verbs)",
    }[view]
    sql = f"""
    WITH changes AS (
        SELECT o.resource_type, o.resource_id, o.parents, o.action,
               o.changed::text[] AS changed,
               o.actor_user_id, o.occurred_at
        FROM event_outbox o
        WHERE o.occurred_at > :since
          AND o.actor_user_id IS NOT NULL
          AND o.actor_install_id IS NULL{narrowing}
        ORDER BY o.occurred_at DESC
        LIMIT :candidates
    ),
    attributed AS (
        SELECT item.kind, item.id, o.actor_user_id AS actor, o.occurred_at,
               {_verb()} AS verb
        FROM changes o
        CROSS JOIN LATERAL content_item_of(o.resource_type, o.resource_id, o.parents)
            AS item
    ),
    per_actor AS (
        SELECT kind, id, actor, max(occurred_at) AS last
        FROM attributed
        WHERE actor <> :reader AND verb IS NOT NULL
        GROUP BY kind, id, actor
    ),
    items AS (
        SELECT p.kind, p.id, max(p.last) AS latest,
               (array_agg(p.actor ORDER BY p.last DESC, p.actor))[1:{ACTORS_SHOWN}]
                   AS actors,
               count(*) AS actor_count
        FROM per_actor p
        GROUP BY p.kind, p.id
    ),
    involved AS (
        SELECT i.*,
               (SELECT array_agg(DISTINCT a.verb ORDER BY a.verb) FROM attributed a
                 WHERE a.kind = i.kind AND a.id = i.id
                   AND a.actor <> :reader AND a.verb IS NOT NULL) AS verbs,
               EXISTS (SELECT 1 FROM attributed a
                        WHERE a.kind = i.kind AND a.id = i.id
                          AND a.actor = :reader) AS changed_by_reader,
               {_assigned()} AS assigned,
               {_item_rows("created_by", "r.created_by = :reader")} AS made,
               EXISTS (SELECT 1 FROM recent_views v
                        WHERE v.user_id = :reader AND v.entity_type = i.kind
                          AND v.entity_id = i.id AND v.last_viewed_at > :since)
                   AS opened
        FROM items i
    ),
    entries AS (
        SELECT i.kind AS entity_type, i.id AS entity_id, i.latest, i.actors,
               i.actor_count, i.verbs,
               se.title, se.initiative_id, se.dac_tool AS tool, se.dac_id AS tool_id,
               power(2.0, -extract(epoch FROM (:now - i.latest)) / :half_life)
               * (1 + :boost * coalesce(l.level, 0))
               * (1
                  + CASE WHEN i.assigned THEN :assigned_weight ELSE 0 END
                  + CASE WHEN i.changed_by_reader THEN :changed_weight ELSE 0 END
                  + CASE WHEN i.opened THEN :opened_weight ELSE 0 END
                  + CASE WHEN se.dac_tool = '{Tool.project.value}' AND EXISTS (
                        SELECT 1 FROM project_favorites f
                         WHERE f.user_id = :reader AND f.project_id = se.dac_id)
                    THEN :favourite_weight ELSE 0 END) AS score
        FROM involved i
        JOIN search_entries se
          ON se.entity_type = i.kind AND se.entity_id = i.id AND se.chunk_ix = 0
         AND NOT se.archived AND NOT se.template
        LEFT JOIN engagement_levels l
          ON l.entity_type = i.kind AND l.entity_id = i.id
        WHERE {wanted}
    )
    SELECT e.*, container.title AS tool_title, ini.name AS initiative_name
    FROM entries e
    LEFT JOIN search_entries container
      ON container.entity_type = e.tool AND container.entity_id = e.tool_id
     AND container.chunk_ix = 0
     AND NOT (container.entity_type = e.entity_type
              AND container.entity_id = e.entity_id)
    LEFT JOIN initiatives ini ON ini.id = e.initiative_id
    ORDER BY e.score DESC, e.latest DESC, e.entity_type, e.entity_id
    LIMIT :limit OFFSET :offset
    """
    params = [
        bindparam("reader", type_=Integer),
        bindparam("since", type_=DateTime(timezone=True)),
        bindparam("now", type_=DateTime(timezone=True)),
        bindparam("candidates", type_=Integer),
        bindparam("quiet", type_=ARRAY(Text)),
        bindparam("schedule_columns", type_=ARRAY(Text)),
        bindparam("item_tables", type_=ARRAY(Text)),
        bindparam("half_life", type_=Float),
        bindparam("boost", type_=Float),
        bindparam("assigned_weight", type_=Float),
        bindparam("changed_weight", type_=Float),
        bindparam("opened_weight", type_=Float),
        bindparam("favourite_weight", type_=Float),
        bindparam("limit", type_=Integer),
        bindparam("offset", type_=Integer),
    ]
    if initiative:
        params.append(bindparam("initiative_id", type_=Integer))
    if tool:
        params += [bindparam("tool", type_=Text), bindparam("tool_id", type_=Integer)]
    return text(sql).bindparams(*params)


@dataclass(frozen=True)
class FeedEntry:
    """One item, as the feed shows it."""

    entity_type: str
    entity_id: int
    title: str
    initiative_id: Optional[int]
    initiative_name: Optional[str]
    tool: Optional[str]
    tool_id: Optional[int]
    tool_title: Optional[str]
    latest: datetime
    verbs: list[str]
    actors: list[MemberProfile]
    actor_count: int


def query(
    *,
    reader_id: int,
    view: FeedView = FeedView.all,
    initiative_id: Optional[int] = None,
    tool: Optional[Tool] = None,
    tool_id: Optional[int] = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> tuple[Any, dict[str, Any]]:
    """The statement one page of the feed runs, and its parameters."""
    now = datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "reader": reader_id,
        "since": now - WINDOW,
        "now": now,
        "candidates": CANDIDATE_CHANGES,
        "quiet": list(QUIET_FACETS),
        "schedule_columns": list(_SCHEDULE_COLUMNS),
        "item_tables": sorted(CONTENT_KIND_TABLES.values()),
        "half_life": HALF_LIFE.total_seconds(),
        "boost": BOOST,
        "assigned_weight": ASSIGNED_WEIGHT,
        "changed_weight": CHANGED_WEIGHT,
        "opened_weight": OPENED_WEIGHT,
        "favourite_weight": FAVOURITE_WEIGHT,
        # One more than the page, to say whether another follows.
        "limit": page_size + 1,
        "offset": (page - 1) * page_size,
    }
    if initiative_id is not None:
        params["initiative_id"] = initiative_id
    if tool is not None and tool_id is not None:
        params["tool"] = tool.value
        params["tool_id"] = tool_id
    statement = _statement(
        view, initiative=initiative_id is not None, tool="tool" in params
    )
    return statement, params


async def feed(
    session: AsyncSession,
    *,
    reader_id: int,
    view: FeedView = FeedView.all,
    initiative_id: Optional[int] = None,
    tool: Optional[Tool] = None,
    tool_id: Optional[int] = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> tuple[list[FeedEntry], bool]:
    """One page of the reader's feed, on their own routed session.

    Narrowed to one initiative, or to one tool (any :class:`Tool`, with the id
    of the instance), where those are given. Narrowing only removes changes.
    Returns the page's entries and whether another page follows.
    """
    statement, params = query(
        reader_id=reader_id,
        view=view,
        initiative_id=initiative_id,
        tool=tool,
        tool_id=tool_id,
        page=page,
        page_size=page_size,
    )
    rows = (await session.exec(statement, params=params)).mappings().all()  # type: ignore[call-overload]
    has_next = len(rows) > page_size
    rows = rows[:page_size]

    people_ids = {actor for row in rows for actor in row["actors"]}
    people = (
        {
            person.id: person
            for person in (
                await session.exec(
                    select(MemberProfile).where(MemberProfile.id.in_(people_ids))  # type: ignore[attr-defined]
                )
            ).all()
        }
        if people_ids
        else {}
    )
    return [
        FeedEntry(
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            title=row["title"],
            initiative_id=row["initiative_id"],
            initiative_name=row["initiative_name"],
            tool=row["tool"],
            tool_id=row["tool_id"],
            tool_title=row["tool_title"],
            latest=row["latest"],
            verbs=list(row["verbs"] or []),
            actors=[people[a] for a in row["actors"] if a in people],
            actor_count=row["actor_count"],
        )
        for row in rows
    ], has_next
