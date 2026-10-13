"""The shelf of home layouts a person can add."""

import copy

from app.services.marketplace import catalog as marketplace_catalog
from app.services.marketplace.builtin import load_builtin_manifests
from app.services.platform import home_layouts


async def test_the_shelf_reads_every_page_of_layouts(session, monkeypatch):
    """A deployment with more layouts than one page holds offers all of them."""
    template = next(
        m for m in load_builtin_manifests() if m.get("kind") == "home_layout"
    )
    for n in range(5):
        manifest = copy.deepcopy(template)
        manifest["uid"] = f"HMPAGETESTXY{n:02d}"
        manifest["public_id"] = f"core.home-page-test-{n}"
        await marketplace_catalog.upsert_listing(session, manifest, source="builtin")
    await session.commit()
    monkeypatch.setattr(home_layouts, "_PAGE", 2)

    offered = await home_layouts.available_home_layouts(session)

    assert {each.listing.public_id for each in offered} >= {
        f"core.home-page-test-{n}" for n in range(5)
    }
