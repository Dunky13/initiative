/**
 * How a project's tasks are grouped: by their date window or status, and by
 * any field whose values group cleanly. A grouping says which groups a task is
 * in, the order its groups go in, what each group's header shows, and what a
 * drop from one group into another changes. The table draws it as header rows,
 * the board as bands across its status columns.
 */

import type { GroupingState } from "@tanstack/react-table";
import type { ReactNode } from "react";

import {
  type LayoutGrouping,
  type ListLayoutDefinitionOutput,
  type ListLayoutReadKind,
  type PropertyDefinitionRead,
  type PropertySummary,
  PropertyType,
  type PropertyValuesSetRequest,
  TaskGroupingId,
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
import type { FieldDef } from "@/lib/layouts/fields";
import { PRIORITY_ORDER, priorityRank } from "@/lib/sorting";
import {
  getTaskDateStatus,
  getTaskDateStatusLabel,
  TASK_DATE_STATUSES,
} from "@/lib/taskDateStatus";
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
  /** What a layout names it by: the field's id, or the date window's or
   *  status's. */
  id: string;
  /** The table's hidden column for it, which is what a person's view keeps. */
  column: string;
  label: string;
  /** The groups a task is in: none puts it in {@link NO_GROUP}, several in each. */
  keys: (task: TaskListRead) => string[];
  /** The groups there are whether or not a task is in them: the field's
   *  statuses, priorities or options, and the group for tasks with none.
   *  People and tags have only that one; the rest are those their tasks hold. */
  values?: string[];
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

/** A grouping's table column, as a person's view keeps it. */
export const groupColumn = (id: string) => `${id} group`;

/** The most groupings a layout offers, and groups one leaves out, as the
 *  server holds a layout to. */
export const MAX_GROUPINGS = 50;
export const MAX_HIDDEN_GROUPS = 200;

/** What a list offers where its layout names no groupings of its own. */
export const SHIPPED_GROUPINGS: string[] = Object.values(TaskGroupingId);

/** Whether `kind` can be grouped by `id`: a board's columns are its statuses
 *  already, so its bands never are. */
const groupsBy = (kind: ListLayoutReadKind, id: string) =>
  kind !== "board" || id !== TaskGroupingId.status;

/** A layout's groupings, or the shipped ones where it names none. */
export const groupingsOf = (
  groupings: LayoutGrouping[] | null | undefined,
  kind: ListLayoutReadKind
): LayoutGrouping[] =>
  groupings ?? SHIPPED_GROUPINGS.filter((id) => groupsBy(kind, id)).map((field) => ({ field }));

/** The groupings `kind` can offer, of `all`. */
export const groupingsFor = (all: TaskGrouping[], kind: ListLayoutReadKind): TaskGrouping[] =>
  all.filter((each) => groupsBy(kind, each.id));

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
  const base = { id: field.id, column: groupColumn(field.id), label: field.label };
  const options = (definition.options ?? []).map((option) => option.value);
  switch (definition.type) {
    case PropertyType.select:
      return {
        ...base,
        keys: (task) => {
          const value = heldBy(task);
          return typeof value === "string" && value ? [value] : [];
        },
        values: [...options, NO_GROUP],
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
        values: [...options, NO_GROUP],
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
        values: [NO_GROUP],
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
        values: ["true", "false"],
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
  statuses,
  tasks,
  t,
}: {
  fields: ReadonlyMap<string, FieldDef>;
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

  const ofField = (field: FieldDef): TaskGrouping | null => {
    const base = { id: field.id, column: groupColumn(field.id), label: t(field.label) };
    switch (field.kind) {
      case "priority":
        return {
          ...base,
          keys: (task) => [task.priority],
          values: PRIORITY_ORDER,
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
          values: [NO_GROUP],
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
          values: [NO_GROUP],
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
      case "property":
        return field.property ? propertyGrouping(field, field.property, tasks, t) : null;
      default:
        return null;
    }
  };

  return [
    {
      id: TaskGroupingId.date,
      column: groupColumn(TaskGroupingId.date),
      label: t("tasks:columns.dateWindow"),
      keys: (task) => [getTaskDateStatus(task.start_date, task.due_date)],
      values: TASK_DATE_STATUSES,
      // The windows' keys are numbered in their order.
      compare: (a, b) => text.compare(a, b),
      header: (key) => label(getTaskDateStatusLabel(key, t)),
    },
    {
      id: TaskGroupingId.status,
      column: groupColumn(TaskGroupingId.status),
      label: t("table.statusColumn"),
      keys: (task) => [String(task.task_status_id)],
      values: statuses.map((status) => String(status.id)),
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

/** A grouping a list offers, and the groups it leaves out while grouped by it. */
export type OfferedGrouping = { grouping: TaskGrouping; hidden: ReadonlySet<string> };

/** What a list offers, in its order: the layout's own groupings, or the
 *  shipped ones where it names none. One whose field the project no longer
 *  has, or whose values no longer group, is passed over. */
export const offeredGroupings = (
  all: TaskGrouping[],
  groupings: LayoutGrouping[] | null | undefined,
  kind: ListLayoutReadKind
): OfferedGrouping[] => {
  const byGrouping = new Map(groupingsFor(all, kind).map((each) => [each.id, each]));
  return groupingsOf(groupings, kind).flatMap((entry) => {
    const grouping = byGrouping.get(entry.field);
    return grouping ? [{ grouping, hidden: new Set(entry.hidden ?? []) }] : [];
  });
};

/**
 * What a person's list is grouped by: the pick they kept, None included,
 * while the list still offers it, and otherwise the grouping the list starts
 * on. `kept` is null where they never picked. Grouping by tag kept
 * "tag group" before every field could group.
 */
export const viewGrouping = (
  definition: Pick<ListLayoutDefinitionOutput, "groupings" | "group_by"> | undefined,
  kind: ListLayoutReadKind,
  kept: GroupingState | null
): GroupingState => {
  const start = definition?.group_by ? [groupColumn(definition.group_by)] : [];
  if (kept === null) return start;
  const offered = groupingsOf(definition?.groupings, kind)
    .filter((entry) => groupsBy(kind, entry.field))
    .map((entry) => groupColumn(entry.field));
  const picked = kept.map((column) => (column === "tag group" ? "tags group" : column));
  return picked.every((column) => offered.includes(column)) ? picked : start;
};

/** `groupings` (the shipped ones where null) with the group `key` of the one
 *  `id` names shown or left out. */
export const withGroupShown = (
  groupings: LayoutGrouping[] | null | undefined,
  kind: ListLayoutReadKind,
  id: string,
  key: string,
  shown: boolean
): LayoutGrouping[] =>
  groupingsOf(groupings, kind).map((entry) => {
    if (entry.field !== id) return entry;
    const others = (entry.hidden ?? []).filter((each) => each !== key);
    return { ...entry, hidden: shown ? others : [...others, key] };
  });

/** A band of a grouped board: one group, and its tasks in the board's order. */
export type Band = { key: string; tasks: TaskListRead[] };

/** A board's bands: one for each group there is (the ones `values` names,
 *  holding a task or not) and each its tasks are in, a task in several in
 *  each, less those `hidden` leaves out, in the grouping's order. */
export const boardBands = (
  { grouping, hidden }: OfferedGrouping,
  tasks: TaskListRead[]
): Band[] => {
  const bands = new Map<string, TaskListRead[]>((grouping.values ?? []).map((key) => [key, []]));
  for (const task of tasks) {
    const keys = grouping.keys(task);
    for (const key of keys.length > 0 ? keys : [NO_GROUP]) {
      const band = bands.get(key);
      if (band) band.push(task);
      else bands.set(key, [task]);
    }
  }
  return [...bands]
    .filter(([key]) => !hidden.has(key))
    .sort(([a], [b]) => grouping.compare(a, b))
    .map(([key, held]) => ({ key, tasks: held }));
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
