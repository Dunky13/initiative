/**
 * A moderator's menu on one thing: what it offers, and the warning it sends
 * without taking the thing down.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { ModerationMenu } from "./ModerationMenu";

const render = (canModerate = true) =>
  renderWithProviders(
    <ModerationMenu targetType="post" targetId={12} canModerate={canModerate} communityId={3} />,
    { auth: { user: buildUser() } }
  );

describe("ModerationMenu", () => {
  it("warns whoever wrote it in the moderator's words, and leaves it up", async () => {
    let acted: Record<string, unknown> | undefined;
    server.use(
      communityHttp.post("/moderation/acts", async ({ request }) => {
        acted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: 1 }, { status: 201 });
      })
    );
    const user = userEvent.setup();
    render();

    await user.click(screen.getByRole("button", { name: "Moderate" }));
    await user.click(await screen.findByRole("menuitem", { name: "Warn…" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("What they're told"), "Keep it civil.");
    await user.click(within(dialog).getByRole("button", { name: "Send warning" }));

    await waitFor(() =>
      expect(acted).toEqual({
        target_type: "post",
        target_id: 12,
        act: "warn",
        note: "Keep it civil.",
      })
    );
  });

  it("shows nothing to somebody who doesn't moderate it", () => {
    const { container } = render(false);
    expect(container).toBeEmptyDOMElement();
  });
});
