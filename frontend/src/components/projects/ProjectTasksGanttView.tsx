import { Link, useNavigate } from "@tanstack/react-router";
import type { GroupingState } from "@tanstack/react-table";
import { ChevronRight } from "lucide-react";
import {
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  LayoutGrouping,
  ListTasksParams,
  TaskListRead,
  TaskStatusRead,
  TaskUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { useListTaskEdges } from "@/api/generated/relationships/relationships";
import { TaskTypeMark } from "@/components/tasks/TaskTypeOption";
import { Button } from "@/components/ui/button";
import { GroupBySelect } from "@/components/ui/data-table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useProjectTaskTypes } from "@/hooks/useProjects";
import { useProperties } from "@/hooks/useProperties";
import { useTaskGroupings } from "@/hooks/useTaskGroupings";
import {
  DAY,
  type DragHold,
  draggedAcross,
  draggedDates,
  GANTT_SCALES,
  type GanttRow,
  type GanttScale,
  type GanttSpan,
  ganttWindow,
  heldDays,
  PX_PER_DAY,
  scheduledDates,
  spanOf,
  taskRows,
  wholesOf,
} from "@/lib/gantt";
import { dateTimeFormat } from "@/lib/intl";
import { LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import { boardBands } from "@/lib/layouts/grouping";
import { taskFields } from "@/lib/layouts/tasks";
import { cn } from "@/lib/utils";
import {
  type AxisTick,
  addUnits,
  axisTicks,
  floorToUnit,
  majorSegments,
  weekendBands,
} from "@/lib/widgets/timelineAxis";
import type { TranslateFn } from "@/types/i18n";

const LABEL_WIDTH = 260;
const ROW_HEIGHT = 32;
const HEADER_HEIGHT = 40;
const INDENT = 14;
/** How far a pointer moves before a press on a bar is a drag, not a click. */
const DRAG_SLOP = 4;
/** Where the arrow from a blocker turns before it reaches what waits on it. */
const ELBOW = 8;

type Dates = Pick<TaskUpdate, "start_date" | "due_date">;

/** A drag in progress: what it holds, where it began, and how many days it
 *  has gone. A task with no dates is being given some from `from`. */
type Drag = {
  key: string;
  task: TaskListRead;
  hold: DragHold;
  originX: number;
  days: number;
  moved: boolean;
  from?: number;
};

type ProjectTasksGanttViewProps = {
  initiativeId: number;
  projectId: number;
  tasks: TaskListRead[];
  taskStatuses: TaskStatusRead[];
  /** The list the tasks are, which their groups are worked out for. */
  listParams?: ListTasksParams;
  scale: GanttScale;
  onScaleChange?: (scale: GanttScale) => void;
  grouping: GroupingState;
  onGroupingChange?: (grouping: GroupingState) => void;
  viewGroupings?: LayoutGrouping[] | null;
  taskHref: (taskId: number) => string;
  /** Writes a task's new dates; left out, the bars stay where they are. */
  onReschedule?: (task: TaskListRead, dates: Dates) => Promise<unknown>;
  /** Drawn in the layout editor: nothing opens or moves. */
  editing?: boolean;
};

/**
 * A project's tasks on a time axis, each a bar from its start to its due date.
 * A task with one date is a marker on that day, and a task with none has an
 * empty track, which a drag across gives dates. A bar is dragged to move it
 * and by an end to change that date; a task depending on another is joined to
 * it by an arrow, red where it starts before the other ends; and a task's
 * parts are listed under it, folded with it, the span they cover drawn over
 * its row. Grouped, each group is a band with its heading.
 */
export const ProjectTasksGanttView = ({
  initiativeId,
  projectId,
  tasks,
  taskStatuses,
  listParams,
  scale,
  onScaleChange,
  grouping,
  onGroupingChange,
  viewGroupings,
  taskHref,
  onReschedule,
  editing = false,
}: ProjectTasksGanttViewProps) => {
  const { t, i18n } = useTranslation(["projects", "common"]);
  const { t: layoutT } = useTranslation(LAYOUT_NAMESPACES);
  const locale = i18n.language;
  const navigate = useNavigate();
  const communityId = useActiveCommunityId();

  const { data: definitions } = useProperties({ initiativeId });
  const fields = useMemo(() => taskFields(definitions ?? []), [definitions]);
  const { offered, active } = useTaskGroupings({
    fields,
    statuses: taskStatuses,
    tasks,
    groupings: viewGroupings,
    kind: "gantt",
    grouping,
    params: listParams,
    t: layoutT as TranslateFn,
  });
  // A project with one type shows none: it tells no task apart.
  const typed = (useProjectTaskTypes(projectId).data?.length ?? 0) > 1;
  const edges = useListTaskEdges(communityId, { project_id: projectId }).data;

  // Dates written but not yet answered for, drawn where they were dropped.
  const [pending, setPending] = useState<ReadonlyMap<number, Dates>>(new Map());
  const shown = useMemo(
    () =>
      pending.size === 0
        ? tasks
        : tasks.map((task) => {
            const dates = pending.get(task.id);
            return dates ? { ...task, ...dates } : task;
          }),
    [tasks, pending]
  );

  const [folded, setFolded] = useState<ReadonlySet<string>>(new Set());
  const rows = useMemo<GanttRow[]>(() => {
    const wholes = wholesOf(shown, edges ?? []);
    if (!active) return taskRows(shown, wholes, folded);
    const byId = new Map(shown.map((task) => [task.id, task]));
    return boardBands(active, tasks).flatMap((band): GanttRow[] => {
      const held = band.tasks.map((task) => byId.get(task.id) ?? task);
      return [
        { type: "group", key: band.key, count: held.length },
        ...taskRows(held, wholes, folded, `${band.key}:`),
      ];
    });
  }, [shown, tasks, edges, folded, active]);

  const now = useMemo(() => Date.now(), []);
  const pxPerDay = PX_PER_DAY[scale];
  const range = useMemo(
    () =>
      ganttWindow(
        shown.flatMap((task) => spanOf(task) ?? []),
        scale,
        now
      ),
    [shown, scale, now]
  );
  const width = Math.round(((range.end - range.start) / DAY) * pxPerDay);
  const x = useCallback(
    (at: number) => ((at - range.start) / DAY) * pxPerDay,
    [range.start, pxPerDay]
  );
  const ticks = useMemo(() => axisTicks(range, scale, 0, Number.POSITIVE_INFINITY), [range, scale]);
  const major = useMemo(() => majorSegments(range, scale), [range, scale]);
  const weekends = useMemo(() => (scale === "month" ? [] : weekendBands(range)), [range, scale]);

  // Opens on today, a third of the way in, and again on another scale. When
  // the window widens (tasks load, a filter changes) the dates in view stay.
  const scroller = useRef<HTMLDivElement>(null);
  const scrollToToday = useCallback(() => {
    const element = scroller.current;
    if (element) element.scrollLeft = Math.max(0, x(now) - (element.clientWidth - LABEL_WIDTH) / 3);
  }, [x, now]);
  const drawn = useRef<{ scale: GanttScale; start: number } | null>(null);
  useLayoutEffect(() => {
    const before = drawn.current;
    drawn.current = { scale, start: range.start };
    const element = scroller.current;
    if (!before || before.scale !== scale) scrollToToday();
    else if (element && before.start !== range.start) {
      element.scrollLeft += x(before.start);
    }
  }, [scale, range.start, x, scrollToToday]);

  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const moveDrag = (next: Drag | null) => {
    dragRef.current = next;
    setDrag(next);
  };
  const canMove = Boolean(onReschedule) && !editing;

  const write = async (task: TaskListRead, dates: Dates) => {
    if (!onReschedule) return;
    setPending((all) => new Map(all).set(task.id, dates));
    try {
      await onReschedule(task, dates);
    } finally {
      setPending((all) => {
        const next = new Map(all);
        next.delete(task.id);
        return next;
      });
    }
  };

  const dayAt = (event: ReactPointerEvent<HTMLElement>) => {
    const track = event.currentTarget.getBoundingClientRect();
    return floorToUnit(range.start + ((event.clientX - track.left) / pxPerDay) * DAY, "day");
  };

  const press = (
    event: ReactPointerEvent<HTMLElement>,
    key: string,
    task: TaskListRead,
    hold: DragHold,
    from?: number
  ) => {
    if (event.button !== 0 || (!canMove && from !== undefined)) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    moveDrag({ key, task, hold, originX: event.clientX, days: 0, moved: false, from });
  };

  const follow = (event: ReactPointerEvent<HTMLElement>) => {
    const current = dragRef.current;
    if (!current) return;
    const dx = event.clientX - current.originX;
    const moved = current.moved || Math.abs(dx) > DRAG_SLOP;
    const days = canMove ? Math.round(dx / pxPerDay) : 0;
    if (moved !== current.moved || days !== current.days) moveDrag({ ...current, moved, days });
  };

  const release = () => {
    const current = dragRef.current;
    moveDrag(null);
    if (!current) return;
    if (current.from !== undefined) {
      // A click on an empty track is not a choice of dates; a drag across it is.
      if (current.moved) {
        void write(current.task, scheduledDates(current.from, current.days));
      }
      return;
    }
    if (!current.moved) {
      if (!editing) void navigate({ to: taskHref(current.task.id) });
      return;
    }
    const span = spanOf(current.task);
    const days = span ? heldDays(span, current.hold, current.days) : 0;
    if (days !== 0) void write(current.task, draggedDates(current.task, current.hold, days));
  };

  /** Where a row's bar is drawn, the drag on it included. */
  const spanIn = (key: string, task: TaskListRead): GanttSpan | null => {
    const span = spanOf(task);
    if (!drag || drag.key !== key) return span;
    if (drag.from !== undefined) return { ...draggedAcross(drag.from, drag.days), kind: "bar" };
    if (!span) return null;
    const days = heldDays(span, drag.hold, drag.days);
    return {
      ...span,
      start: drag.hold === "end" ? span.start : addUnits(span.start, "day", days),
      end: drag.hold === "start" ? span.end : addUnits(span.end, "day", days),
    };
  };

  // A dependency's arrow runs from the end of what blocks to the start of
  // what waits, between the first rows each is drawn in.
  const arrows = useMemo(() => {
    const at = new Map<number, { index: number; span: GanttSpan }>();
    rows.forEach((row, index) => {
      if (row.type !== "task" || at.has(row.task.id)) return;
      const span = spanOf(row.task);
      if (span) at.set(row.task.id, { index, span });
    });
    return (edges ?? []).flatMap((edge) => {
      if (edge.relationship_type !== "depends_on") return [];
      const waits = at.get(edge.source_id);
      const blocks = at.get(edge.target_id);
      if (!waits || !blocks) return [];
      const x1 = x(blocks.span.end);
      const y1 = blocks.index * ROW_HEIGHT + ROW_HEIGHT / 2;
      const x2 = x(waits.span.start);
      const y2 = waits.index * ROW_HEIGHT + ROW_HEIGHT / 2;
      const path =
        x2 - x1 >= ELBOW * 2
          ? `M${x1},${y1} H${x1 + ELBOW} V${y2} H${x2}`
          : `M${x1},${y1} H${x1 + ELBOW} V${(y1 + y2) / 2} H${x2 - ELBOW} V${y2} H${x2}`;
      return [
        {
          key: `${edge.source_id}:${edge.target_id}`,
          path,
          late: waits.span.start < blocks.span.end,
        },
      ];
    });
  }, [rows, edges, x]);

  const tickLabel = (tick: AxisTick) =>
    dateTimeFormat(locale, scale === "month" ? { month: "short" } : { day: "numeric" }).format(
      new Date(tick.at)
    );
  const segmentLabel = (at: number) =>
    dateTimeFormat(
      locale,
      major.unit === "year" ? { year: "numeric" } : { month: "long", year: "numeric" }
    ).format(new Date(at));
  const dayLabel = (at: number) =>
    dateTimeFormat(locale, { month: "short", day: "numeric" }).format(new Date(at));

  const toggleFold = (key: string) =>
    setFolded((all) => {
      const next = new Set(all);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const todayX = x(floorToUnit(now, "day"));
  const markerId = useId();

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-end gap-3">
        {onGroupingChange && offered.length > 0 && !editing ? (
          <GroupBySelect
            options={offered.map(({ grouping: each }) => ({ id: each.column, label: each.label }))}
            value={active?.grouping.column ?? null}
            onChange={(id) => onGroupingChange(id === null ? [] : [id])}
          />
        ) : null}
        <Button type="button" variant="outline" size="sm" onClick={scrollToToday}>
          {t("common:calendar.today")}
        </Button>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={scale}
          onValueChange={(next) => {
            if (next) onScaleChange?.(next as GanttScale);
          }}
          aria-label={t("common:calendar.viewMode")}
        >
          {GANTT_SCALES.map((each) => (
            <ToggleGroupItem key={each} value={each}>
              {t(`common:calendar.${each}` as never)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <div
        ref={scroller}
        className="scrollbar-thin max-h-[75vh] overflow-auto rounded-md border text-sm"
        data-testid="gantt"
      >
        <div className="relative" style={{ width: LABEL_WIDTH + width }}>
          {/* The axis: the coarser unit over its days, weeks or months. */}
          <div
            className="sticky top-0 z-20 flex border-b bg-background"
            style={{ height: HEADER_HEIGHT }}
          >
            <div
              className="sticky left-0 z-10 shrink-0 border-r bg-background"
              style={{ width: LABEL_WIDTH }}
            />
            <div className="relative" style={{ width }}>
              {major.segments.map((segment) => (
                <div
                  key={segment.at}
                  className="absolute top-0 h-5 truncate border-l px-1.5 font-medium text-muted-foreground text-xs leading-5"
                  style={{ left: x(segment.start), width: x(segment.end) - x(segment.start) }}
                >
                  {segmentLabel(segment.at)}
                </div>
              ))}
              {ticks.map((tick) => (
                <div
                  key={tick.at}
                  className="absolute bottom-0 h-5 truncate border-l px-1 text-2xs text-muted-foreground leading-5"
                  style={{ left: x(tick.at) }}
                >
                  {tickLabel(tick)}
                </div>
              ))}
            </div>
          </div>

          <div className="relative">
            {/* Behind the bars: weekends, gridlines, today and the arrows. */}
            <div
              className="pointer-events-none absolute inset-y-0"
              style={{ left: LABEL_WIDTH, width }}
              aria-hidden
            >
              {weekends.map((band) => (
                <div
                  key={band.start}
                  className="absolute inset-y-0 bg-muted/40"
                  style={{ left: x(band.start), width: x(band.end) - x(band.start) }}
                />
              ))}
              {ticks.map((tick) => (
                <div
                  key={tick.at}
                  className="absolute inset-y-0 w-px bg-border/50"
                  style={{ left: x(tick.at) }}
                />
              ))}
              <div className="absolute inset-y-0 w-px bg-primary" style={{ left: todayX }} />
              <svg
                className="absolute inset-0 overflow-visible"
                width={width}
                height={rows.length * ROW_HEIGHT}
              >
                <defs>
                  {[false, true].map((late) => (
                    <marker
                      key={String(late)}
                      id={`${markerId}-${late}`}
                      viewBox="0 0 6 6"
                      refX="6"
                      refY="3"
                      markerWidth="6"
                      markerHeight="6"
                      orient="auto"
                    >
                      <path
                        d="M0,0 L6,3 L0,6 z"
                        className={late ? "fill-destructive" : "fill-muted-foreground"}
                      />
                    </marker>
                  ))}
                </defs>
                {arrows.map((arrow) => (
                  <path
                    key={arrow.key}
                    d={arrow.path}
                    fill="none"
                    strokeWidth={1.5}
                    markerEnd={`url(#${markerId}-${arrow.late})`}
                    className={arrow.late ? "stroke-destructive" : "stroke-muted-foreground"}
                  />
                ))}
              </svg>
            </div>

            {rows.length === 0 ? (
              <p
                className="sticky left-0 p-6 text-muted-foreground"
                style={{ width: LABEL_WIDTH + 320 }}
              >
                {t("tasks.ganttEmpty")}
              </p>
            ) : null}
            {rows.map((row) =>
              row.type === "group" ? (
                <div
                  key={`group:${row.key}`}
                  className="flex border-b bg-muted/30"
                  style={{ height: ROW_HEIGHT }}
                >
                  <div
                    className="sticky left-0 z-10 flex shrink-0 items-center gap-2 border-r bg-muted px-3"
                    style={{ width: LABEL_WIDTH }}
                  >
                    <span className="min-w-0 truncate">{active?.grouping.header(row.key)}</span>
                    <span className="text-muted-foreground text-xs tabular-nums">{row.count}</span>
                  </div>
                </div>
              ) : (
                <div
                  key={row.key}
                  className="group/row flex border-border/50 border-b"
                  style={{ height: ROW_HEIGHT }}
                >
                  <div
                    className="sticky left-0 z-10 flex shrink-0 items-center gap-1.5 border-r bg-background pr-2 group-hover/row:bg-muted"
                    style={{ width: LABEL_WIDTH, paddingLeft: 8 + row.depth * INDENT }}
                  >
                    {row.hasParts ? (
                      <button
                        type="button"
                        onClick={() => toggleFold(row.key)}
                        className="-m-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                        aria-expanded={row.open}
                        aria-label={t(row.open ? "tasks.ganttFold" : "tasks.ganttUnfold", {
                          title: row.task.title,
                        })}
                      >
                        <ChevronRight
                          className={cn(
                            "h-3.5 w-3.5 transition-transform",
                            row.open && "rotate-90"
                          )}
                          aria-hidden
                        />
                      </button>
                    ) : (
                      <span className="w-3.5 shrink-0" aria-hidden />
                    )}
                    {typed && row.task.task_type ? (
                      <TaskTypeMark type={row.task.task_type} />
                    ) : null}
                    {editing ? (
                      <span className="min-w-0 truncate">{row.task.title}</span>
                    ) : (
                      <Link
                        to={taskHref(row.task.id)}
                        className={cn(
                          "min-w-0 truncate hover:underline",
                          row.task.task_status.category === "done" &&
                            "text-muted-foreground line-through"
                        )}
                      >
                        {row.task.title}
                      </Link>
                    )}
                  </div>
                  <TaskTrack
                    row={row}
                    width={width}
                    x={x}
                    span={spanIn(row.key, row.task)}
                    canMove={canMove}
                    dragging={drag?.key === row.key}
                    scheduleHint={t("tasks.ganttSchedule")}
                    dayLabel={dayLabel}
                    onPress={(event, hold) => press(event, row.key, row.task, hold)}
                    onSchedule={(event) => press(event, row.key, row.task, "move", dayAt(event))}
                    onFollow={follow}
                    onRelease={release}
                    onCancel={() => moveDrag(null)}
                  />
                </div>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

type TrackProps = {
  row: Extract<GanttRow, { type: "task" }>;
  width: number;
  x: (at: number) => number;
  span: GanttSpan | null;
  canMove: boolean;
  dragging: boolean;
  scheduleHint: string;
  dayLabel: (at: number) => string;
  onPress: (event: ReactPointerEvent<HTMLElement>, hold: DragHold) => void;
  onSchedule: (event: ReactPointerEvent<HTMLElement>) => void;
  onFollow: (event: ReactPointerEvent<HTMLElement>) => void;
  onRelease: () => void;
  onCancel: () => void;
};

/** One task's stretch of the axis: its bar or marker, what its parts cover,
 *  or, with no dates, a track to drag dates onto. */
const TaskTrack = ({
  row,
  width,
  x,
  span,
  canMove,
  dragging,
  scheduleHint,
  dayLabel,
  onPress,
  onSchedule,
  onFollow,
  onRelease,
  onCancel,
}: TrackProps) => {
  const done = row.task.task_status.category === "done";
  const pointer = {
    onPointerMove: onFollow,
    onPointerUp: onRelease,
    onPointerCancel: onCancel,
  };
  const tooltip = span
    ? span.kind === "bar"
      ? `${row.task.title} · ${dayLabel(span.start)} → ${dayLabel(span.end - DAY)}`
      : `${row.task.title} · ${dayLabel(span.start)}`
    : undefined;
  const undated = spanOf(row.task) === null;

  return (
    <div
      className={cn("relative", undated && canMove && "cursor-crosshair touch-pan-y")}
      style={{ width }}
      title={undated && canMove && !dragging ? scheduleHint : undefined}
      onPointerDown={undated && canMove ? onSchedule : undefined}
      {...(undated ? pointer : {})}
    >
      {row.parts ? (
        // What its parts cover, as a bracket over the row.
        <div
          className="pointer-events-none absolute top-1 h-1 rounded-sm bg-foreground/40"
          style={{
            left: x(row.parts.start),
            width: Math.max(2, x(row.parts.end) - x(row.parts.start)),
          }}
          aria-hidden
        />
      ) : null}
      {span && span.kind !== "bar" ? (
        <div
          className={cn(
            "absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px]",
            done ? "bg-muted-foreground/60" : "bg-primary",
            canMove ? "cursor-grab touch-none active:cursor-grabbing" : "cursor-pointer"
          )}
          style={{ left: x(span.start) + (x(span.end) - x(span.start)) / 2 }}
          title={tooltip}
          onPointerDown={(event) => onPress(event, "move")}
          {...pointer}
        />
      ) : null}
      {span && span.kind === "bar" ? (
        <div
          className={cn(
            "absolute top-1/2 h-4 -translate-y-1/2 rounded",
            done ? "bg-muted-foreground/40" : "bg-primary/80",
            dragging && "ring-2 ring-ring",
            canMove ? "cursor-grab touch-none active:cursor-grabbing" : "cursor-pointer"
          )}
          style={{ left: x(span.start), width: Math.max(4, x(span.end) - x(span.start)) }}
          title={tooltip}
          onPointerDown={(event) => onPress(event, "move")}
          {...pointer}
        >
          {canMove ? (
            <>
              <span
                className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize touch-none"
                onPointerDown={(event) => onPress(event, "start")}
                {...pointer}
              />
              <span
                className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize touch-none"
                onPointerDown={(event) => onPress(event, "end")}
                {...pointer}
              />
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
