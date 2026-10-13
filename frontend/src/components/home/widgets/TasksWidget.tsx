import { useNavigate } from "@tanstack/react-router";
import { Inbox, SquareCheckBig } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type TaskListRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  buildTaskCalendarEntries,
  type CalendarEntry,
  CalendarView,
  type CalendarViewMode,
} from "@/components/calendar";
import { HomeWidgetCard, HomeWidgetNotice } from "@/components/home/HomeWidgetCard";
import {
  ToolFilterButton,
  ToolFilterPanel,
} from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolLayoutSelect } from "@/components/initiativeTools/shared/ToolLayoutSelect";
import { listLayoutLooks } from "@/components/projects/projectTasksConfig";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { globalTaskColumns } from "@/components/tasks/globalTaskColumns";
import { TaskFilters } from "@/components/tasks/TaskFilters";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { useFocusPreferences } from "@/hooks/useFocusSummary";
import { MY_TASKS_VIEW, useGlobalTasksTable } from "@/hooks/useGlobalTasksTable";
import { useListView } from "@/hooks/useListView";
import { useMyToolRows } from "@/hooks/useMyTools";
import { useProperties } from "@/hooks/useProperties";
import { useTaskListName } from "@/hooks/useTaskListName";
import { communityPath, useCommunityPath } from "@/lib/communityUrl";
import type { HomeTaskList } from "@/lib/home/firstHome";
import { LAYOUT_NAMESPACES, type LayoutEnv } from "@/lib/layouts/fields";
import { taskFields } from "@/lib/layouts/tasks";
import { getProjectColor } from "@/lib/projectColor";
import { entityRefRoute, taskRoute } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";

import { QuickAddTask } from "./QuickAddTask";
import type { HomeWidgetProps, HomeWidgetSettingsProps } from "./types";

/** The ways the widget lists them. */
const MY_TASKS_LAYOUTS = ["table", "calendar"] as const;

/**
 * The reader's tasks from every community, as a table or a calendar: what the
 * My Tasks page was, now one widget of the home page. Its view — layout,
 * filters, sort, grouping, columns — is the reader's own and kept where My
 * Tasks kept it, so nobody's table changed when the page became a widget.
 *
 * Its own options name a list to add to, which puts a line for a new task at
 * the top; a reader with nothing assigned yet is told what lands here, and
 * offered that line, rather than shown an empty table.
 */
