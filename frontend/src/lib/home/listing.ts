import type { HomeLayoutListing } from "@/api/generated/initiativeAPI.schemas";

import { HOME_LAYOUT_VERSION, type HomeLayout, readHomeLayout } from "./layout";

/**
 * A marketplace layout as a page to add. Read like a stored one, so a widget a
 * later build added and this one does not draw is left out rather than
 * breaking the view; the server already held the rest to the widgets it knows.
 */
export const layoutFromListing = (listing: HomeLayoutListing): HomeLayout =>
  readHomeLayout({ version: HOME_LAYOUT_VERSION, widgets: listing.widgets }) ?? {
    version: HOME_LAYOUT_VERSION,
    widgets: [],
  };
