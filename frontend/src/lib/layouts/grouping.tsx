/**
 * How a project's tasks are grouped: by their date window or status, and by
 * any field whose values group cleanly. A grouping says which groups a task is
 * in, the order its groups go in, what each group's header shows, and what a
 * drop from one group into another changes. The table draws it as header rows.
 */

import type { ReactNode } from "react";

import {
  type PropertyDefinitionRead,
  type PropertySummary,
  PropertyType,
  type PropertyValuesSetRequest,
  type TaskListRead,
  type TaskPriority,
  type TaskStatusRead,
  type TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { extractUser, PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { TagBadge } from "@/components/tags/TagBadge";
import { TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { Badge } from "@/components/ui/badge";
import { collator } from "@/lib/intl";
import { type FieldDef, propertyFieldId } from "@/lib/layouts/fields";
import { priorityRank } from "@/lib/sorting";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { getUserDisplayName } from "@/lib/userDisplay";
import type { TranslateFn } from "@/types/i18n";

/** The key of the group a task with no value falls into. */
export const NO_GROUP = "";

/** What a drop from one group into another writes. */
export type GroupMove =
  | { status: number }
  | { patch: TaskUpdate }
  | { tags: { add: number[]; remove: number[] } }
  | { properties: PropertyValuesSetRequest };

/** One way to split a project's tasks. */
export type TaskGrouping = {
  /** The table's hidden column for it, which is what a person's view keeps. */
  column: string;
  label: string;
  /** The groups a task is in: none puts it in {@link NO_GROUP}, several in each. */
  keys: (task: TaskListRead) => string[];
  /** The order of two groups. */
  compare: (a: string, b: string) => number;
  header: (key: string) => ReactNode;
  /** The write a drop from `from` into `to` makes; left out where a drop
   *  can't change anything (a date window isn't a date). */
  move?: (from: string, to: string) => GroupMove;
};

const text = collator(undefined, { numeric: true, sensitivity: "base" });

// The empty group goes last, whatever the order of the rest.
const emptyLast = (a: string, b: string) => Number(a === NO_GROUP) - Number(b === NO_GROUP);
const ranked = (rank: (key: string) => number) => (a: string, b: string) =>
  emptyLast(a, b) || rank(a) - rank(b);
const named = (name: (key: string) => string) => (a: string, b: string) =>
  emptyLast(a, b) || text.compare(name(a), name(b));

const label = (content: ReactNode) => <span className="font-medium text-base">{content}</span>;

const byId = <T extends { id: number }>(items: T[]) =>
  new Map(items.map((item) => [String(item.id), item]));

/** How a person, a tag or an option moves between groups: off the one it came
 *  from and onto the other, where the empty group has none to take or give. */
const swap = (from: string, to: string) => ({
  add: to === NO_GROUP ? [] : [to],
  remove: from === NO_GROUP ? [] : [from],
});

const propertyGrouping = (
  field: FieldDef,
  definition: PropertyDefinitionRead,
  tasks: TaskListRead[],
  t: TranslateFn
): TaskGrouping | null => {
  const id = definition.id;
  const heldBy = (task: TaskListRead) =>
    task.properties?.find((summary) => summary.property_id === id)?.value;
  const summary = (value: unknown): PropertySummary => ({
    property_id: id,
    name: definition.name,
    type: definition.type,
    options: definition.options,
    value,
  });
  const empty = label(t("table.noValue", { name: field.label }));
  const optionRank = new Map((definition.options ?? []).map((option, i) => [option.value, i]));
  const byOption = ranked((key) => optionRank.get(key) ?? optionRank.size);
  const write = (to: string, value: unknown): GroupMove => ({
    properties:
      to === NO_GROUP
        ? { merge: true, removed: [id] }
        : { merge: true, values: [{ property_id: id, value }] },
  });
  const base = { column: `${field.id} group`, label: field.label };
  switch (definition.type) {
    case PropertyType.select:
      return {
        ...base,
        keys: (task) => {
          const value = heldBy(task);
          return typeof value === "string" && value ? [value] : [];
        },
        compare: byOption,
        header: (key) => (key === NO_GROUP ? empty : <PropertyValueCell summary={summary(key)} />),
        move: (_from, to) => write(to, to),
      };
    case PropertyType.multi_select:
      return {
        ...base,
        keys: (task) => {
          const value = heldBy(task);
          return Array.isArray(value)
            ? value.filter((v): v is string => typeof v === "string")
            : [];
        },
        compare: byOption,
        header: (key) =>
          key === NO_GROUP ? empty : <PropertyValueCell summary={summary([key])} />,
        move: (from, to) => ({
          properties: { merge: true, options: [{ property_id: id, ...swap(from, to) }] },
        }),
      };
    case PropertyType.user_reference: {
      const people = byId(tasks.flatMap((task) => extractUser(heldBy(task)) ?? []));
      return {
        ...base,
        keys: (task) => {
          const person = extractUser(heldBy(task));
          return person ? [String(person.id)] : [];
        },
        compare: named((key) => getUserDisplayName(people.get(key))),
        header: (key) =>
          key === NO_GROUP ? empty : <PropertyValueCell summary={summary(people.get(key))} />,
        move: (_from, to) => write(to, Number(to)),
      };
    }
    case PropertyType.checkbox:
      // Unchecked is a value of its own, so nothing falls in the empty group.
      return {
        ...base,
        keys: (task) => [String(heldBy(task) === true)],
        compare: (a, b) => Number(b === "true") - Number(a === "true"),
        header: (key) =>
          label(t(key === "true" ? "table.checked" : "table.unchecked", { name: field.label })),
        move: (_from, to) => write(to, to === "true"),
      };
    default:
      return null;
  }
};

/**
 * The ways a project's tasks can be grouped: their date window and status,
 * then every field of the project's that groups cleanly, in the fields' order.
 * A text, number, URL or date field doesn't, nor does a plug-in's.
 */
export const taskGroupings = ({
  fields,
  definitions,
  statuses,
  tasks,
  t,
}: {
  fields: ReadonlyMap<string, FieldDef>;
  definitions: PropertyDefinitionRead[];
  statuses: TaskStatusRead[];
  tasks: TaskListRead[];
  t: TranslateFn;
}): TaskGrouping[] => {
  // The project's own statuses over the copies its tasks carry.
  const statusesById = byId<TaskStatusRead>([
    ...tasks.map((task) => task.task_status),
    ...statuses,
  ]);
  const people = byId(tasks.flatMap((task) => task.assignees));
  const tags = byId(tasks.flatMap((task) => task.tags ?? []));
  const definitionsByField = new Map(definitions.map((each) => [propertyFieldId(each.id), each]));

  const ofField = (field: FieldDef): TaskGrouping | null => {
    const base = { column: `${field.id} group`, label: t(field.label) };
    switch (field.kind) {
      case "priority":
        return {
          ...base,
          keys: (task) => [task.priority],
          // Most urgent first.
          compare: ranked((key) => -priorityRank[key as TaskPriority]),
          header: (key) => (
            <Badge variant={priorityVariant[key as TaskPriority]}>
              {t(`tasks:priority.${key}`)}
            </Badge>
          ),
          move: (_from, to) => ({ patch: { priority: to as TaskPriority } }),
        };
      case "people":
        return {
          ...base,
          keys: (task) => task.assignees.map((assignee) => String(assignee.id)),
          compare: named((key) => getUserDisplayName(people.get(key))),
          header: (key) => {
            const person = people.get(key);
            return person ? (
              <TaskAssigneeList assignees={[person]} size="md" className="text-foreground" />
            ) : (
              label(t("filters.unassigned"))
            );
          },
          move: (from, to) => {
            const { add, remove } = swap(from, to);
            return {
              patch: { add_assignee_ids: add.map(Number), remove_assignee_ids: remove.map(Number) },
            };
          },
        };
      case "tags":
        return {
          ...base,
          keys: (task) => (task.tags ?? []).map((tag) => String(tag.id)),
          compare: named((key) => tags.get(key)?.name ?? ""),
          header: (key) => {
            const tag = tags.get(key);
            return tag ? <TagBadge tag={tag} size="md" /> : label(t("table.untagged"));
          },
          move: (from, to) => {
            const { add, remove } = swap(from, to);
            return { tags: { add: add.map(Number), remove: remove.map(Number) } };
          },
        };
      case "property": {
        const definition = definitionsByField.get(field.id);
        return definition ? propertyGrouping(field, definition, tasks, t) : null;
      }
      default:
        return null;
    }
  };

  return [
    {
      column: "date group",
      label: t("tasks:columns.dateWindow"),
      keys: (task) => [getTaskDateStatus(task.start_date, task.due_date)],
      // The windows' keys are numbered in their order.
      compare: (a, b) => text.compare(a, b),
      header: (key) => label(getTaskDateStatusLabel(key, t)),
    },
    {
      column: "status group",
      label: t("table.statusColumn"),
      keys: (task) => [String(task.task_status_id)],
      // Board order, as the columns stand.
      compare: ranked((key) => statusesById.get(key)?.position ?? Number.MAX_SAFE_INTEGER),
      header: (key) => {
        const status = statusesById.get(key);
        return status ? (
          <TaskStatusOption status={status} className="font-medium text-base" />
        ) : null;
      },
      move: (_from, to) => ({ status: Number(to) }),
    },
    ...[...fields.values()].flatMap((field) => ofField(field) ?? []),
  ];
};

/** A task as a row of a grouped table: the one group it is listed under, when
 *  the table is grouped, so a plain task list is a valid row list. */
export type TaskGroupRow = TaskListRead & { group?: string };

/** One row per group a task is in, so a task with two tags is listed under
 *  both rather than under whichever came first. */
export const groupRows = (tasks: TaskListRead[], grouping: TaskGrouping): TaskGroupRow[] =>
  tasks.flatMap((task) => {
    const keys = grouping.keys(task);
    return (keys.length > 0 ? keys : [NO_GROUP]).map((group) => ({ ...task, group }));
  });

/** A row's id: a task listed under several groups has a row in each. */
export const groupRowId = (row: TaskGroupRow): string =>
  row.group === undefined ? String(row.id) : `${row.id}::${row.group}`;

/** The tasks rows came from, each once, as the list holds them. */
export const uniqueTasksFromRows = (
  rows: TaskGroupRow[],
  tasksById: Map<number, TaskListRead>
): TaskListRead[] => {
  const seen = new Set<number>();
  const tasks: TaskListRead[] = [];
  for (const row of rows) {
    if (seen.has(row.id)) {
      continue;
    }
    seen.add(row.id);
    tasks.push(tasksById.get(row.id) ?? row);
  }
  return tasks;
};
