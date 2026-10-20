/**
 * What an embed shows, and where its items come from.
 *
 * An embed is a block in a page: one thing — its card, or the facts about it
 * that matter here — or the tasks matching a filter, as a list, a table or a
 * count. The filter is the shape a layout preset keeps (`TaskFilterSpec`), so
 * it reads back as the same controls, and it is compiled each time the page
 * is read: `me` is whoever is reading, and "due this week" is this week.
 */

import type {
  ListTasksParams,
  SmartChipKind,
  SortField,
} from "@/api/generated/initiativeAPI.schemas";
import {
  buildTaskListParams,
  EMPTY_TASK_FILTERS,
  type StoredTaskFilters,
  specFromStored,
  type TaskFilterSpec,
  tableSortFields,
  taskTableSorting,
} from "@/lib/filters/taskFilters";
import { isSmartChipKind } from "@/lib/smartChips";

/** How an embed draws: one thing as a card or as chosen facts; a set of tasks
 *  as a list, a table or a count. */
export type EmbedMode = "card" | "fields" | "list" | "table" | "count";

export const ITEM_MODES: EmbedMode[] = ["card", "fields"];
export const TASK_MODES: EmbedMode[] = ["list", "table", "count"];

export interface EmbedDisplay {
  mode: EmbedMode;
  /** The facts a `fields` embed shows, as chip kinds (`task:status`). */
  fields?: SmartChipKind[];
  /** The columns a `table` shows, as a layout names them (`dueDate`,
   *  `property:7`). Absent, the project table's shipped columns. */
  columns?: string[];
}

export const CARD: EmbedDisplay = { mode: "card" };

/** Where a task embed's tasks come from: the page's initiative, or one project
 *  in it, narrowed by a filter and ordered by a sort. */
export interface TaskQuery {
  initiative_id: number;
  project_id: number | null;
  filters: TaskFilterSpec;
  sort: SortField[];
}

export const emptyTaskQuery = (initiativeId: number): TaskQuery => ({
  initiative_id: initiativeId,
  project_id: null,
  filters: EMPTY_TASK_FILTERS,
  sort: [],
});

/** How many rows a list or table shows before it pages on. */
export const EMBED_PAGE_SIZE = 20;

/** The task list request for one page of an embed: the same request a
 *  project's list makes, scoped to the embed's project or initiative. A count
 *  asks for one row and reads the total. */
export const taskQueryParams = (
  query: TaskQuery,
  page: number,
  count = false
): ListTasksParams => ({
  ...buildTaskListParams(
    query.filters,
    query.project_id !== null
      ? { projectId: query.project_id }
      : { initiativeId: query.initiative_id },
    { page: count ? 1 : page, page_size: count ? 1 : EMBED_PAGE_SIZE }
  ),
  ...(query.sort.length > 0 && { sorting: query.sort }),
});

const MODES = new Set<EmbedMode>([...ITEM_MODES, ...TASK_MODES]);

/** A stored display read back, keeping only what this build understands. */
export const readDisplay = (value: unknown): EmbedDisplay => {
  const stored = (value ?? {}) as Partial<EmbedDisplay>;
  if (!stored.mode || !MODES.has(stored.mode)) return CARD;
  return {
    mode: stored.mode,
    ...(Array.isArray(stored.fields) && { fields: stored.fields.filter(isSmartChipKind) }),
    ...(Array.isArray(stored.columns) && {
      columns: stored.columns.filter((id) => typeof id === "string"),
    }),
  };
};

/** A stored query read back, or `null` where it is not one. */
export const readQuery = (value: unknown): TaskQuery | null => {
  const stored = value as Partial<TaskQuery> | null | undefined;
  if (!stored || typeof stored.initiative_id !== "number") return null;
  return {
    initiative_id: stored.initiative_id,
    project_id: typeof stored.project_id === "number" ? stored.project_id : null,
    filters: specFromStored(stored.filters as StoredTaskFilters | undefined),
    // Read the way a preset's sort is: only what the list can order by.
    sort: Array.isArray(stored.sort)
      ? tableSortFields(
          taskTableSorting(stored.sort.filter((entry) => typeof entry?.field === "string"))
        )
      : [],
  };
};
