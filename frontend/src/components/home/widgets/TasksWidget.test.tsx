import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it, onTestFinished } from "vitest";

import { buildProjectTaskStatus, buildTagSummary, buildTask } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { keepViewPreferences } from "@/__tests__/helpers/viewPreferences";
import { setInvalidationCommunity } from "@/api/query-keys";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";

import { TasksWidget as Widget } from "./TasksWidget";

/** The widget as the home page places it, with no options of its own. */
const TasksWidget = () => (
  <Widget
    widget={{ id: "tasks", type: "tasks", grid: { x: 0, y: 0, w: 12, h: 10 } }}
    options={{}}
    onOptionsChange={() => undefined}
    stacked={false}
    onConfigure={() => undefined}
    onRemove={() => undefined}
  />
);

/** Serve one page of assigned tasks; the list has to be non-empty to render. */
function stubTasks() {
  const requests: URLSearchParams[] = [];
  server.use(
    http.get("/api/v1/me/tasks", ({ request }) => {
      requests.push(new URL(request.url).searchParams);
      return HttpResponse.json({
        items: [buildTask({ title: "Write the thing" })],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_next: false,
      });
    })
  );
  return requests;
}

function renderMyTasks() {
  const queryClient = createTestQueryClient();
  // Skip the preferences fetch so the table mounts with its defaults.
  queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, { items: {} });
  return renderPage(TasksWidget, { queryClient });
}

/** Serve saved preferences, optionally after the tasks request has resolved. */
function stubPreferences(prefs: unknown, { delayMs = 0 } = {}) {
  server.use(
    http.get("/api/v1/user-view-preferences", async () => {
      if (delayMs > 0) await delay(delayMs);
      return HttpResponse.json({ items: { "initiative-my-tasks-filters": prefs } });
    })
  );
}

const groupSelect = () => screen.getByRole("combobox", { name: /group by/i });

/** The table's own requests. The focus summary reads the same endpoint with a
 *  page size of its own, and asks for its own "due soonest" order. */
const tableRequests = (requests: URLSearchParams[]) =>
  requests.filter((params) => params.get("page_size") === "20");

describe("TasksWidget saved sort", () => {
  it("waits for the saved sort before asking for rows or mounting the table", async () => {
    const requests = stubTasks();
    // Preferences land after the tasks request, which is the case that used to
    // freeze the headers on the default sort.
    stubPreferences({ sorting: [{ field: "priority", dir: "desc" }] }, { delayMs: 50 });
    renderPage(TasksWidget, { queryClient: createTestQueryClient() });

    // Nothing is drawn on the defaults in the meantime, and nothing is asked
    // for in them either.
    expect(screen.queryByRole("columnheader")).not.toBeInTheDocument();
    expect(tableRequests(requests)).toHaveLength(0);

    // Once the saved sort is in hand the table mounts seeded with it — the
    // header carries a direction arrow rather than the unsorted glyph, so it
    // agrees with the order the rows came back in.
    const priorityHeader = await screen.findByRole("columnheader", { name: /priority/i });
    const icon = within(priorityHeader).getByRole("button").querySelector("svg");
    expect(icon).toHaveClass("lucide-arrow-down");

    // And the rows under them were fetched in that order — one request, in the
    // saved sort, rather than the default sort followed by a throwaway refetch.
    expect(tableRequests(requests)).toHaveLength(1);
    // Ties keep the project's own order, as on a project's table.
    expect(JSON.parse(tableRequests(requests)[0].get("sorting") ?? "[]")).toEqual([
      { field: "priority", dir: "desc" },
      { field: "position", dir: "asc" },
    ]);
  });
});

describe("TasksWidget beside another", () => {
  it("shows the shared sort on both widgets' headers when one changes it", async () => {
    const user = userEvent.setup();
    stubTasks();
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, { items: {} });
    const widget = (id: string) => (
      <Widget
        widget={{ id, type: "tasks", grid: { x: 0, y: 0, w: 12, h: 10 } }}
        options={{}}
        onOptionsChange={() => undefined}
        stacked={false}
        onConfigure={() => undefined}
        onRemove={() => undefined}
      />
    );
    renderPage(
      () => (
        <>
          {widget("tasks")}
          {widget("tasks-2")}
        </>
      ),
      { queryClient }
    );

    await waitFor(() =>
      expect(screen.getAllByRole("columnheader", { name: /priority/i })).toHaveLength(2)
    );
    const [first] = screen.getAllByRole("columnheader", { name: /priority/i });
    await user.click(within(first).getByRole("button"));

    await waitFor(() => {
      for (const header of screen.getAllByRole("columnheader", { name: /priority/i })) {
        expect(within(header).getByRole("button").querySelector("svg")).not.toHaveClass(
          "lucide-arrow-up-down"
        );
      }
    });
  });
});

