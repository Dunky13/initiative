/**
 * The tab names the tool the route is in — read from the registry, so a tool's
 * own pages, the things it holds and its settings all name it, and a page
 * that is no tool's leaves the title alone.
 */
import { waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { useToolPageTitle } from "./useToolPageTitle";

const Page = () => {
  useToolPageTitle();
  return null;
};

const visit = (initialRoute: string, routeParams: Record<string, string>) =>
  renderPage(Page, { initialRoute, routeParams });

beforeEach(() => {
  document.title = "Initiative";
  server.use(
    communityHttp.get("/projects/:id", () => HttpResponse.json({ id: 1, name: "Sprint 3" })),
    communityHttp.get("/wikis/:id", () => HttpResponse.json({ id: 4, name: "Handbook" })),
    communityHttp.get("/files/:id", () => HttpResponse.json({ id: 8, name: "Map" }))
  );
});

afterEach(() => {
  document.title = "Initiative";
});

describe("useToolPageTitle", () => {
  it("names the tool on its own page", async () => {
    visit("/c/$communityId/i/$initiativeId/projects/$projectId", {
      communityId: "3",
      initiativeId: "5",
      projectId: "1",
    });
    await waitFor(() => expect(document.title).toBe("Sprint 3 - Initiative"));
  });

  it("names the parent tool on a page of something it holds", async () => {
    visit("/c/$communityId/i/$initiativeId/wikis/$wikiId/pages/$pageId", {
      communityId: "3",
      initiativeId: "5",
      wikiId: "4",
      pageId: "11",
    });
    await waitFor(() => expect(document.title).toBe("Handbook - Initiative"));
  });

  it("names the wiki, not the file, when a file is read inside a wiki", async () => {
    visit("/c/$communityId/i/$initiativeId/wikis/$wikiId/files/$fileId", {
      communityId: "3",
      initiativeId: "5",
      wikiId: "4",
      fileId: "8",
    });
    await waitFor(() => expect(document.title).toBe("Handbook - Initiative"));
  });

  it("names the tool on its settings", async () => {
    visit("/c/$communityId/i/$initiativeId/projects/$projectId/settings/access", {
      communityId: "3",
      initiativeId: "5",
      projectId: "1",
    });
    await waitFor(() => expect(document.title).toBe("Sprint 3 - Initiative"));
  });

  it("puts the title back when it leaves", async () => {
    const { unmount } = visit("/c/$communityId/i/$initiativeId/projects/$projectId", {
      communityId: "3",
      initiativeId: "5",
      projectId: "1",
    });
    await waitFor(() => expect(document.title).toBe("Sprint 3 - Initiative"));
    unmount();
    expect(document.title).toBe("Initiative");
  });
});
