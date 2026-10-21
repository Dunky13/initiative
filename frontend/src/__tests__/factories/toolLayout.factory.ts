import type {
  DetailLayoutRead,
  DetailLayoutWrite,
  ListLayoutRead,
  ListLayoutReadKind,
  ListLayoutWrite,
  ToolLayoutSetRead,
} from "@/api/generated/initiativeAPI.schemas";

/** When a layout built here was last changed. */
const CHANGED = "2026-10-01T12:00:00.000Z";

/** Which layout a layout is: its kind, and a task page's type. */
const sameLayout = (
  a: ListLayoutRead | DetailLayoutRead,
  b: { kind: string; task_type_id?: number | null }
) =>
  a.kind === b.kind &&
  (("task_type_id" in a ? a.task_type_id : null) ?? null) === (b.task_type_id ?? null);

/** A target's layouts as the server reads them until it changes any, each as
 *  shipped: a project's table (which it opens on), board and calendar, then
 *  the page of its task type 1, "Task"; or, with `tool: "calendar"`, the
 *  initiative calendar's calendar and its event's detail. `layouts` replaces
 *  those of the same kind (and type), and another type's page is added. */
export function buildToolLayoutSet(
  overrides: Partial<Omit<ToolLayoutSetRead, "layouts">> & {
    layouts?: (ListLayoutRead | DetailLayoutRead)[];
    tool?: "project" | "calendar";
  } = {}
): ToolLayoutSetRead {
  const { layouts = [], tool = "project", ...rest } = overrides;
  const lists: ListLayoutReadKind[] =
    tool === "project" ? ["table", "board", "calendar"] : ["calendar"];
  const shipped: (ListLayoutRead | DetailLayoutRead)[] = [
    ...lists.map((kind, index) => ({
      kind,
      is_default: index === 0,
      definition: {},
      updated_at: null,
    })),
    tool === "project"
      ? {
          kind: "task",
          task_type_id: 1,
          task_type_name: "Task",
          definition: {},
          updated_at: null,
        }
      : {
          kind: "calendar_event",
          task_type_id: null,
          task_type_name: null,
          definition: {},
          updated_at: null,
        },
  ];
  const key = (each: ListLayoutRead | DetailLayoutRead) => ({
    kind: each.kind,
    task_type_id: "task_type_id" in each ? each.task_type_id : null,
  });
  return {
    layouts: [
      ...shipped.map((each) => layouts.find((layout) => sameLayout(layout, key(each))) ?? each),
      // Another task type's page follows the shipped ones.
      ...layouts.filter((layout) => !shipped.some((each) => sameLayout(each, key(layout)))),
    ],
    can_configure: true,
    ...rest,
  };
}

/** `set` as the server answers a change: `write` saved, and dated. */
export function buildSavedLayoutSet(
  set: ToolLayoutSetRead,
  write: ListLayoutWrite | DetailLayoutWrite
): ToolLayoutSetRead {
  return {
    ...set,
    layouts: set.layouts.map((layout) =>
      sameLayout(layout, write)
        ? ({ ...layout, definition: write.definition, updated_at: CHANGED } as typeof layout)
        : layout
    ),
  };
}
