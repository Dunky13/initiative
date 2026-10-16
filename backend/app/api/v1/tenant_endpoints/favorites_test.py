"""Stars on any tool: starring, a community's list, and every community's."""

from __future__ import annotations

from httpx import AsyncClient
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.favorite import Favorite
from app.models.tenant.initiative import InitiativeMember
from app.testing import (
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_queue,
    create_user,
    route_session_to_guild,
)


async def test_any_tool_can_be_starred_and_listed_newest_first(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(
        session, a.initiative, a.user, name="Fete", icon="🎪"
    )
    queue = await create_queue(session, a.initiative, a.user, name="Rota")

    for path in (f"/favorites/project/{project.id}", f"/favorites/queue/{queue.id}"):
        response = await client.post(a.g(path), headers=a.headers)
        assert response.status_code == 204, response.text
    # Starring again keeps the star, and its time.
    again = await client.post(
        a.g(f"/favorites/project/{project.id}"), headers=a.headers
    )
    assert again.status_code == 204

    listed = await client.get(a.g("/favorites"), headers=a.headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert [(i["entity_type"], i["entity_id"], i["name"]) for i in items] == [
        ("queue", queue.id, "Rota"),
        ("project", project.id, "Fete"),
    ]
    assert items[1]["icon"] == "🎪"
    assert items[1]["initiative_id"] == a.initiative.id
    assert items[1]["community_id"] == a.guild.id


async def test_a_star_comes_off_and_says_so_on_the_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The project form and the any-tool form are one star."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user)

    await client.post(a.g(f"/favorites/project/{project.id}"), headers=a.headers)
    read = await client.get(a.g(f"/projects/{project.id}"), headers=a.headers)
    assert read.json()["is_favorited"] is True
    favorites = await client.get(a.g("/projects/favorites"), headers=a.headers)
    assert [p["id"] for p in favorites.json()] == [project.id]

    removed = await client.delete(
        a.g(f"/favorites/project/{project.id}"), headers=a.headers
    )
    assert removed.status_code == 204
    # Taking off a star that is not there changes nothing.
    again = await client.delete(
        a.g(f"/favorites/project/{project.id}"), headers=a.headers
    )
    assert again.status_code == 204
    assert (await client.get(a.g("/favorites"), headers=a.headers)).json() == []
    read = await client.get(a.g(f"/projects/{project.id}"), headers=a.headers)
    assert read.json()["is_favorited"] is False


async def test_a_tool_the_reader_cannot_open_cannot_be_starred(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Starring takes read access, as the tool's own page does: a queue in an
    initiative the reader is not in is not there for them."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    owner = await create_user(session)
    elsewhere = await create_initiative(session, a.guild, owner)
    hidden = await create_queue(session, elsewhere, owner)

    response = await client.post(
        a.g(f"/favorites/queue/{hidden.id}"), headers=a.headers
    )
    assert response.status_code == 404
    assert (await client.get(a.g("/favorites"), headers=a.headers)).json() == []


async def test_my_favorites_gathers_every_community(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    # A second community, which the same person then joins.
    second = await acting_user(guild_role=CommunityRole.member, initiative=True)
    first_project = await create_project(session, a.initiative, a.user, name="Here")
    await client.post(a.g(f"/favorites/project/{first_project.id}"), headers=a.headers)

    await create_guild_membership(session, user=a.user, guild=second.guild)
    await create_initiative_member(session, second.initiative, a.user)
    there = await create_queue(session, second.initiative, a.user, name="There")
    starred = await client.post(
        f"/api/v1/c/{second.guild.id}/favorites/queue/{there.id}", headers=a.headers
    )
    assert starred.status_code == 204, starred.text

    mine = await client.get("/api/v1/me/favorites", headers=a.headers)
    assert mine.status_code == 200, mine.text
    assert [(i["community_id"], i["name"]) for i in mine.json()] == [
        (second.guild.id, "There"),
        (a.guild.id, "Here"),
    ]


async def test_leaving_a_community_takes_its_stars(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user)
    await client.post(a.g(f"/favorites/project/{project.id}"), headers=a.headers)

    left = await client.delete(
        f"/api/v1/communities/{a.guild.id}/leave", headers=a.headers
    )
    assert left.status_code == 204, left.text

    # Back in, the star is not waiting for them.
    await create_guild_membership(session, user=a.user, guild=a.guild)
    await create_initiative_member(session, a.initiative, a.user)
    assert (await client.get(a.g("/favorites"), headers=a.headers)).json() == []


async def test_a_star_comes_off_a_tool_the_reader_has_lost(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Out of the initiative, the star still comes off rather than waiting
    for them to be let back in."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    project = await create_project(session, a.initiative, b.user)
    starred = await client.post(
        b.g(f"/favorites/project/{project.id}"), headers=b.headers
    )
    assert starred.status_code == 204, starred.text

    await route_session_to_guild(session, a.guild.id)
    await session.exec(
        delete(InitiativeMember).where(  # type: ignore[arg-type]
            col(InitiativeMember.user_id) == b.user.id
        )
    )
    await session.commit()

    # Out of reach now.
    gone = await client.get(b.g(f"/projects/{project.id}"), headers=b.headers)
    assert gone.status_code == 404, gone.text

    removed = await client.delete(
        b.g(f"/favorites/project/{project.id}"), headers=b.headers
    )
    assert removed.status_code == 204

    session.expunge_all()
    await route_session_to_guild(session, a.guild.id)
    left = (await session.exec(select(Favorite.user_id))).all()
    assert left == []
