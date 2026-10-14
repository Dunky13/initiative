import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { FavoriteButton } from "./FavoriteButton";

const starredQueue = {
  entity_type: "queue",
  entity_id: 7,
  community_id: 3,
  initiative_id: 2,
  name: "Tea rota",
  favorited_at: "2026-10-10T00:00:00Z",
  icon: null,
  file_type: null,
  mime_type: null,
  original_filename: null,
};

describe("FavoriteButton", () => {
  it("reads its star from the community's list and stars a tool of any kind", async () => {
    const user = userEvent.setup();
    let favorites: (typeof starredQueue)[] = [];
    const written: string[] = [];
    server.use(
      http.get("/api/v1/c/3/favorites", () => HttpResponse.json(favorites)),
      http.post("/api/v1/c/3/favorites/:tool/:id", ({ params }) => {
        written.push(`${params.tool}/${params.id}`);
        favorites = [starredQueue];
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<FavoriteButton tool="queue" entityId={7} name="Tea rota" />, {
      communities: { activeCommunityId: 3 },
    });

    const star = await screen.findByRole("button", { name: "Add to favorites" });
    expect(star).toHaveAttribute("aria-pressed", "false");
    await user.click(star);

    // Starred at once, and still starred once the list is read again.
    expect(await screen.findByRole("button", { name: "Remove from favorites" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(written).toEqual(["queue/7"]);
  });

  it("puts the star back when starring fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/c/3/favorites", () => HttpResponse.json([])),
      http.post("/api/v1/c/3/favorites/:tool/:id", () => new HttpResponse(null, { status: 404 }))
    );
    renderWithProviders(<FavoriteButton tool="file" entityId={9} />, {
      communities: { activeCommunityId: 3 },
    });

    await user.click(await screen.findByRole("button", { name: "Add to favorites" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add to favorites" })).toHaveAttribute(
        "aria-pressed",
        "false"
      )
    );
  });

  it("takes no second click until the first write lands", async () => {
    const user = userEvent.setup();
    let release: () => void = () => {};
    const landed = new Promise<void>((resolve) => {
      release = resolve;
    });
    const writes: string[] = [];
    server.use(
      http.get("/api/v1/c/3/favorites", () => HttpResponse.json([])),
      http.post("/api/v1/c/3/favorites/:tool/:id", async () => {
        writes.push("star");
        await landed;
        await delay(0);
        return new HttpResponse(null, { status: 204 });
      }),
      http.delete("/api/v1/c/3/favorites/:tool/:id", () => {
        writes.push("unstar");
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<FavoriteButton tool="queue" entityId={7} />, {
      communities: { activeCommunityId: 3 },
    });

    await user.click(await screen.findByRole("button", { name: "Add to favorites" }));
    const star = screen.getByRole("button", { name: "Remove from favorites" });
    expect(star).toBeDisabled();
    await user.click(star);
    expect(writes).toEqual(["star"]);

    release();
    await waitFor(() => expect(star).toBeEnabled());
    await user.click(star);
    await waitFor(() => expect(writes).toEqual(["star", "unstar"]));
  });
});
