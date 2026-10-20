import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildCalendarEvent, writerCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { CreateEventDialog } from "./CreateEventDialog";

const CALENDAR = {
  id: 7,
  name: "Rehearsals",
  description: null,
  color: "#336699",
  initiative_id: 3,
  community_id: 1,
  created_by: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  archived_at: null,
  can: writerCan(),
  comments_enabled: true,
  tags: [],
  grants: [],
};

describe("adding an event", () => {
  it("starts in the only calendar it can go in, and is made whole by Create", async () => {
    const sent: Record<string, unknown>[] = [];
    server.use(
      communityHttp.get("/calendars/", () =>
        HttpResponse.json({
          items: [CALENDAR],
          total_count: 1,
          page: 1,
          page_size: 200,
          has_next: false,
        })
      ),
      communityHttp.post("/calendar-events/", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        sent.push(body);
        return HttpResponse.json(buildCalendarEvent({ id: 9, calendar_id: 7 }));
      })
    );
    renderPage(() => (
      <CreateEventDialog open onOpenChange={() => {}} defaultStartDate="2026-10-20" />
    ));
    const user = userEvent.setup();

    expect(await screen.findByText("Rehearsals")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Event title"), "Dress rehearsal");
    await user.click(screen.getByRole("button", { name: "Create Event" }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({
      calendar_id: 7,
      title: "Dress rehearsal",
      all_day: false,
      start_at: new Date("2026-10-20T09:00:00").toISOString(),
      properties: [],
    });
    expect(sent[0].attendee_ids).toHaveLength(1);
  });
});