describe("TasksWidget grouping", () => {
  it("remembers the grouping choice for the next visit", async () => {
    const user = userEvent.setup();
    stubTasks();
    const kept = keepViewPreferences();
    const first = renderPage(TasksWidget, { queryClient: createTestQueryClient() });

    // Opens grouped by date window, as it always has.
    await waitFor(() => expect(groupSelect()).toHaveTextContent(/date/i));

    await user.click(groupSelect());
    await user.click(screen.getByRole("option", { name: "None" }));
    await waitFor(() => expect(groupSelect()).toHaveTextContent(/none/i));

    // It is kept for the reader, on any device.
    first.unmount();
    await waitFor(() => expect(kept["view:me:tasks"]).toBeDefined());
    renderPage(TasksWidget, { queryClient: createTestQueryClient() });
    await waitFor(() => expect(groupSelect()).toHaveTextContent(/none/i));
  });
});

describe("TasksWidget columns", () => {
  it("shows the columns its own options keep", async () => {
    stubTasks();
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, { items: {} });
    renderPage(
      () => (
        <Widget
          widget={{ id: "tasks-2", type: "tasks", grid: { x: 0, y: 0, w: 12, h: 10 } }}
          options={{ columns: { priority: false } }}
          onOptionsChange={() => undefined}
          stacked={false}
          onConfigure={() => undefined}
          onRemove={() => undefined}
        />
      ),
      { queryClient }
    );

    await screen.findByRole("columnheader", { name: /title|task/i });
    expect(screen.queryByRole("columnheader", { name: /priority/i })).not.toBeInTheDocument();
  });

  it("keeps a column change on the widget, not the reader's shared view", async () => {
    const user = userEvent.setup();
    stubTasks();
    const kept = keepViewPreferences();
    const saved: Record<string, unknown>[] = [];
    const addTo = { communityId: 4, initiativeId: 2, projectId: 9 };
    renderPage(
      () => (
        <Widget
          widget={{ id: "tasks", type: "tasks", grid: { x: 0, y: 0, w: 12, h: 10 } }}
          options={{ addTo }}
          onOptionsChange={(next) => saved.push(next)}
          stacked={false}
          onConfigure={() => undefined}
          onRemove={() => undefined}
        />
      ),
      { queryClient: createTestQueryClient() }
    );

    await screen.findByRole("columnheader", { name: /priority/i });
    await user.click(screen.getAllByRole("button", { name: /columns/i })[0]);
    await user.click(await screen.findByRole("menuitemcheckbox", { name: /priority/i }));

    await waitFor(() => expect(saved).toHaveLength(1));
    // What it kept before stays, and the hidden-by-default columns stay hidden.
    expect(saved[0]).toEqual({
      addTo,
      columns: expect.objectContaining({ priority: false, guild: false, "date group": false }),
    });
    expect(kept["view:me:tasks"]).toBeUndefined();
  });
});

describe("TasksWidget filters", () => {
  it("asks for the tasks its own filters name", async () => {
    const requests = stubTasks();
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, { items: {} });
    renderPage(
      () => (
        <Widget
          widget={{ id: "tasks-2", type: "tasks", grid: { x: 0, y: 0, w: 12, h: 10 } }}
          options={{ filters: { status_categories: ["done"], priorities: ["high"] } }}
          onOptionsChange={() => undefined}
          stacked={false}
          onConfigure={() => undefined}
          onRemove={() => undefined}
        />
      ),
      { queryClient }
    );

    await waitFor(() => expect(tableRequests(requests).length).toBeGreaterThan(0));
    const conditions = tableRequests(requests)[0].getAll("conditions").join(" ");
    expect(conditions).toMatch(/done/);
    expect(conditions).toMatch(/high/);
    expect(conditions).not.toMatch(/in_progress/);
  });

  it("clears back to the defaults on the widget, not the reader's shared view", async () => {
    const user = userEvent.setup();
    stubTasks();
    const kept = keepViewPreferences();
    const saved: Record<string, unknown>[] = [];
    renderPage(
      () => (
        <Widget
          widget={{ id: "tasks", type: "tasks", grid: { x: 0, y: 0, w: 12, h: 10 } }}
          options={{ filters: { status_categories: ["done"] } }}
          onOptionsChange={(next) => saved.push(next)}
          stacked={false}
          onConfigure={() => undefined}
          onRemove={() => undefined}
        />
      ),
      { queryClient: createTestQueryClient() }
    );

    await user.click(await screen.findByRole("button", { name: /filters/i }));
    await user.click(await screen.findByRole("button", { name: /clear/i }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0].filters).toMatchObject({
      status_categories: ["backlog", "todo", "in_progress"],
    });
    expect(kept["view:me:tasks"]).toBeUndefined();
  });
});

