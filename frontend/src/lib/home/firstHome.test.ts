import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient } from "@/__tests__/helpers/render";

import { firstHomeLayout, seedFirstHome } from "./firstHome";
import { HOME_GRID_COLUMNS, readHomeLayout } from "./layout";
import { HOME_VIEWS_KEY, homeViewKey, MAIN_VIEW_ID } from "./views";

const list = { communityId: 4, initiativeId: 2, projectId: 9 };

describe("firstHomeLayout", () => {
  it.each([
    ["personal", "myDay"],
    ["shared", "owner"],
    ["join", "community"],
    ["invite", "community"],
  ] as const)(
    "starts a %s sign-up on the %s layout, with getting started first",
    (path, preset) => {
      const layout = firstHomeLayout(path);
      expect(layout.preset).toBe(preset);
      const order = [...layout.widgets]
        .sort((a, b) => a.grid.y - b.grid.y || a.grid.x - b.grid.x)
        .map((widget) => widget.type);
      expect(order.slice(0, 2)).toEqual(["greeting", "gettingStarted"]);
      expect(layout.widgets.find((w) => w.type === "gettingStarted")?.options).toEqual({ path });
      // Nothing clamped, dropped or stacked on anything else.
      expect(readHomeLayout(JSON.parse(JSON.stringify(layout)))).toEqual(layout);
      const cells = new Set<string>();
      for (const { grid } of layout.widgets) {
        expect(grid.x + grid.w).toBeLessThanOrEqual(HOME_GRID_COLUMNS);
        for (let x = grid.x; x < grid.x + grid.w; x++) {
          for (let y = grid.y; y < grid.y + grid.h; y++) {
            expect(cells.has(`${x},${y}`)).toBe(false);
            cells.add(`${x},${y}`);
          }
        }
      }
    }
  );

  it("points the widgets that read one community or list at the ones the flow made", () => {
    const personal = firstHomeLayout("personal", { communityId: 4, list });
    expect(personal.widgets.find((w) => w.type === "tasks")?.options).toEqual({ addTo: list });
    expect(personal.widgets.find((w) => w.type === "gettingStarted")?.options).toMatchObject({
      list,
    });

    const shared = firstHomeLayout("shared", { communityId: 4 });
    expect(shared.widgets.find((w) => w.type === "activity")?.options).toEqual({ communityId: 4 });
  });
});

describe("seedFirstHome", () => {
  const serve = (items: Record<string, unknown>) => {
    const written: Record<string, unknown> = {};
    server.use(
      http.get("/api/v1/user-view-preferences", () => HttpResponse.json({ items })),
      http.put("/api/v1/user-view-preferences/:key", async ({ params, request }) => {
        written[String(params.key)] = ((await request.json()) as { value: unknown }).value;
        return new HttpResponse(null, { status: 204 });
      })
    );
    return written;
  };

  it("saves the first page for an account with no home of its own", async () => {
    const written = serve({});
    await seedFirstHome(createTestQueryClient(), "personal", { communityId: 4, list });
    expect(written[homeViewKey(MAIN_VIEW_ID)]).toEqual(
      firstHomeLayout("personal", { communityId: 4, list })
    );
  });

  it("leaves a home somebody already made alone", async () => {
    const written = serve({
      [HOME_VIEWS_KEY]: { version: 1, views: [{ id: "main", name: "Mine" }] },
    });
    await seedFirstHome(createTestQueryClient(), "join");
    expect(written).toEqual({});
  });
});
