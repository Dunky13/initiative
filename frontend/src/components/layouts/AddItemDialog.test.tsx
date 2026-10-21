import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildProjectTaskStatus, buildTaskType } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  QueueItemRead,
  TaskRead,
  TaskTypeRead,
  TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { blankQueueItem, QUEUE_ITEM_DETAIL } from "@/lib/layouts/queueItemLayout";
import { blankTask, TASK_DETAIL } from "@/lib/layouts/taskLayout";

import { AddItemDialog, type Written } from "./AddItemDialog";

/** A queue's Add Item, with the dialog closed and opened again by a button. */
const Adding = ({
  create,
}: {
  create: (written: Written<QueueItemRead, unknown>) => Promise<{ id: number }>;
}) => {
  const [open, setOpen] = useState(true);
  const leaving = useRef(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <AddItemDialog
        open={open}
        onOpenChange={setOpen}
        detail={QUEUE_ITEM_DETAIL}
        blank={blankQueueItem(1)}
        context={{ readOnly: false, queueId: 1, initiativeId: 1, leaving, actions: null }}
        layouts={() => null}
        title="Add Item"
        ready={(item) => item.label.trim() !== ""}
        create={create}
        onAdded={() => setOpen(false)}
      />
    </>
  );
};

describe("adding an item", () => {
  it("is drawn as its kind is laid out, and made whole by Add", async () => {
    const patched = vi.fn();
    server.use(
      communityHttp.patch("/queue-items/:itemId", () => {
        patched();
        return HttpResponse.json({});
      })
    );
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <Adding create={create} />);
    const user = userEvent.setup();

    const add = await screen.findByRole("button", { name: "Add Item" });
    expect(add).toBeDisabled();
    await user.type(screen.getByPlaceholderText("Item name"), "Goblin");
    const position = within(screen.getByRole("group", { name: "Position" })).getByRole(
      "spinbutton"
    );
    await user.clear(position);
    await user.type(position, "12");
    await user.click(add);

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({ fields: { label: "Goblin", position: 12 }, properties: [] })
      )
    );
    expect(patched).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Add Item" })).not.toBeInTheDocument()
    );
  });

  it("drops what was typed when it is closed", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <Adding create={create} />);
    const user = userEvent.setup();

    await user.type(await screen.findByPlaceholderText("Item name"), "Ogre");
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Open" }));

    expect(await screen.findByPlaceholderText("Item name")).toHaveValue("");
    expect(create).not.toHaveBeenCalled();
  });

  it("waits while a field is emptied or shows what it cannot take", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => <Adding create={create} />);
    const user = userEvent.setup();
    const add = await screen.findByRole("button", { name: "Add Item" });
    const label = screen.getByPlaceholderText("Item name");

    await user.type(label, "Imp");
    await user.clear(label);
    expect(add).toBeDisabled();

    await user.type(label, "Imp");
    const position = within(screen.getByRole("group", { name: "Position" })).getByRole(
      "spinbutton"
    );
    await user.type(position, "4");
    await user.clear(position);
    expect(add).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(create).not.toHaveBeenCalled();

    await user.type(position, "7");
    expect(add).toBeEnabled();
  });
});

/** A project's Create Task, where the task starts as Bug. */
const AddingTask = ({
  types,
  create,
}: {
  types: TaskTypeRead[];
  create: (written: Written<TaskRead, TaskUpdate>) => Promise<{ id: number }>;
}) => {
  const leaving = useRef(false);
  const status = buildProjectTaskStatus();
  return (
    <AddItemDialog
      open
      onOpenChange={() => {}}
      detail={TASK_DETAIL}
      blank={blankTask(1, status, types[0])}
      context={{
        readOnly: false,
        readOnlyMessage: null,
        statuses: [status],
        types,
        initiativeId: 1,
        askScope: async () => null,
        actions: null,
        leaving,
      }}
      layouts={() => null}
      title="Create task"
      ready={() => true}
      create={create}
      onAdded={() => {}}
    />
  );
};

describe("adding a task", () => {
  const bug = () =>
    buildTaskType({
      name: "Bug",
      starting_values: {
        description: "What happened?",
        checklist: [],
        priority: "high",
        recurrence: null,
        recurrence_strategy: null,
      },
    });

  const pickType = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
    await user.click(screen.getByRole("combobox", { name: "Type" }));
    await user.click(await screen.findByRole("option", { name }));
  };

  it("starts with what its type starts with, and follows the type until it is changed", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => (
      <AddingTask types={[bug(), buildTaskType({ name: "Feature" })]} create={create} />
    ));
    const user = userEvent.setup();

    // Written, it opens on its preview; the box behind it holds the text.
    await screen.findByRole("combobox", { name: "Type" });
    const description = document.getElementById("task-description");
    expect(description).toHaveValue("What happened?");
    await pickType(user, "Feature");
    expect(description).toHaveValue("");
    await pickType(user, "Bug");
    expect(description).toHaveValue("What happened?");
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          item: expect.objectContaining({ description: "What happened?", priority: "high" }),
        })
      )
    );
  });

  it("keeps a description the person wrote when the type changes", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    renderPage(() => (
      <AddingTask types={[buildTaskType({ name: "Feature" }), bug()]} create={create} />
    ));
    const user = userEvent.setup();

    const description = await screen.findByRole("textbox", { name: "Description" });
    await user.type(description, "Mine");
    await pickType(user, "Bug");

    expect(description).toHaveValue("Mine");
  });

  it("keeps a priority the person picked when the type changes", async () => {
    const create = vi.fn(async () => ({ id: 5 }));
    const [feature, chore] = [
      buildTaskType({ name: "Feature" }),
      buildTaskType({
        name: "Chore",
        starting_values: {
          description: null,
          checklist: [],
          priority: "low",
          recurrence: null,
          recurrence_strategy: null,
        },
      }),
    ];
    renderPage(() => <AddingTask types={[feature, chore]} create={create} />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("combobox", { name: "Priority" }));
    await user.click(await screen.findByRole("option", { name: /Urgent/ }));
    await pickType(user, "Chore");
    await user.click(screen.getByRole("button", { name: "Create task" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          item: expect.objectContaining({ task_type_id: chore.id, priority: "urgent" }),
        })
      )
    );
  });
});
