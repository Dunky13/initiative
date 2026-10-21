"""Integration tests for the mode-based AI config surface.

Proves the security properties end-to-end:
- A connection's key is never returned by the API (only ``has_api_key``).
- A member configures nothing: no connection of their own, no key, no choice.
  They read whether AI is available, and run on the owner's connection.
- A community can never persist a private/internal base_url.
"""

import pytest

from app.models.platform.guild import CommunityRole
from app.services import ai_settings as ai_settings_service


PLATFORM_MODE = "/api/v1/settings/ai/platform/mode"
PLATFORM_CONNS = "/api/v1/settings/ai/platform/connections"


@pytest.fixture(autouse=True)
def _reset_ai_cache():
    """The platform config is cached in-process; drop it around each test so a
    mode/connection change in one test never leaks into the next."""
    ai_settings_service.invalidate_platform_ai_cache()
    yield
    ai_settings_service.invalidate_platform_ai_cache()


async def _set_mode(client, owner, mode: str):
    r = await client.put(PLATFORM_MODE, headers=owner.headers, json={"mode": mode})
    assert r.status_code == 200, r.text


async def test_platform_connection_key_never_returned(client, acting_user):
    owner = await acting_user()  # platform owner (config.manage)
    await _set_mode(client, owner, "platform")

    r = await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Company OpenAI",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-super-secret",
            "enabled": True,
            "is_default": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_api_key"] is True
    assert body["scope"] == "platform"
    # The ciphertext / plaintext key is never serialized.
    assert "api_key" not in body
    assert "api_key_encrypted" not in body

    # Listing likewise never exposes the key.
    r = await client.get(PLATFORM_CONNS, headers=owner.headers)
    assert r.status_code == 200
    for conn in r.json():
        assert "api_key" not in conn
        assert "api_key_encrypted" not in conn


async def test_member_reads_that_ai_is_available_without_the_key(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Shared",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-secret",
            "is_default": True,
        },
    )

    member = await acting_user(guild_role=CommunityRole.member, initiative=True)
    r = await client.get(member.g("/settings/ai/resolved"), headers=member.headers)
    assert r.status_code == 200, r.text
    resolved = r.json()
    assert resolved["source"] == "platform"
    assert resolved["enabled"] is True
    assert resolved["has_api_key"] is True
    assert "api_key" not in resolved


async def test_member_cannot_set_a_destination(client, acting_user):
    """Exfil-impossible: a member has no endpoint to create a connection, so
    they can never point a key at a destination they chose."""
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    member = await acting_user(guild_role=CommunityRole.member, initiative=True)

    # There is no member connection-create route.
    r = await client.post(
        member.g("/settings/ai/connections"),
        headers=member.headers,
        json={"label": "evil", "provider": "custom", "base_url": "http://evil"},
    )
    assert r.status_code == 403  # the seat only


async def test_guild_admin_cannot_save_private_base_url(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "community")

    admin = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)

    # A public custom endpoint is fine.
    r = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json={"label": "ok", "provider": "openai", "model": "gpt-4o", "api_key": "k"},
    )
    assert r.status_code == 200, r.text

    # A private/internal base_url is rejected for a guild connection.
    r = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json={
            "label": "evil",
            "provider": "ollama",
            "base_url": "http://169.254.169.254",
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "AI_INVALID_BASE_URL"


async def test_a_member_runs_on_the_community_s_key(client, acting_user, reading_as):
    """A connection is used once it names a model. A member then reads that
    the seat's connection has a key, and their request resolves to it though
    they cannot read the key table; clearing it is seen the same way."""
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    seat = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
    r = await client.post(
        seat.g("/settings/ai/connections"),
        headers=seat.headers,
        json={
            "label": "Team",
            "provider": "openai",
            "api_key": "sk-team",
            "is_default": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_api_key"] is True
    conn_id = r.json()["id"]

    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=seat.guild,
        initiative=seat.initiative,
        initiative_role="member",
    )
    resolved = await client.get(
        member.g("/settings/ai/resolved"), headers=member.headers
    )
    assert resolved.json()["enabled"] is False
    r = await client.put(
        seat.g(f"/settings/ai/connections/{conn_id}"),
        headers=seat.headers,
        json={"model": "gpt-5-mini"},
    )
    assert r.status_code == 200, r.text
    resolved = await client.get(
        member.g("/settings/ai/resolved"), headers=member.headers
    )
    assert resolved.json()["enabled"] is True
    asking = await reading_as(member.user.id, seat.guild.id)
    with_key = await ai_settings_service.resolve_ai_settings(
        asking, seat.guild.id, with_key=True
    )
    assert with_key.api_key == "sk-team"

    r = await client.put(
        seat.g(f"/settings/ai/connections/{conn_id}"),
        headers=seat.headers,
        json={"api_key": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_api_key"] is False
    resolved = await client.get(
        member.g("/settings/ai/resolved"), headers=member.headers
    )
    assert resolved.json()["has_api_key"] is False


async def test_disabled_mode_hides_ai(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "disabled")
    member = await acting_user(guild_role=CommunityRole.member, initiative=True)

    r = await client.get(member.g("/settings/ai/resolved"), headers=member.headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False


async def test_connecting_a_provider_is_the_seat_s(client, acting_user):
    """Which provider a community's work is sent to says what leaves it, so it
    answers to the seat rather than to running the community."""
    owner = await acting_user()
    await _set_mode(client, owner, "community")
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    listed = await client.get(
        admin.g("/settings/ai/connections"), headers=admin.headers
    )
    assert listed.status_code == 403, listed.text

    created = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json={"label": "no", "provider": "openai", "model": "gpt-4o", "api_key": "k"},
    )
    assert created.status_code == 403, created.text
