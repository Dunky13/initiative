import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { FollowButton } from "./FollowButton";

const state = (followed_at: string | null) => ({
  entity_type: "task",
  entity_id: 7,
  viewed_at: null,
  view_source: null,
  starred_at: null,
  followed_at,
});

describe("FollowButton", () => {
  it("reads whether the item is followed, follows it, and puts it back when that fails", async () => {
    const user = userEvent.setup();
    let followed: string | null = null;
    let fail = false;
    const written: string[] = [];
    server.use(
      http.get("/api/v1/c/3/personal-items/task/7", () => HttpResponse.json(state(followed))),
      http.put("/api/v1/c/3/personal-items/follow/:kind/:id", ({ params }) => {
        written.push(`follow ${params.kind}/${params.id}`);
        if (fail) return new HttpResponse(null, { status: 404 });
        followed = "2026-10-17T00:00:00Z";
        return HttpResponse.json(state(followed));
      }),
      http.delete("/api/v1/c/3/personal-items/follow/:kind/:id", ({ params }) => {
        written.push(`unfollow ${params.kind}/${params.id}`);
        followed = null;
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<FollowButton kind="task" entityId={7} />, {
      communities: { activeCommunityId: 3 },
    });

    const button = await screen.findByRole("button", { name: "Follow" });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    const following = await screen.findByRole("button", { name: "Stop following" });
    expect(following).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(following).toBeEnabled());

    await user.click(following);
    await screen.findByRole("button", { name: "Follow" });
    expect(written).toEqual(["follow task/7", "unfollow task/7"]);

    fail = true;
    await waitFor(() => expect(screen.getByRole("button", { name: "Follow" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Follow" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Follow" })).toHaveAttribute(
        "aria-pressed",
        "false"
      )
    );
  });
});