export const TasksWidget = ({ options, onConfigure }: HomeWidgetProps) => {
  const { t } = useTranslation(["tasks", "dates", "common", "projects", "home"]);

  const { communities } = useCommunities();
  const { user } = useAuth();
  const gp = useCommunityPath();
  const navigate = useNavigate();

  // This person's view of My Tasks: table or calendar, the calendar's month
  // or week, and the table's grouping and columns.
  const view = useListView(MY_TASKS_VIEW);
  const viewMode: "table" | "calendar" = view.layout === "calendar" ? "calendar" : "table";
  const setViewMode = view.rememberLayout as (next: "table" | "calendar") => void;
  const calendarViewMode = (view.mode ?? "month") as CalendarViewMode;
  const setCalendarViewMode = view.setMode as (next: CalendarViewMode) => void;
  const [calendarFocusDate, setCalendarFocusDate] = useState(() => new Date());
  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;

  const table = useGlobalTasksTable();
  const focus = useFocusPreferences();
  const list = listOf(options);
  // Offered only while the list is there to add to.
  const listName = useTaskListName(list).data;
  const addTo = list && listName ? { list, name: listName } : null;
  // Nothing at all to show, not a narrowed list with nothing in it: that one
  // is said by the table, under the filters that narrowed it.
  const nothingYet =
    !table.isInitialLoad &&
    !table.hasError &&
    table.totalCount === 0 &&
    table.activeFilterCount === 0;

  const { data: allPropertyDefinitions = [] } = useProperties();
  const fields = useMemo(() => taskFields(allPropertyDefinitions), [allPropertyDefinitions]);
  // Rows come from every community: each one's links go to its own.
  const { t: viewT } = useTranslation(LAYOUT_NAMESPACES);
  const env = useMemo<LayoutEnv>(() => {
    const path = (to: string, task: TaskListRead) => {
      const communityId = task.community_id ?? table.activeCommunityId;
      return communityId ? communityPath(communityId, to) : to;
    };
    return {
      t: viewT as TranslateFn,
      communityPath: path,
      // A row without an initiative resolves through /go.
      taskHref: (task) =>
        path(
          task.initiative_id != null
            ? taskRoute(task.initiative_id, task.project_id, task.id)
            : entityRefRoute("task", task.id),
          task
        ),
    };
  }, [viewT, table.activeCommunityId]);
  // Property columns start hidden.
  const propertyHiddenIds = useMemo(
    () => [...fields.values()].filter((field) => field.source === "property").map(({ id }) => id),
    [fields]
  );
  const { columns: keptColumns, setColumns: setColumnVisibility, setGrouping } = view;
  const tableState = { grouping: view.grouping };
  // A column they never chose about is shown, but for the date window, the
  // community ("guild", the id the stored state is keyed by) and properties.
  const effectiveColumnVisibility = useMemo(() => {
    const next = { ...keptColumns };
    for (const id of ["date group", "guild", ...propertyHiddenIds]) {
      if (!(id in next)) next[id] = false;
    }
    return next;
  }, [keptColumns, propertyHiddenIds]);

  const columns = useMemo(
    () =>
      globalTaskColumns({
        activeCommunityId: table.activeCommunityId,
        isUpdatingTask: table.isUpdatingTask,
        changeTaskStatus: table.changeTaskStatus,
        changeTaskStatusById: table.changeTaskStatusById,
        fetchProjectStatuses: table.fetchProjectStatuses,
        projectStatusCache: table.projectStatusCache,
        t: t as TranslateFn,
        isPinned: focus.isPinned,
        togglePin: focus.togglePin,
        fields,
        env,
      }),
    [
      table.activeCommunityId,
      table.isUpdatingTask,
      table.changeTaskStatus,
      table.changeTaskStatusById,
      table.fetchProjectStatuses,
      table.projectStatusCache,
      t,
      fields,
      env,
      focus.isPinned,
      focus.togglePin,
    ]
  );

  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t("myTasks.groupByDate") },
      { id: "guild", label: t("myTasks.groupByCommunity") },
    ],
    [t]
  );

  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];
    // Reuse the shared builder so start/due markers get the same visual
    // treatment as the other calendars, injecting communityId into meta for
    // cross-community navigation. Not draggable here (no reschedule handler).
    table.displayTasks.forEach((task) => {
      for (const entry of buildTaskCalendarEntries(task, getProjectColor(task.project_id), false)) {
        entries.push({
          ...entry,
          meta: { ...(entry.meta as Record<string, unknown>), communityId: task.community_id },
        });
      }
    });
    return entries;
  }, [table.displayTasks]);

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as
      | { taskId?: number; projectId?: number; initiativeId?: number | null; communityId?: number }
      | undefined;
    if (!meta?.taskId) return;
    // A task's URL names its project and initiative. This page spans communities, so
    // a row that didn't carry them resolves through `/go` instead of guessing.
    const path =
      meta.projectId != null && meta.initiativeId != null
        ? taskRoute(meta.initiativeId, meta.projectId, meta.taskId)
        : entityRefRoute("task", meta.taskId);
    void navigate({ to: meta.communityId ? communityPath(meta.communityId, path) : gp(path) });
  };

  const layoutSelect = (
    // The same layout menu as a project's tasks: the table and the calendar,
    // and no presets.
    <ToolLayoutSelect
      layouts={MY_TASKS_LAYOUTS.map((kind) => ({
        slug: kind,
        name: t(`projects:${listLayoutLooks[kind].labelKey}` as never),
        icon: listLayoutLooks[kind].icon,
      }))}
      activeSlug={viewMode}
      modified={viewMode === "table" && table.activeFilterCount > 0}
      onSelect={(slug) => setViewMode(slug as "table" | "calendar")}
      label={t("projects:layouts.label")}
      modifiedLabel={t("projects:filters.modified")}
    />
  );

  return (
    <HomeWidgetCard
      icon={SquareCheckBig}
      title={t("myTasks.title")}
      actions={
        <>
          {/* The calendar view reads none of these task-table filters. */}
          {viewMode === "table" ? (
            <ToolFilterButton
              open={table.filtersOpen}
              onOpenChange={table.setFiltersOpen}
              activeCount={table.activeFilterCount}
            />
          ) : null}
          {layoutSelect}
        </>
      }
    >
      {viewMode === "table" && (
        <div className="space-y-4">
          {addTo && !nothingYet ? <QuickAddTask list={addTo.list} name={addTo.name} /> : null}
          <ToolFilterPanel
            open={table.filtersOpen}
            onOpenChange={table.setFiltersOpen}
            onClear={table.clearFilters}
            activeCount={table.activeFilterCount}
          >
            <TaskFilters
              scope={{ kind: "mine", communities }}
              value={table.filters}
              onChange={table.setFilters}
            />
          </ToolFilterPanel>

          <div className="relative">
            {/* A refetch is a background event: a status change has already
                been applied to the rows optimistically, and the reader can go
                on sorting, paging and checking things off while the
                cross-community aggregate catches up. So this says a refresh is
                running and takes nothing away — no cover, no pointer events,
                no dimming of rows that are already correct. */}
            {table.isRefetching ? (
              <div
                aria-hidden
                className="pointer-events-none absolute inset-x-0 top-0 z-10 h-0.5 overflow-hidden rounded-full bg-primary/15"
              >
                <div className="h-full w-1/3 animate-indeterminate-sweep rounded-full bg-primary/60" />
              </div>
            ) : null}
            <span aria-live="polite" className="sr-only">
              {table.isRefetching ? t("updating") : ""}
            </span>
            {/* The saved sort has to be in hand before the table mounts: it
                seeds its headers once, so a table built on the defaults would
                keep claiming them while the rows came back in the saved order.
                The filters resolve from the same request. */}
            {table.isInitialLoad || !table.preferencesLoaded ? (
              <SkeletonRegion>
                <TableSkeleton rows={8} columns={6} pagination />
              </SkeletonRegion>
            ) : table.hasError ? (
              <p className="py-8 text-center text-destructive text-sm">{t("myTasks.loadError")}</p>
            ) : nothingYet ? (
              <HomeWidgetNotice
                icon={Inbox}
                action={
                  addTo ? (
                    <div className="w-full max-w-md">
                      <QuickAddTask list={addTo.list} name={addTo.name} />
                    </div>
                  ) : (
                    <Button type="button" variant="outline" size="sm" onClick={onConfigure}>
                      {t("home:widgets.tasks.chooseList")}
                    </Button>
                  )
                }
              >
                {t("home:widgets.tasks.empty")}
              </HomeWidgetNotice>
            ) : (
              <DataTable
                columns={columns}
                data={table.displayTasks}
                groupingOptions={groupingOptions}
                columnVisibility={effectiveColumnVisibility}
                onColumnVisibilityChange={setColumnVisibility}
                onGroupingChange={setGrouping}
                initialState={{
                  grouping: tableState.grouping,
                  expanded: true,
                }}
                initialSorting={table.initialSorting}
                enableFilterInput
                filterInputColumnKey="title"
                filterInputPlaceholder={t("filters.filterPlaceholder")}
                enablePagination
                manualPagination
                pageCount={table.totalPages}
                rowCount={table.totalCount}
                pageIndex={table.page - 1}
                onPaginationChange={(pag) => {
                  if (pag.pageSize !== table.pageSize) {
                    table.setPageSize(pag.pageSize);
                    table.setPage(1);
                  } else {
                    table.setPage(pag.pageIndex + 1);
                  }
                }}
                onPrefetchPage={(pageIndex) => table.prefetchPage(pageIndex + 1)}
                manualSorting
                onSortingChange={table.handleSortingChange}
                enableResetSorting
                enableColumnVisibilityDropdown
              />
            )}
          </div>
        </div>
      )}

      {viewMode === "calendar" && (
        <CalendarView
          entries={calendarEntries}
          viewMode={calendarViewMode}
          onViewModeChange={setCalendarViewMode}
          focusDate={calendarFocusDate}
          onFocusDateChange={setCalendarFocusDate}
          onEntryClick={handleEntryClick}
          weekStartsOn={weekStartsOn}
          isLoading={table.isInitialLoad}
        />
      )}
    </HomeWidgetCard>
  );
};

