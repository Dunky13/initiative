"""The home layouts a person can add to their home page.

A home layout is a marketplace listing that installs to a *person*: adding one
makes a new view on their own home page, which lives in their preferences on
the client. So nothing is written here — the server's part is offering the
catalog's layouts, already checked against the widgets this build draws
(``app.services.marketplace.home_layouts``) when they were published.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.services.marketplace import catalog as catalog_service

__all__ = ["HomeLayoutListing", "available_home_layouts"]


@dataclass(frozen=True)
class HomeLayoutListing:
    """A home layout listing and the published version a reader would add."""

    listing: MarketplaceListing
    version: MarketplaceListingVersion


#: More layouts than a shelf would ever hold; the store reads them all at once.
_MAX_LAYOUTS = 100


async def available_home_layouts(session: AsyncSession) -> list[HomeLayoutListing]:
    """Every home layout this deployment offers, with the widgets each places.

    Read from the catalog, like any listing: one that ships with the build and
    one published to the deployment differ only by where they came from. A
    listing whose published version places nothing is not offered.
    """
    listings, _total = await catalog_service.list_listings(
        session, kind="home_layout", page_size=_MAX_LAYOUTS
    )
    versions = await catalog_service.get_listing_versions(
        session, [listing.latest_version_id for listing in listings]
    )
    offered = []
    for listing in listings:
        version = versions.get(listing.latest_version_id)
        widgets = ((version.definition if version is not None else None) or {}).get(
            "widgets"
        )
        if version is not None and isinstance(widgets, list) and widgets:
            offered.append(HomeLayoutListing(listing=listing, version=version))
    return offered
