import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { buildActivityEntry, buildCommunity } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { FeedView, Tool } from "@/api/generated/initiativeAPI.schemas";
import type { ActivityScope } from "@/lib/recentRoute";

import { CommunityActivityFeed } from "./CommunityActivityFeed";

/** The drawer's feed, moved from one project to another while it is open. */
function MovingFeed() {
  const [scope, setScope] = useState<ActivityScope>({ tool: Tool.project, toolId: 1 });
  return (
    <>
      <button type="button" onClick={() => setScope({ tool: Tool.project, toolId: 2 })}>
        Next project
      </button>
      <CommunityActivityFeed view={FeedView.all} lastVisit={null} scope={scope} />
    </>
  );
}

describe("CommunityActivityFeed", () => {
  it("shows nothing of the last place's activity while the next one's arrives", async () => {
    let release = () => {};
    const arrived = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      communityHttp.get("/activity/", async ({ request }) => {
        const toolId = new URL(request.url).searchParams.get("tool_id");
        // The second place's feed is held until the first has been looked for.
        if (toolId === "2") await arrived;
        const items = toolId === "1" ? [buildActivityEntry({ title: "The first project's" })] : [];
        return HttpResponse.json({ items, page: 1, page_size: 20, has_next: false });
      })
    );
    const user = userEvent.setup();

    renderPage(MovingFeed, {
      communities: { activeCommunityId: 1, activeCommunity: buildCommunity({ id: 1 }) },
    });
    await screen.findByText("The first project's");
    await user.click(screen.getByRole("button", { name: "Next project" }));

    expect(screen.queryByText("The first project's")).not.toBeInTheDocument();
    release();
    expect(await screen.findByText("Nothing has changed here this week.")).toBeInTheDocument();
  });
});
