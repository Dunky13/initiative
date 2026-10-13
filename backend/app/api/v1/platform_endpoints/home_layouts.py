"""The marketplace's home layouts, for a person's own home page (``/me``).

Adding one is the client's: it becomes a view in the reader's preferences, so
there is nothing to write here and no install to record. This is the shelf.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, UserSessionDep
from app.schemas.platform.home_layout import (
    HomeLayoutGrid,
    HomeLayoutListing,
    HomeLayoutListResponse,
    HomeLayoutWidget,
)
from app.services.platform import home_layouts as home_layouts_service

me_router = APIRouter()


def _entry(offered: home_layouts_service.HomeLayoutListing) -> HomeLayoutListing:
    listing, version = offered.listing, offered.version
    return HomeLayoutListing(
        uid=listing.uid,
        public_id=listing.public_id,
        name=listing.name,
        publisher=listing.publisher,
        description=listing.description,
        long_description=listing.long_description,
        avatar_url=listing.avatar_url,
        version=version.version,
        widgets=[
            HomeLayoutWidget(
                id=widget["id"],
                type=widget["type"],
                grid=HomeLayoutGrid(**widget["grid"]),
                options=widget.get("options"),
            )
            for widget in version.definition["widgets"]
        ],
    )


@me_router.get("/home-layouts", response_model=HomeLayoutListResponse)
async def list_home_layouts(
    session: UserSessionDep,
    _current_user: CurrentUser,
) -> HomeLayoutListResponse:
    """The home layouts this deployment offers, each ready to add as a view.

    The shelf is the marketplace catalog, so a layout that ships with the build
    and one published to the deployment read the same here. Every one was held
    to the widgets this build draws when it was published.
    """
    offered = await home_layouts_service.available_home_layouts(session)
    return HomeLayoutListResponse(items=[_entry(each) for each in offered])
