import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildGalleryImage } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { GalleryImageRead } from "@/api/generated/initiativeAPI.schemas";

import { GalleryImageSheet } from "./GalleryImageSheet";

/** Serves `image`, and each change as the server would answer it. */
const serve = (image: GalleryImageRead) => {
  const sent: Record<string, unknown>[] = [];
  server.use(
    communityHttp.get("/galleries/:galleryId/images/:imageId", () => HttpResponse.json(image)),
    communityHttp.get("/galleries/:galleryId/images/:imageId/versions", () =>
      HttpResponse.json([])
    ),
    communityHttp.patch("/galleries/:galleryId/images/:imageId", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      sent.push(body);
      return HttpResponse.json(Object.assign(image, body));
    })
  );
  return sent;
};

// Drawn on a page: its caption, like a description, holds the page while unsaved.
const open = (image: GalleryImageRead, canEdit = true) =>
  renderPage(() => (
    <GalleryImageSheet
      galleryId={1}
      initiativeId={1}
      image={image}
      open
      onOpenChange={() => {}}
      canEdit={canEdit}
      canDeleteVersions={false}
      isCover={false}
      onSetCover={() => {}}
      onRemoved={() => {}}
    />
  ));

describe("a picture, opened", () => {
  it("is drawn as its gallery lays it out, each field saved on its own", async () => {
    const image = buildGalleryImage({ id: 5, title: "Sketch" });
    const sent = serve(image);
    open(image);
    const user = userEvent.setup();

    const title = await screen.findByDisplayValue("Sketch");
    await user.clear(title);
    await user.type(title, "Final{Enter}");

    await waitFor(() => expect(sent).toEqual([{ title: "Final" }]));
  });

  it("shows a reader what it holds, with nothing to change it with", async () => {
    const image = buildGalleryImage({ id: 6, title: "Sketch", caption: "Round one" });
    serve(image);
    open(image, false);

    expect(await screen.findByRole("heading", { level: 1, name: "Sketch" })).toBeInTheDocument();
    expect(screen.getByText("Round one")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