const listOf = (options: Record<string, unknown>): HomeTaskList | null => {
  const list = options.addTo as Partial<HomeTaskList> | undefined;
  return list &&
    typeof list.communityId === "number" &&
    typeof list.initiativeId === "number" &&
    typeof list.projectId === "number"
    ? { communityId: list.communityId, initiativeId: list.initiativeId, projectId: list.projectId }
    : null;
};

const NO_LIST = "none";

/** Which list the line for a new task adds to, out of the reader's projects. */
export const TasksSettings = ({ options, onChange }: HomeWidgetSettingsProps) => {
  const { t } = useTranslation("home");
  const { communities } = useCommunities();
  const { rows } = useMyToolRows(Tool.project, 1, 100, { sortBy: "name", sortDir: "asc" });
  const current = listOf(options);
  const communityNames = new Map(communities.map((community) => [community.id, community.name]));
  const key = (communityId: number, projectId: number) => `${communityId}:${projectId}`;
  const lists = rows.filter((row) => row.initiativeId != null);

  return (
    <div className="space-y-2">
      <Label htmlFor="tasks-widget-list">{t("widgets.tasks.addTo")}</Label>
      <Select
        value={current ? key(current.communityId, current.projectId) : NO_LIST}
        onValueChange={(value) => {
          const { addTo: _dropped, ...rest } = options;
          const row = lists.find((each) => key(each.communityId, each.id) === value);
          onChange(
            row
              ? {
                  ...rest,
                  addTo: {
                    communityId: row.communityId,
                    initiativeId: row.initiativeId,
                    projectId: row.id,
                  },
                }
              : rest
          );
        }}
      >
        <SelectTrigger id="tasks-widget-list">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_LIST}>{t("widgets.tasks.noList")}</SelectItem>
          {lists.map((row) => (
            <SelectItem key={key(row.communityId, row.id)} value={key(row.communityId, row.id)}>
              {communities.length > 1
                ? `${row.name} · ${communityNames.get(row.communityId) ?? ""}`
                : row.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-muted-foreground text-xs">{t("widgets.tasks.addToHint")}</p>
    </div>
  );
};
