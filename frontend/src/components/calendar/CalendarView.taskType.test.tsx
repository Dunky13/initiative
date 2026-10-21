import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildTaskType } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { type CalendarEntry, CalendarView, type CalendarViewMode } from "./CalendarView";

const FOCUS = new Date("2026-06-15T12:00:00");
const bug = buildTaskType({ name: "Bug", icon: "bug" });

const entry = (overrides: Partial<CalendarEntry>): CalendarEntry => ({
  id: "task-9",
  title: "Fix the gate",
  startAt: "2026-06-15T00:00:00",
  endAt: "2026-06-15T00:00:00",
  allDay: true,
  kind: "due",
  taskType: bug,
  meta: { type: "task", taskId: 9 },
  ...overrides,
});

const show = (viewMode: CalendarViewMode, entries: CalendarEntry[]) =>
  renderWithProviders(
    <CalendarView
      entries={entries}
      viewMode={viewMode}
      onViewModeChange={vi.fn()}
      focusDate={FOCUS}
      onFocusDateChange={vi.fn()}
      onEntryClick={vi.fn()}
    />
  );

describe("a task's type on the calendar", () => {
  it.each(["month", "week", "day", "list"] as const)(
    "is named by the task's title in the %s view",
    async (viewMode) => {
      show(viewMode, [entry({})]);
      const title = await screen.findByText("Fix the gate");
      expect(title.parentElement).toHaveTextContent("Bug");
      expect(screen.getByTitle("Bug")).toBeInTheDocument();
    }
  );

  it("is named on a timed entry and a bar across days", async () => {
    show("week", [
      entry({
        id: "task-1",
        title: "Timed",
        startAt: "2026-06-15T09:00:00",
        endAt: "2026-06-15T11:00:00",
        allDay: false,
        kind: undefined,
      }),
      entry({
        id: "task-2",
        title: "Across",
        startAt: "2026-06-15T00:00:00",
        endAt: "2026-06-17T00:00:00",
        kind: undefined,
      }),
    ]);
    expect((await screen.findByText("Timed")).parentElement).toHaveTextContent("Bug");
    expect(screen.getByText("Across").parentElement).toHaveTextContent("Bug");
  });

  it("is left out for a task with no type to tell apart", async () => {
    show("month", [entry({ taskType: null })]);
    await screen.findByText("Fix the gate");
    expect(screen.queryByTitle("Bug")).toBeNull();
  });
});