describe("TasksWidget status changes", () => {
  /**
   * One task per community so the per-row rules are observable: checking either
   * must not take the other away. The PATCH never answers, so each test reads
   * the row while its save is in flight.
   */
  function stubTwoTasksAndStatuses() {
    const todo = buildProjectTaskStatus({
      id: 10,
      project_id: 5,
      name: "To Do",
      category: "todo",
      position: 0,
      is_default: true,
    });
    const done = buildProjectTaskStatus({
      id: 11,
      project_id: 5,
      name: "Done",
      category: "done",
      position: 1,
    });
    const items = [
      buildTask({
        id: 101,
        title: "Write the thing",
        community_id: 3,
        project_id: 5,
        task_status_id: todo.id,
        task_status: todo,
      }),
      buildTask({
        id: 102,
        title: "Read the thing",
        community_id: 3,
        project_id: 5,
        task_status_id: todo.id,
        task_status: todo,
      }),
    ];
    server.use(
      // Only the table's page carries these rows. The focus summary reads the
      // same endpoint with a page size of its own, and answering it too would
      // put a second copy of every row on the screen.
      http.get("/api/v1/me/tasks", ({ request }) => {
        const forTable = new URL(request.url).searchParams.get("page_size") === "20";
        return HttpResponse.json({
          items: forTable ? items : [],
          total_count: forTable ? items.length : 0,
          page: 1,
          page_size: 20,
          has_next: false,
        });
      }),
      http.get("/api/v1/c/:communityId/projects/:projectId/task-statuses", () =>
        HttpResponse.json([todo, done])
      ),
      http.patch("/api/v1/c/:communityId/tasks/:taskId", async () => {
        await delay("infinite");
        return new HttpResponse(null, { status: 204 });
      })
    );
  }

  /** The table's Done checkboxes, in row order. */
  const doneBoxes = () =>
    within(screen.getByRole("table")).getAllByRole("checkbox", {
      name: /mark task as (done|in progress)/i,
    });

  /** A row title, looked for in the table rather than anywhere on the page. */
  const rowTitle = (title: string) => within(screen.getByRole("table")).findByText(title);

  it("shows the row checked before the server answers", async () => {
    const user = userEvent.setup();
    stubTwoTasksAndStatuses();
    renderMyTasks();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    await rowTitle("Write the thing");
    const [first] = doneBoxes();
    expect(first).not.toBeChecked();

    await user.click(first);

    // The check lands on the optimistic write, with the PATCH still in flight
    // and the cross-community list not yet refetched.
    await waitFor(() => expect(doneBoxes()[0]).toBeChecked());
  });

  it("leaves every other row usable while one is saving", async () => {
    const user = userEvent.setup();
    stubTwoTasksAndStatuses();
    renderMyTasks();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    await rowTitle("Read the thing");
    await user.click(doneBoxes()[0]);

    // The row being saved is held so it can't be double-submitted; the other
    // one — and the table around it — stays live. The old blocking overlay
    // disabled the whole page for the length of the request.
    await waitFor(() => expect(doneBoxes()[0]).toBeDisabled());
    expect(doneBoxes()[1]).toBeEnabled();
    await rowTitle("Read the thing");
  });

  it("can't check a task into its project's full done column", async () => {
    stubTwoTasksAndStatuses();
    server.use(
      http.get("/api/v1/c/:communityId/tasks/column-limits", () =>
        HttpResponse.json([{ project_id: 5, status_id: 11, limit: 1, count: 1 }])
      )
    );
    renderMyTasks();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    await rowTitle("Read the thing");
    await waitFor(() => expect(doneBoxes()[0]).toBeDisabled());
    expect(doneBoxes()[0]).toHaveAttribute("title", "Done is full");
    expect(doneBoxes()[1]).toBeDisabled();
  });

  it("frees a full column for the other rows once a task leaves it", async () => {
    // Home keeps the last community visited as the active one, and the
    // tasks are in another.
    setInvalidationCommunity(9);
    onTestFinished(() => setInvalidationCommunity(null));
    const user = userEvent.setup();
    const todo = buildProjectTaskStatus({ id: 10, project_id: 5, category: "todo", position: 0 });
    const done = buildProjectTaskStatus({ id: 11, project_id: 5, category: "done", position: 1 });
    const task = (id: number, title: string, status: typeof todo) =>
      buildTask({
        id,
        title,
        community_id: 3,
        project_id: 5,
        task_status_id: status.id,
        task_status: status,
      });
    let left = false;
    server.use(
      http.get("/api/v1/me/tasks", ({ request }) => {
        const forTable = new URL(request.url).searchParams.get("page_size") === "20";
        const items = [
          task(101, "Write the thing", left ? todo : done),
          task(102, "Plan the trip", todo),
        ];
        return HttpResponse.json({
          items: forTable ? items : [],
          total_count: forTable ? items.length : 0,
          page: 1,
          page_size: 20,
          has_next: false,
        });
      }),
      http.get("/api/v1/c/:communityId/projects/:projectId/task-statuses", () =>
        HttpResponse.json([todo, done])
      ),
      http.get("/api/v1/c/:communityId/tasks/column-limits", () =>
        HttpResponse.json([{ project_id: 5, status_id: done.id, limit: 1, count: left ? 0 : 1 }])
      ),
      http.patch("/api/v1/c/:communityId/tasks/:taskId", () => {
        left = true;
        return HttpResponse.json(task(101, "Write the thing", todo));
      })
    );
    renderMyTasks();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    await rowTitle("Plan the trip");
    const doneBoxOf = (title: string) =>
      within(
        within(screen.getByRole("table")).getByText(title).closest("tr") as HTMLElement
      ).getByRole("checkbox", { name: /mark task as (done|in progress)/i });
    await waitFor(() => expect(doneBoxOf("Plan the trip")).toBeDisabled());

    await user.click(doneBoxOf("Write the thing"));

    await waitFor(() => expect(doneBoxOf("Plan the trip")).toBeEnabled());
  });
});

