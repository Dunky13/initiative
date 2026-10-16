"""The hooks about a community's install: written, sent, retried, settled.

Each is held to what a plug-in's kit relies on: a lifecycle token naming the
hook, the community by the plug-in's own reference and where it stands; a 2xx
or a 404 settles it for good and anything else is asked again later; an
``erase`` drops the plug-in's references only once it has been answered; and a
status change reaches every enabled install however it was made.
"""

from __future__ import annotations

import ipaddress
import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityStatus
from app.models.platform.plugin_community_hook import PluginCommunityHook
from app.services import safe_http
from app.services.marketplace import community_hooks, plugin_installs, plugin_refs
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant import plugin_connection_flows
from app.services.webhook_target_url import ValidatedTarget
from app.testing import (
    create_guild,
    create_guild_plugin,
    create_plugin_service_registration,
    create_user,
)

PUBLIC_ID = "tests.hooked"
LISTING_UID = "TESTAPP0000071"
BASE_URL = "https://hooked.example.test"

_KEY = ed25519.Ed25519PrivateKey.generate()
_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


class Plugin:
    """The plug-in's hook route: answers each call with the next status in
    ``answers`` (the last repeating), and keeps what it was sent."""

    def __init__(self, *answers: int) -> None:
        self.answers = list(answers) or [204]
        self.calls: list[tuple[str, dict, dict]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        token = request.headers["authorization"].removeprefix("Bearer ")
        claims = jwt.decode(
            token,
            _KEY.public_key(),
            algorithms=["EdDSA"],
            audience=f"initiative-plugin:{PUBLIC_ID}",
        )
        self.calls.append(
            (request.url.path, claims, json.loads(request.content or b"{}"))
        )
        status = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return httpx.Response(status)


@pytest.fixture(autouse=True)
def _signing(monkeypatch):
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _PEM)
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_KEY_ID", "plugin-platform-1")

    async def resolve(url: str, *, allow_private: bool = False) -> ValidatedTarget:
        return ValidatedTarget(
            hostname=httpx.URL(url).host,
            addresses=(ipaddress.ip_address("93.184.216.34"),),
        )

    monkeypatch.setattr(safe_http, "resolve_validated_target_async", resolve)


def _answering(monkeypatch, plugin: Plugin) -> Plugin:
    monkeypatch.setattr(
        plugin_connection_flows, "http_transport", httpx.MockTransport(plugin.handle)
    )
    return plugin


