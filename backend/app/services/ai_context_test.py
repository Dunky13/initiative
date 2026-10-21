"""What a task's checklist and description are written from."""

import json

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import TaskStatusCategory
from app.services import ai_context
from app.services.tenant import task_queries
from app.testing import (
    checklist_items,
    create_comment,
    create_relationship,
    create_task,
)


async def test_a_task_is_told_with_its_links_and_newest_comments(
    session, acting_user, reading_as
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=a.initiative
    )
    task = await create_task(
        session,
        a.project,
        title="Ship it",
        description=f"Ask @[]({b.user.id}) about the hall",
        checklist=checklist_items("Book the hall"),
    )
    caterer = await create_task(session, a.project, title="Find a caterer")
    date = await create_task(
        session, a.project, title="Pick a date", status_category=TaskStatusCategory.done
    )
    for other in (caterer, date):
        await create_relationship(
            session,
            a.guild,
            source=(SearchEntityType.task, task.id),
            target=(SearchEntityType.task, other.id),
            relationship_type=RelationshipType.depends_on,
        )
    for text in ("first", "second", "third"):
        await create_comment(session, a.user, task=task, content=text)

    reading = await reading_as(a.user.id, a.guild.id)
    loaded = await task_queries.load_task(reading, task.id)

    async def told(budget: int) -> ai_context.TaskContext:
        return await ai_context.task_context(
            reading, loaded, user=a.user, guild_id=a.guild.id, budget=budget
        )

    whole = await told(3000)
    data = json.loads(whole.data)
    assert data["task"]["title"] == "Ship it"
    assert data["task"]["checklist"] == [{"text": "Book the hall", "done": False}]
    # A mention reads as the name, not the id it is stored as.
    assert "@[]" not in data["task"]["description"]
    assert b.user.username in data["task"]["description"]
    # Only the linked task still to do; a finished one has nothing to add.
    assert data["linked_tasks"] == ["Find a caterer (this task depends_on it)"]
    assert [c["text"] for c in data["comments"]] == ["first", "second", "third"]
    assert (whole.comments_read, whole.comments_total) == (3, 3)

    # With no room, the task still goes in, and the result says what was left.
    bare = await told(0)
    assert "comments" not in json.loads(bare.data)
    assert (bare.comments_read, bare.comments_total) == (0, 3)

    # Room for one: the newest.
    newest = data["comments"][-1]
    one, finished = await ai_context._recent_comments(
        reading,
        loaded,
        user=a.user,
        guild_id=a.guild.id,
        room=len(ai_context._dumps(newest)) + 1,
    )
    assert (one, finished) == ([newest], False)