describe("TasksWidget priority", () => {
  it("saves a priority change to the task's own community", async () => {
    const user = userEvent.setup();
    const task = buildTask({ id: 101, title: "Write the thing", community_id: 3, priority: "low" });
    const patched: string[] = [];
    server.use(
      http.get("/api/v1/me/tasks", ({ request }) => {
        const forTable = new URL(request.url).searchParams.get("page_size") === "20";
        return HttpResponse.json({
          items: forTable ? [task] : [],
          total_count: forTable ? 1 : 0,
          page: 1,
          page_size: 20,
          has_next: false,
        });
      }),
      http.patch("/api/v1/c/:communityId/tasks/:taskId", ({ params }) => {
        patched.push(`${params.communityId}/${params.taskId}`);
        return HttpResponse.json({ ...task, priority: "high" });
      })
    );
    renderMyTasks();

    await user.click(await screen.findByRole("button", { name: /priority: low/i }));
    await user.click(await screen.findByRole("menuitemradio", { name: "High" }));

    await waitFor(() => expect(patched).toEqual(["3/101"]));
  });
});

describe("TasksWidget links", () => {
  it("takes each row into its own community", async () => {
    const task = buildTask({
      id: 101,
      title: "Write the thing",
      community_id: 3,
      initiative_id: 2,
      project_id: 5,
      tags: [buildTagSummary({ id: 7, name: "Urgent" })],
    });
    server.use(
      http.get("/api/v1/me/tasks", ({ request }) => {
        const forTable = new URL(request.url).searchParams.get("page_size") === "20";
        return HttpResponse.json({
          items: forTable ? [task] : [],
          total_count: forTable ? 1 : 0,
          page: 1,
          page_size: 20,
          has_next: false,
        });
      })
    );
    renderMyTasks();

    const table = await screen.findByRole("table");
    expect(await within(table).findByRole("link", { name: "Write the thing" })).toHaveAttribute(
      "href",
      "/c/3/i/2/projects/5/tasks/101"
    );
    expect(within(table).getByRole("link", { name: "Urgent" })).toHaveAttribute(
      "href",
      "/c/3/tags/7"
    );
  });
});
