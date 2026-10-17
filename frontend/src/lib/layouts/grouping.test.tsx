import { describe, expect, it } from "vitest";

import {
  buildDefaultTaskStatuses,
  buildPropertyDefinition,
  buildPropertyOption,
  buildTagSummary,
  buildTask,
  buildTaskAssignee,
} from "@/__tests__/factories";
import {
  PropertyType,
  type TaskListRead,
  type TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { propertyFieldId } from "@/lib/layouts/fields";
import {
  groupRowId,
  groupRows,
  NO_GROUP,
  taskGroupings,
  uniqueTasksFromRows,
} from "@/lib/layouts/grouping";
import { taskFields } from "@/lib/layouts/tasks";
import type { TranslateFn } from "@/types/i18n";

const t = ((key: string) => key) as TranslateFn;

const sprint = buildPropertyDefinition({
  name: "Sprint",
  type: PropertyType.multi_select,
  options: [buildPropertyOption({ value: "s1" }), buildPropertyOption({ value: "s2" })],
});
const note = buildPropertyDefinition({ name: "Note", type: PropertyType.text });

const groupingsOf = (tasks: TaskListRead[], statuses = buildDefaultTaskStatuses()) =>
  taskGroupings({
    fields: taskFields([sprint, note]),
    definitions: [sprint, note],
    statuses,
    tasks,
    t,
  });
const groupingOf = (column: string, tasks: TaskListRead[] = [], statuses?: TaskStatusRead[]) => {
  const grouping = groupingsOf(tasks, statuses).find((each) => each.column === column);
  if (!grouping) throw new Error(`no grouping ${column}`);
  return grouping;
};

describe("taskGroupings", () => {
  it("offers a field whose values group, and not one whose values don't", () => {
    const columns = groupingsOf([]).map((each) => each.column);

    expect(columns).toEqual(expect.arrayContaining(["priority group", "assignees group"]));
    expect(columns).toContain(`${propertyFieldId(sprint.id)} group`);
    expect(columns).not.toContain(`${propertyFieldId(note.id)} group`);
    expect(columns).not.toContain("title group");
  });

  it("orders statuses as the board does and priorities most urgent first", () => {
    const statuses = buildDefaultTaskStatuses();
    const [todo, doing, done] = statuses;
    const keys = [done, todo, doing].map((status) => String(status.id));
    const priorities = ["low", "urgent", "medium"];

    expect(keys.sort(groupingOf("status group", [], statuses).compare)).toEqual(
      [todo, doing, done].map((status) => String(status.id))
    );
    expect(priorities.sort(groupingOf("priority group").compare)).toEqual([
      "urgent",
      "medium",
      "low",
    ]);
  });

  it("orders people by name, with the unassigned last", () => {
    const zed = buildTaskAssignee({ id: 1, display_name: "Zed" });
    const ada = buildTaskAssignee({ id: 2, display_name: "Ada" });
    const people = groupingOf("assignees group", [buildTask({ assignees: [zed, ada] })]);

    expect([NO_GROUP, "1", "2"].sort(people.compare)).toEqual(["2", "1", NO_GROUP]);
  });

  it("moves a person off the group a task came from and onto the one it went to", () => {
    const people = groupingOf("assignees group");

    expect(people.move?.("1", "2")).toEqual({
      patch: { add_assignee_ids: [2], remove_assignee_ids: [1] },
    });
    expect(people.move?.("1", NO_GROUP)).toEqual({
      patch: { add_assignee_ids: [], remove_assignee_ids: [1] },
    });
  });

  it("changes one option of a multi-select, against what the task holds", () => {
    const sprints = groupingOf(`${propertyFieldId(sprint.id)} group`);

    expect(sprints.move?.("s1", "s2")).toEqual({
      properties: {
        merge: true,
        options: [{ property_id: sprint.id, add: ["s2"], remove: ["s1"] }],
      },
    });
  });

  it("can't move a task between date windows", () => {
    expect(groupingOf("date group").move).toBeUndefined();
  });
});

describe("groupRows", () => {
  const bug = buildTagSummary({ name: "bug" });
  const urgent = buildTagSummary({ name: "urgent" });

  it("lists a task under each of its tags, and one without any in the empty group", () => {
    const tagged = buildTask({ id: 7, tags: [bug, urgent] });
    const bare = buildTask({ id: 8, tags: [] });
    const tags = groupingOf("tags group", [tagged, bare]);

    const rows = groupRows([tagged, bare], tags);

    expect(rows.map(groupRowId)).toEqual([`7::${bug.id}`, `7::${urgent.id}`, "8::"]);
    expect("group" in tagged).toBe(false);
  });

  it("keeps the plain task id when the table is not grouped", () => {
    expect(groupRowId(buildTask({ id: 7 }))).toBe("7");
  });

  it("collapses a task's rows back to the task the list holds", () => {
    const tagged = buildTask({ tags: [bug, urgent] });
    const tags = groupingOf("tags group", [tagged]);

    const selected = uniqueTasksFromRows(groupRows([tagged], tags), new Map([[tagged.id, tagged]]));

    expect(selected).toEqual([tagged]);
    expect(selected[0]).toBe(tagged);
  });
});
