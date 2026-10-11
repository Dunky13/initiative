import { HttpResponse } from "msw";

import { communityHttp } from "../communityHttp";

export const activityHandlers = [
  // The community home reads its feed on every render; tests that care about
  // the feed override it with their own entries.
  communityHttp.get("/activity/", () => {
    return HttpResponse.json({ items: [], page: 1, page_size: 20, has_next: false });
  }),
];