async def _setup(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    install = await create_guild_plugin(
        session,
        guild,
        user,
        definition={"plugin_kind": "service", "service": {"public_id": PUBLIC_ID}},
        listing_uid=LISTING_UID,
    )
    await create_plugin_service_registration(
        session, public_id=PUBLIC_ID, listing_uid=LISTING_UID, base_url=BASE_URL
    )
    await session.commit()
    invalidate_registrations()
    return user, guild, install


async def _hooks(session: AsyncSession, guild_id: int) -> list[PluginCommunityHook]:
    await set_rls_context(session, Unattributed())
    rows = (
        await session.exec(
            select(PluginCommunityHook)
            .where(PluginCommunityHook.guild_id == guild_id)
            .order_by(PluginCommunityHook.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    await session.commit()
    return list(rows)


def _later(minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


class TestSending:
    async def test_a_hook_is_a_lifecycle_call_naming_the_community(
        self, session, monkeypatch
    ):
        _user, guild, install = await _setup(session)
        plugin = _answering(monkeypatch, Plugin(204))

        assert await community_hooks.deliver_community_hook(
            guild_id=guild.id, public_id=PUBLIC_ID, hook="installed"
        )
        assert await community_hooks.run_pass() == 1

        ((path, claims, body),) = plugin.calls
        assert path == "/v1/hooks/installed"
        assert body == {}
        assert claims["scope"] == "lifecycle"
        assert claims["hook"] == "installed"
        assert claims["community_status"] == "active"
        assert claims["plugin_install_id"] == install.id
        assert claims["community_ref"] == await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        (row,) = await _hooks(session, guild.id)
        assert (row.outcome, row.attempts) == ("delivered", 1)
        assert row.done_at is not None

    async def test_a_404_means_the_hook_is_not_taken_and_is_not_asked_again(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)
        plugin = _answering(monkeypatch, Plugin(404))

        await community_hooks.deliver_community_hook(
            guild_id=guild.id, public_id=PUBLIC_ID, hook="uninstalled"
        )
        await community_hooks.run_pass()
        await community_hooks.run_pass(now=_later(60 * 24))

        assert len(plugin.calls) == 1
        (row,) = await _hooks(session, guild.id)
        assert row.outcome == "not_taken"

    async def test_anything_else_is_asked_again_after_a_while(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)
        plugin = _answering(monkeypatch, Plugin(500, 204))

        await community_hooks.deliver_community_hook(
            guild_id=guild.id, public_id=PUBLIC_ID, hook="installed"
        )
        await community_hooks.run_pass()
        (row,) = await _hooks(session, guild.id)
        assert row.done_at is None and row.attempts == 1
        assert row.next_attempt_at > datetime.now(timezone.utc)
        assert "500" in (row.last_error or "")

        # Not due yet: nothing is sent.
        await community_hooks.run_pass()
        assert len(plugin.calls) == 1

        await community_hooks.run_pass(now=_later(5))
        assert len(plugin.calls) == 2
        (row,) = await _hooks(session, guild.id)
        assert (row.outcome, row.attempts) == ("delivered", 2)

    async def test_one_plugins_hooks_go_in_the_order_they_were_written(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)
        plugin = _answering(monkeypatch, Plugin(500, 204))

        for hook in ("uninstalled", "installed"):
            await community_hooks.deliver_community_hook(
                guild_id=guild.id, public_id=PUBLIC_ID, hook=hook
            )
        await community_hooks.run_pass()
        # The second waits behind the first.
        assert [path for path, _, _ in plugin.calls] == ["/v1/hooks/uninstalled"]

        await community_hooks.run_pass(now=_later(5))
        await community_hooks.run_pass(now=_later(5))
        assert [path for path, _, _ in plugin.calls] == [
            "/v1/hooks/uninstalled",
            "/v1/hooks/uninstalled",
            "/v1/hooks/installed",
        ]

    async def test_it_is_given_up_on_in_the_end(self, session, monkeypatch):
        _user, guild, _install = await _setup(session)
        _answering(monkeypatch, Plugin(503))
        monkeypatch.setattr(community_hooks, "MAX_ATTEMPTS", 2)

        await community_hooks.deliver_community_hook(
            guild_id=guild.id, public_id=PUBLIC_ID, hook="installed"
        )
        await community_hooks.run_pass()
        await community_hooks.run_pass(now=_later(5))
        (row,) = await _hooks(session, guild.id)
        assert (row.outcome, row.attempts) == ("gave_up", 2)

    async def test_only_a_community_hook_and_only_a_container_plugin(self, session):
        _user, guild, _install = await _setup(session)

        with pytest.raises(community_hooks.UnknownCommunityHookError):
            await community_hooks.deliver_community_hook(
                guild_id=guild.id, public_id=PUBLIC_ID, hook="revoke"
            )
        assert not await community_hooks.deliver_community_hook(
            guild_id=guild.id, public_id="not.registered", hook="installed"
        )
        assert await _hooks(session, guild.id) == []

    async def test_a_newer_status_replaces_one_still_waiting(self, session):
        _user, guild, _install = await _setup(session)

        for status in ("read_only", "on_hold"):
            await community_hooks.deliver_community_hook(
                guild_id=guild.id,
                public_id=PUBLIC_ID,
                hook="community_status",
                body={"status": status},
            )
        (row,) = await _hooks(session, guild.id)
        assert row.body == {"status": "on_hold"}


class TestErasing:
    async def test_the_references_go_only_once_it_has_answered(
        self, session, monkeypatch
    ):
        user, guild, _install = await _setup(session)
        member = await plugin_refs.ensure_plugin_ref(
            guild_id=guild.id, public_id=PUBLIC_ID, user_id=user.id
        )
        community = await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        plugin = _answering(monkeypatch, Plugin(502, 204))

        await community_hooks.deliver_community_hook(
            guild_id=guild.id, public_id=PUBLIC_ID, hook="erase"
        )
        await community_hooks.run_pass()
        # Not answered: everything it holds a name for still has one.
        assert await plugin_refs.resolve_plugin_ref(
            session, ref=member, guild_id=guild.id
        )
        assert plugin.calls[0][1]["community_ref"] == community

        await community_hooks.run_pass(now=_later(5))
        assert (
            await plugin_refs.resolve_plugin_ref(session, ref=member, guild_id=guild.id)
            is None
        )
        assert (
            await plugin_refs.existing_plugin_guild_ref(
                guild_id=guild.id, public_id=PUBLIC_ID
            )
            is None
        )

    async def test_the_issuer_hears_of_an_erase_once_it_is_answered(
        self, session, monkeypatch
    ):
        from app.services.marketplace import plugin_entitlements

        _user, guild, _install = await _setup(session)
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        told: list[tuple[int, str]] = []

        async def erased(guild_id: int, listing_uid: str) -> None:
            told.append((guild_id, listing_uid))

        monkeypatch.setattr(plugin_entitlements, "erased", erased)
        _answering(monkeypatch, Plugin(500, 204))

        await community_hooks.deliver_community_hook(
            guild_id=guild.id, public_id=PUBLIC_ID, hook="erase"
        )
        await community_hooks.run_pass()
        assert told == []
        await community_hooks.run_pass(now=_later(5))
        assert told == [(guild.id, LISTING_UID)]

    async def test_a_plugin_that_takes_no_erase_hook_is_forgotten_too(
        self, session, monkeypatch
    ):
        user, guild, _install = await _setup(session)
        member = await plugin_refs.ensure_plugin_ref(
            guild_id=guild.id, public_id=PUBLIC_ID, user_id=user.id
        )
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        _answering(monkeypatch, Plugin(404))

        await community_hooks.deliver_community_hook(
            guild_id=guild.id, public_id=PUBLIC_ID, hook="erase"
        )
        await community_hooks.run_pass()
        assert (
            await plugin_refs.resolve_plugin_ref(session, ref=member, guild_id=guild.id)
            is None
        )

    async def test_an_erase_is_retried_after_the_install_has_gone(
        self, session, monkeypatch
    ):
        user, guild, install = await _setup(session)
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        install_id = install.id
        await session.delete(install)
        await session.commit()
        plugin = _answering(monkeypatch, Plugin(500, 204))

        await community_hooks.deliver_community_hook(
            guild_id=guild.id,
            public_id=PUBLIC_ID,
            hook="erase",
            install_id=install_id,
        )
        await community_hooks.run_pass()
        await community_hooks.run_pass(now=_later(5))

        assert [claims["plugin_install_id"] for _, claims, _ in plugin.calls] == [
            install_id,
            install_id,
        ]
        (row,) = await _hooks(session, guild.id)
        assert row.outcome == "delivered"

    async def test_a_purge_tells_every_plugin_holding_a_name_within_bounds(
        self, session, monkeypatch
    ):
        _user, guild, _install = await _setup(session)
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=guild.id, public_id=PUBLIC_ID
        )
        plugin = _answering(monkeypatch, Plugin(500))

        await community_hooks.erase_for_purge(guild.id)

        assert [path for path, _, _ in plugin.calls] == ["/v1/hooks/erase"] * (
            community_hooks.PURGE_ERASE_ATTEMPTS
        )


class TestStatus:
    async def test_a_status_change_is_told_to_every_enabled_install(
        self, session, monkeypatch
    ):
        _user, guild, install = await _setup(session)
        await plugin_installs.record(guild.id, install)
        # Recorded as already told: a fresh install learns it from its tokens.
        assert await community_hooks.reconcile_community_status(session) == 0

        guild.status = CommunityStatus.read_only.value
        session.add(guild)
        await session.commit()

        assert await community_hooks.reconcile_community_status(session) == 1
        (row,) = await _hooks(session, guild.id)
        assert (row.hook, row.body, row.install_id) == (
            "community_status",
            {"status": "read_only"},
            install.id,
        )
        # Told once.
        assert await community_hooks.reconcile_community_status(session) == 0

        plugin = _answering(monkeypatch, Plugin(204))
        await community_hooks.run_pass()
        ((path, claims, body),) = plugin.calls
        assert path == "/v1/hooks/community_status"
        assert body == {"status": "read_only"}
        assert claims["community_status"] == "read_only"
