"""An installed plug-in's entitlement statement and usage reports.

* ``GET /installation/entitlement`` answers the statement held for the
  install's community and listing, or 404 ``NO_ENTITLEMENT``;
* ``PUT /installation/usage/{meter}/{period}`` keeps a period's total for a
  meter the listing's terms name, refuses any other meter (403), a total lower
  than the one held (409) and a malformed report (422), and passes each total
  it keeps on to billing as a ``usage`` ping.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.core.messages import PluginChannelMessages
from app.db import post_commit
from app.models.platform.plugin_entitlement import PluginUsage
from app.services.marketplace import plugin_entitlements, tuf_registry
from app.services.platform import billing_ping
from app.testing import billing_guild_ref, create_listing_with_terms
from app.testing.plugin_clients import CLIENT, install_headers, install_plugin

BASE = "/api/v1/plugin-platform/installation"
BILLING = "https://billing.test"
SECRET = "outbound-billing-secret"
#: The install's listing, as the catalog spells a uid.
LISTING = "TKNCMETER00001"


@pytest.fixture
def shipped_root(monkeypatch):
    monkeypatch.setattr(tuf_registry, "configured_root_is_builtin", lambda: True)


@pytest.fixture
def billing_sent(monkeypatch) -> list[tuple[str, dict, dict]]:
    """Every request this deployment sends billing, as (url, body, headers)."""
    sent: list[tuple[str, dict, dict]] = []
    monkeypatch.setattr(config_module.settings, "BILLING_SERVICE_URL", BILLING)
    monkeypatch.setattr(config_module.settings, "BILLING_HMAC_SECRET", SECRET)

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, *, content, headers):
            sent.append((url, json.loads(content), dict(headers)))
            return httpx.Response(200, json={})

    monkeypatch.setattr(billing_ping.httpx, "AsyncClient", Client)
    return sent


async def _installed(session, acting_user, role_session):
    return await install_plugin(
        session, acting_user, role_session, granted=[], listing_uid=LISTING
    )


def _headers(installed):
    return install_headers(installed, [], client_id=CLIENT)


async def test_the_statement_held_is_answered(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, shipped_root
):
    installed = await _installed(session, acting_user, role_session)
    await create_listing_with_terms(
        session, uid=LISTING, public_id=CLIENT, access="entitled"
    )
    await plugin_entitlements.store_statement(
        installed.guild.id, LISTING, version=7, values={"active": True, "plan": "pro"}
    )

    response = await client.get(f"{BASE}/entitlement", headers=_headers(installed))

    assert response.status_code == 200, response.text
    assert response.json() == {"version": 7, "values": {"active": True, "plan": "pro"}}


async def test_no_statement_is_404(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _installed(session, acting_user, role_session)

    response = await client.get(f"{BASE}/entitlement", headers=_headers(installed))

    assert response.status_code == 404
    assert response.json()["detail"] == PluginChannelMessages.NO_ENTITLEMENT


async def test_entitlement_needs_an_installation_token(client: AsyncClient):
    response = await client.get(f"{BASE}/entitlement")

    assert response.status_code == 401


async def _metered(session, acting_user, role_session):
    installed = await _installed(session, acting_user, role_session)
    await create_listing_with_terms(
        session,
        uid=LISTING,
        public_id=CLIENT,
        access="open",
        mandatory=True,
        meters=["runs"],
    )
    return installed


async def _report(client, installed, meter="runs", period="2026-10", **body):
    response = await client.put(
        f"{BASE}/usage/{meter}/{period}",
        json={"quantity": 5, "as_of": "2026-10-16T12:00:00Z", **body},
        headers=_headers(installed),
    )
    await post_commit.settle_all()
    return response


async def test_a_total_is_kept_and_passed_on_to_billing(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    shipped_root,
    billing_sent,
):
    installed = await _metered(session, acting_user, role_session)

    response = await _report(client, installed, quantity=12)

    assert response.status_code == 200, response.text
    assert response.json() == {"meter": "runs", "period": "2026-10", "quantity": 12}
    rows = (await session.exec(select(PluginUsage))).all()
    assert [
        (r.guild_id, r.listing_uid, r.meter, r.period, r.quantity) for r in rows
    ] == [(installed.guild.id, LISTING, "runs", "2026-10", 12)]
    [(url, body, headers)] = billing_sent
    assert url == f"{BILLING}{billing_ping.USAGE_PING_PATH}"
    assert url == "https://billing.test/api/v1/pings/usage"
    event_id = body.pop("event_id")
    assert isinstance(event_id, str) and event_id
    assert body == {
        "community_ref": await billing_guild_ref(installed.guild.id),
        "listing_uid": LISTING,
        "meter": "runs",
        "period": "2026-10",
        "quantity": 12,
    }
    signed = json.dumps({**body, "event_id": event_id}, separators=(",", ":"))
    assert (
        headers["X-Billing-Signature"]
        == hmac.new(
            SECRET.encode(),
            "\n".join(
                [
                    "POST",
                    "/api/v1/pings/usage",
                    headers["X-Billing-Timestamp"],
                    hashlib.sha256(signed.encode()).hexdigest(),
                ]
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
    )


async def test_the_same_total_again_is_accepted_and_a_lower_one_is_not(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    shipped_root,
    billing_sent,
):
    installed = await _metered(session, acting_user, role_session)
    await _report(client, installed, quantity=12)

    again = await _report(client, installed, quantity=12)
    lower = await _report(client, installed, quantity=11)
    another_month = await _report(client, installed, period="2026-11", quantity=1)

    assert again.status_code == 200
    assert lower.status_code == 409
    assert lower.json()["detail"] == PluginChannelMessages.USAGE_TOTAL_DECREASED
    assert another_month.status_code == 200
    assert [body["quantity"] for _, body, _ in billing_sent] == [12, 12, 1]


async def test_a_meter_the_terms_do_not_name_is_refused(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    shipped_root,
    billing_sent,
):
    installed = await _metered(session, acting_user, role_session)

    response = await _report(client, installed, meter="seats")

    assert response.status_code == 403
    assert response.json()["detail"] == PluginChannelMessages.METER_NOT_ALLOWED
    assert billing_sent == []


async def test_every_meter_is_refused_without_terms(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _installed(session, acting_user, role_session)

    response = await _report(client, installed)

    assert response.status_code == 403
    assert response.json()["detail"] == PluginChannelMessages.METER_NOT_ALLOWED


async def test_terms_under_another_root_allow_no_meter(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, monkeypatch
):
    monkeypatch.setattr(tuf_registry, "configured_root_is_builtin", lambda: False)
    installed = await _metered(session, acting_user, role_session)

    response = await _report(client, installed)

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("meter", "period", "body"),
    [
        ("runs", "2026-13", {}),
        ("runs", "202610", {}),
        ("Runs!", "2026-10", {}),
        ("runs", "2026-10", {"quantity": -1}),
        ("runs", "2026-10", {"quantity": 1.5}),
        ("runs", "2026-10", {"quantity": "3"}),
        ("runs", "2026-10", {"as_of": "yesterday"}),
        ("runs", "2026-10", {"as_of": "2026-10-16T12:00:00"}),
    ],
)
async def test_a_malformed_report_is_refused(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    shipped_root,
    meter,
    period,
    body,
):
    installed = await _metered(session, acting_user, role_session)

    response = await _report(client, installed, meter=meter, period=period, **body)

    assert response.status_code == 422
