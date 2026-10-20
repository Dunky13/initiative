"""The statement verb on the billing boundary: ``POST /billing/plugin-entitlement``.

* only a listing whose package names terms for it takes a statement, and only
  under the shipped root;
* a higher version replaces the one held, and an equal or lower one changes
  nothing;
* a statement that lands is kept and handed, exactly as sent, to the
  installed plug-in as its ``entitlement`` hook, and one for a plug-in not
  installed waits for it;
* a statement without the statement header, the issuer's ``iss`` or every
  claim with its type is refused (422 ``INVALID_STATEMENT``) with nothing
  consumed.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.core.messages import BillingMessages
from app.db import post_commit
from app.models.platform.plugin_entitlement import PluginEntitlement
from app.services import sweep_timers
from app.services.marketplace import plugin_entitlements, tuf_registry
from app.services.tenant import plugin_connection_flows as flows
from app.testing import (
    billing_guild_ref,
    create_guild,
    create_guild_plugin,
    create_listing_with_terms,
    create_marketplace_listing,
    create_plugin_service_registration,
    create_user,
    entitlement_statement,
)

PAID_UID = "PAYDAPP0000001"
PAID_ID = "tests.paid"

_keypair = ed25519.Ed25519PrivateKey.generate()
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = (
    _keypair.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)
_HMAC_SECRET = "test-billing-hmac-secret"


@pytest.fixture(autouse=True)
def _configure_billing(monkeypatch):
    monkeypatch.setattr(config_module.settings, "BILLING_PUBLIC_KEY_PEM", _PUBLIC_PEM)
    monkeypatch.setattr(config_module.settings, "BILLING_HMAC_SECRET", _HMAC_SECRET)
    monkeypatch.setattr(config_module.settings, "BILLING_HMAC_SECRET_PREVIOUS", None)
    # The outbound side stays off: these tests are about the inbound verb.
    monkeypatch.setattr(config_module.settings, "BILLING_SERVICE_URL", None)


@pytest.fixture
def shipped_root(monkeypatch):
    """The registry these listings came from verified under the shipped root."""
    monkeypatch.setattr(tuf_registry, "configured_root_is_builtin", lambda: True)


@pytest.fixture
def hooks(monkeypatch) -> list[tuple[str, int, dict]]:
    """Every entitlement hook delivered, as (name, install id, body), once the
    community-hook queue has been drained (:func:`_drained`)."""
    delivered: list[tuple[str, int, dict]] = []

    async def call_hook(name, *, install_id, body, **_kwargs):
        if name == plugin_entitlements.ENTITLEMENT_HOOK:
            delivered.append((name, install_id, dict(body)))
        return None

    monkeypatch.setattr(flows, "call_hook", call_hook)
    return delivered


def _token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "jti": secrets.token_hex(8),
            "sub": "initiative-billing",
            "aud": "initiative:billing",
            "iss": "initiative-billing",
            "iat": int(now.timestamp()),
            "exp": now + timedelta(seconds=300),
        },
        _PRIVATE_PEM,
        algorithm="EdDSA",
    )


async def _send(client: AsyncClient, payload: dict):
    path = "/api/v1/billing/plugin-entitlement"
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    message = "\n".join(["POST", path, ts, hashlib.sha256(body).hexdigest()])
    headers = {
        "Authorization": f"Bearer {_token()}",
        "X-Billing-Timestamp": ts,
        "X-Billing-Signature": hmac_lib.new(
            _HMAC_SECRET.encode(), message.encode(), hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }
    response = await client.post(path, content=body, headers=headers)
    await _drained()
    return response


async def _drained() -> None:
    """Every step a commit started, and every hook it queued, sent."""
    await post_commit.settle_all()
    await sweep_timers.process_due_timers(outward=True)


async def _jws(guild_id: int, **changes) -> str:
    """A statement for ``guild_id`` and the paid listing, ``changes`` applied."""
    claims = {
        "community_ref": await billing_guild_ref(guild_id),
        "listing_uid": PAID_UID,
        **changes,
    }
    return entitlement_statement(**claims)


async def _statement(guild_id: int, *, version: int, values: dict, **changes):
    return {
        "statement": await _jws(guild_id, version=version, values=values, **changes)
    }


async def _install(session: AsyncSession, guild, user):
    await create_plugin_service_registration(
        session, public_id=PAID_ID, listing_uid=PAID_UID
    )
    return await create_guild_plugin(
        session,
        guild,
        user,
        definition={"plugin_kind": "service", "service": {"public_id": PAID_ID}},
        listing_uid=PAID_UID,
    )


async def _held(session: AsyncSession, guild_id: int) -> PluginEntitlement | None:
    session.expunge_all()
    return (
        await session.exec(
            select(PluginEntitlement).where(
                PluginEntitlement.guild_id == guild_id,
                PluginEntitlement.listing_uid == PAID_UID,
            )
        )
    ).first()


async def test_a_listing_without_terms_takes_no_statement(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    guild = await create_guild(session)
    await create_marketplace_listing(
        session,
        uid=PAID_UID,
        public_id=PAID_ID,
        kind="plugin",
        definition={"plugin_kind": "service", "service": {"public_id": PAID_ID}},
    )

    response = await _send(
        client, await _statement(guild.id, version=1, values={"active": True})
    )

    assert response.status_code == 409
    assert response.json()["detail"] == BillingMessages.LISTING_HAS_NO_TERMS
    assert await _held(session, guild.id) is None


async def test_terms_under_another_root_take_no_statement(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(tuf_registry, "configured_root_is_builtin", lambda: False)
    guild = await create_guild(session)
    await create_listing_with_terms(
        session, uid=PAID_UID, public_id=PAID_ID, access="entitled"
    )

    response = await _send(
        client, await _statement(guild.id, version=1, values={"active": True})
    )

    assert response.status_code == 409
    assert await _held(session, guild.id) is None


async def test_versions_only_move_forward(
    client: AsyncClient, session: AsyncSession, shipped_root, hooks
):
    guild = await create_guild(session)
    await create_listing_with_terms(
        session, uid=PAID_UID, public_id=PAID_ID, access="entitled"
    )

    first = await _send(
        client, await _statement(guild.id, version=2, values={"plan": "pro"})
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"listing_uid": PAID_UID, "version": 2, "applied": True}

    older = await _send(
        client, await _statement(guild.id, version=1, values={"plan": "basic"})
    )
    same = await _send(
        client, await _statement(guild.id, version=2, values={"plan": "basic"})
    )
    for response in (older, same):
        assert response.status_code == 200
        assert response.json() == {
            "listing_uid": PAID_UID,
            "version": 2,
            "applied": False,
        }
    held = await _held(session, guild.id)
    assert held is not None and (held.version, held.values) == (2, {"plan": "pro"})

    newer = await _send(
        client, await _statement(guild.id, version=3, values={"plan": "team"})
    )
    assert newer.json()["applied"] is True
    held = await _held(session, guild.id)
    assert held is not None and (held.version, held.values) == (3, {"plan": "team"})


async def test_a_statement_is_delivered_to_the_installed_plugin(
    client: AsyncClient, session: AsyncSession, shipped_root, hooks
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_listing_with_terms(
        session, uid=PAID_UID, public_id=PAID_ID, access="entitled"
    )
    plugin = await _install(session, guild, user)
    statement = await _jws(guild.id, version=1, values={"active": True})

    await _send(client, {"statement": statement})
    # A replay delivers nothing more.
    await _send(client, {"statement": statement})

    assert hooks == [("entitlement", plugin.id, {"statement": statement})]
    held = await _held(session, guild.id)
    assert held is not None and held.statement == statement


async def test_a_plugin_installed_later_is_handed_the_statement(
    session: AsyncSession, shipped_root, hooks, client: AsyncClient
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_listing_with_terms(
        session, uid=PAID_UID, public_id=PAID_ID, access="entitled"
    )
    statement = await _jws(guild.id, version=4, values={"active": True})
    await _send(client, {"statement": statement})
    assert hooks == []

    plugin = await _install(session, guild, user)
    assert await plugin_entitlements.deliver_entitlement(guild.id, PAID_UID) is True
    # The same version is not handed to the same install twice.
    assert await plugin_entitlements.deliver_entitlement(guild.id, PAID_UID) is False
    await _drained()

    assert hooks == [("entitlement", plugin.id, {"statement": statement})]


async def test_an_unknown_community_consumes_nothing(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    await create_listing_with_terms(
        session, uid=PAID_UID, public_id=PAID_ID, access="entitled"
    )

    response = await _send(
        client,
        {
            "statement": entitlement_statement(
                community_ref="gbil_nobody",
                listing_uid=PAID_UID,
                version=1,
                values={},
            )
        },
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"header": {"typ": "JWT"}}, id="wrong-typ"),
        pytest.param({"header": {"typ": None}}, id="no-typ"),
        pytest.param({"header": {"alg": "HS256"}}, id="wrong-alg"),
        pytest.param({"header": {"alg": "none"}}, id="alg-none"),
        pytest.param({"iss": "initiative"}, id="wrong-iss"),
        pytest.param({"drop": ["iss"]}, id="no-iss"),
        pytest.param({"drop": ["version"]}, id="no-version"),
        pytest.param({"drop": ["values"]}, id="no-values"),
        pytest.param({"drop": ["listing_uid"]}, id="no-listing-uid"),
        pytest.param({"drop": ["community_ref"]}, id="no-community-ref"),
        pytest.param({"version": 0}, id="version-zero"),
        pytest.param({"version": "2"}, id="version-string"),
        pytest.param({"version": True}, id="version-bool"),
        pytest.param({"version": 1.5}, id="version-float"),
        pytest.param({"values": []}, id="values-list"),
        pytest.param({"community_ref": ""}, id="empty-community-ref"),
        pytest.param({"listing_uid": 7}, id="listing-uid-number"),
    ],
)
async def test_a_malformed_statement_is_refused(
    client: AsyncClient, session: AsyncSession, shipped_root, change
):
    guild = await create_guild(session)
    await create_listing_with_terms(
        session, uid=PAID_UID, public_id=PAID_ID, access="entitled"
    )
    claims = {"version": 1, "values": {}, **change}

    response = await _send(client, await _statement(guild.id, **claims))

    assert response.status_code == 422
    assert response.json()["detail"] == BillingMessages.INVALID_STATEMENT
    assert await _held(session, guild.id) is None


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="no-statement"),
        pytest.param({"statement": 1}, id="statement-number"),
        pytest.param({"statement": "x", "version": 2}, id="extra-field"),
    ],
)
async def test_a_malformed_body_is_refused(
    client: AsyncClient, session: AsyncSession, shipped_root, body
):
    guild = await create_guild(session)
    await create_listing_with_terms(
        session, uid=PAID_UID, public_id=PAID_ID, access="entitled"
    )

    response = await _send(client, body)

    assert response.status_code == 422
    assert response.json()["detail"] == BillingMessages.INVALID_PAYLOAD
    assert await _held(session, guild.id) is None


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param("not-a-jws", id="one-segment"),
        pytest.param("a.b", id="two-segments"),
        pytest.param("a.b.c.d", id="four-segments"),
        pytest.param("!!.!!.!!", id="not-base64url"),
    ],
)
async def test_a_statement_that_is_not_a_jws_is_refused(
    client: AsyncClient, session: AsyncSession, shipped_root, statement
):
    await create_listing_with_terms(
        session, uid=PAID_UID, public_id=PAID_ID, access="entitled"
    )

    response = await _send(client, {"statement": statement})

    assert response.status_code == 422
    assert response.json()["detail"] == BillingMessages.INVALID_STATEMENT


async def test_a_statement_with_a_cut_signature_is_refused(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    guild = await create_guild(session)
    await create_listing_with_terms(
        session, uid=PAID_UID, public_id=PAID_ID, access="entitled"
    )
    statement = await _jws(guild.id, version=1, values={})

    response = await _send(client, {"statement": statement[:-8]})

    assert response.status_code == 422
    assert response.json()["detail"] == BillingMessages.INVALID_STATEMENT
