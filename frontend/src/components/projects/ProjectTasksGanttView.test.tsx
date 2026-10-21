/**
 * A project's tasks on a time axis. What a drag writes, what a drag across an
 * empty track gives a task with no dates, and which dependencies are drawn
 * late.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildDefaultTaskStatuses, buildTask } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { TaskEdgeRead } from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksGanttView } from "@/components/projects/ProjectTasksGanttView";
import { DAY, PX_PER_DAY } from "@/lib/gantt";

const at = (iso: string) => new Date(`${iso}T09:00:00`).toISOString();

const mount = (
  tasks: ReturnType<typeof buildTask>[],
  edges: TaskEdgeRead[] = [],
  onReschedule = vi.fn(async () => undefined)
) => {
  server.use(communityHttp.get("/relationships/tasks", () => HttpResponse.json(edges)));
  const view = renderPage(
    () => (
      <ProjectTasksGanttView
        initiativeId={1}
        projectId={1}
        tasks={tasks}
        taskStatuses={buildDefaultTaskStatuses(1)}
        scale="week"
        grouping={[]}
        taskHref={(id) => `/tasks/${id}`}
        onReschedule={onReschedule}
      />
    ),
    { initialRoute: "/c/1" }
  );
  return { ...view, onReschedule };
};

describe("ProjectTasksGanttView", () => {
  it("moves a bar's dates by the days it is dragged", async () => {
    const task = buildTask({
      title: "Design",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const { onReschedule } = mount([task]);
    const bar = await screen.findByTitle(/^Design ·/);

    fireEvent.pointerDown(bar, { button: 0, clientX: 100 });
    fireEvent.pointerMove(bar, { clientX: 100 + 2 * PX_PER_DAY.week });
    fireEvent.pointerUp(bar);

    await waitFor(() => expect(onReschedule).toHaveBeenCalledTimes(1));
    const [moved, dates] = onReschedule.mock.calls[0] as unknown as [
      typeof task,
      { start_date: string; due_date: string },
    ];
    expect(moved.id).toBe(task.id);
    expect(dates).toEqual({ start_date: at("2026-03-04"), due_date: at("2026-03-06") });
  });

  it("gives a task with no dates the days dragged across its track", async () => {
    const task = buildTask({ title: "Someday", start_date: null, due_date: null });
    const { onReschedule } = mount([task]);
    const track = await screen.findByTitle("Drag across the days to give this task dates");

    // A click alone picks nothing.
    fireEvent.pointerDown(track, { button: 0, clientX: 0 });
    fireEvent.pointerUp(track);
    expect(onReschedule).not.toHaveBeenCalled();

    fireEvent.pointerDown(track, { button: 0, clientX: 0 });
    fireEvent.pointerMove(track, { clientX: 3 * PX_PER_DAY.week });
    fireEvent.pointerUp(track);
    await waitFor(() => expect(onReschedule).toHaveBeenCalledTimes(1));
    const [, dates] = onReschedule.mock.calls[0] as unknown as [
      unknown,
      { start_date: string; due_date: string },
    ];
    expect(Math.round((Date.parse(dates.due_date) - Date.parse(dates.start_date)) / DAY)).toBe(3);
  });

  it("draws a dependency late where the task starts before what it waits on ends", async () => {
    const first = buildTask({
      title: "First",
      start_date: at("2026-03-02"),
      due_date: at("2026-03-04"),
    });
    const after = buildTask({
      title: "After",
      start_date: at("2026-03-06"),
      due_date: at("2026-03-07"),
    });
    const early = buildTask({
      title: "Early",
      start_date: at("2026-03-03"),
      due_date: at("2026-03-05"),
    });
    const { container } = mount(
      [first, after, early],
      [
        { source_id: after.id, target_id: first.id, relationship_type: "depends_on" },
        { source_id: early.id, target_id: first.id, relationship_type: "depends_on" },
      ]
    );

    await waitFor(() => expect(container.querySelectorAll("path[marker-end]")).toHaveLength(2));
    const late = [...container.querySelectorAll("path[marker-end]")].map((path) =>
      path.classList.contains("stroke-destructive")
    );
    expect(late).toEqual([false, true]);
  });
});
