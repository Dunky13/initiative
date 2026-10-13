/**
 * The details the layout editor lays out: a project's task, and the initiative
 * calendar's event; and the presets each tool's lists offer, with its own
 * filter controls. Each says what kind of detail it is, what the editor calls
 * it and its parts, what its fields are, whether plug-ins draw on it, and
 * draws itself with one of its own while it is laid out.
 */

import { MoreHorizontal } from "lucide-react";
import { type ReactNode, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import { type PropertyDefinitionRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { PropertyFilter } from "@/components/properties/PropertyFilter";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { TaskFilters } from "@/components/tasks/TaskFilters";
import { TaskStatusPriorityFilters } from "@/components/tasks/TaskStatusPriorityFilters";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useCalendarEntries } from "@/hooks/useCalendarEntries";
import { useCalendarEvent } from "@/hooks/useCalendarEvents";
import { useGalleryImagesFeed } from "@/hooks/useGalleries";
import { useQueue } from "@/hooks/useQueues";
import { useTask, useTasks } from "@/hooks/useTasks";
import { type CalendarFilters, EMPTY_CALENDAR_FILTERS } from "@/lib/filters/calendarFilters";
import { buildTaskListParams, EMPTY_TASK_FILTERS } from "@/lib/filters/taskFilters";
import type { DetailLayoutSpec, StoredRegions } from "@/lib/layouts/detailLayout";
import { EventLayoutView } from "@/lib/layouts/eventLayout";
import { EVENT_LAYOUT, eventFields } from "@/lib/layouts/events";
import type { FieldDef } from "@/lib/layouts/fields";
import { GalleryImageLayoutView } from "@/lib/layouts/galleryImageLayout";
import { GALLERY_IMAGE_LAYOUT, galleryImageFields } from "@/lib/layouts/galleryImages";
import { CALENDAR_PRESETS, TASK_PRESETS } from "@/lib/layouts/presets";
import { QueueItemLayoutView } from "@/lib/layouts/queueItemLayout";
import { QUEUE_ITEM_LAYOUT, queueItemFields } from "@/lib/layouts/queueItems";
import { TaskLayoutView } from "@/lib/layouts/taskLayout";
import { TASK_LAYOUT, taskFields } from "@/lib/layouts/tasks";
import type { LayoutNode } from "@/lib/layouts/tree";

import { editablePresets } from "./LayoutPresets";
import type { LayoutProject } from "./LayoutSettingsPanel";

/** A kind of detail, as the editor lays it out. */
export type EditableDetail = {
  spec: DetailLayoutSpec;
  /** What the editor says about it, as keys in `projects`, each naming its
   *  namespace where it is another: its name, what it is, that it is as
   *  shipped, what its title and its fields are, and where its own parts'
   *  names (`parts`) and what each does (`partHelp`) are, as the start of their
   *  keys. */
  words: {
    name: string;
    help: string;
    shipped: string;
    titleHelp: string;
    hiddenHelp: string;
    parts: string;
  };
  /** Its fields, by id: the built-ins, and the plug-ins' where they draw on it. */
  fields: (definitions: PropertyDefinitionRead[], plugins: FieldDef[]) => Map<string, FieldDef>;
  /** The detail drawn with one of its own, laid out as `tree` says. */
  preview: (tree: LayoutNode) => ReactNode;
};

/** The detail tree's regions, as a detail draws them. */
const regionsOf = (tree: LayoutNode): StoredRegions => ({
  header: tree.children?.[0]?.children ?? [],
  main: tree.children?.[1]?.children ?? [],
  side: tree.children?.[2]?.children ?? [],
});

/** What a detail's menu is drawn as, where nothing in it is used. */
const ActionsPreview = () => (
  <Button type="button" variant="outline" size="icon" tabIndex={-1} aria-hidden>
    <MoreHorizontal className="h-4 w-4" />
  </Button>
);

const noop = () => {};

/** The task's detail drawn with the project's first task. */
const TaskPreview = ({ project, tree }: { project: LayoutProject; tree: LayoutNode }) => {
  const { t } = useTranslation(["projects", "layouts"]);
  const { user } = useAuth();
  const scopePrompt = useScopePrompt();
  const leaving = useRef(true);
  const params = useMemo(
    () => ({ ...buildTaskListParams(EMPTY_TASK_FILTERS, { projectId: project.id }), page_size: 1 }),
    [project.id]
  );
  const listed = useTasks(params);
  const first = listed.data?.items[0]?.id ?? null;
  const task = useTask(first).data;
  const layout = useMemo(() => regionsOf(tree), [tree]);
  if (task) {
    return (
      <TaskLayoutView
        task={task}
        layout={layout}
        editing
        context={{
          readOnly: false,
          // Drawn here so it can be placed; a reader sees it only when they
          // cannot change the task.
          readOnlyMessage: t("layouts:noticePreview"),
          statuses: project.statuses,
          initiativeId: project.initiativeId,
          currentUserId: user?.id,
          askScope: scopePrompt.ask,
          actions: <ActionsPreview />,
          leaving,
          preview: true,
        }}
      />
    );
  }
  return listed.isSuccess && first === null ? (
    <p className="text-muted-foreground text-sm">{t("layouts:noTasks")}</p>
  ) : null;
};

const YEAR = 365 * 24 * 60 * 60 * 1000;

/** The event's detail drawn with the first of the initiative's events within
 *  a year either side of today. */
const EventPreview = ({ initiativeId, tree }: { initiativeId: number; tree: LayoutNode }) => {
  const { t } = useTranslation(["projects", "layouts"]);
  const leaving = useRef(true);
  const params = useMemo(() => {
    const now = Date.now();
    return {
      initiative_id: initiativeId,
      include_tasks: false,
      start_after: new Date(now - YEAR).toISOString(),
      start_before: new Date(now + YEAR).toISOString(),
    };
  }, [initiativeId]);
  const listed = useCalendarEntries(params);
  const first = listed.data?.events[0]?.id ?? null;
  const event = useCalendarEvent(first).data;
  const layout = useMemo(() => regionsOf(tree), [tree]);
  if (event) {
    return (
      <EventLayoutView
        event={event}
        layout={layout}
        editing
        context={{
          readOnly: false,
          initiativeId,
          occurrence: undefined,
          occurrenceStart: event.start_at,
          shownStart: event.start_at,
          shownEnd: event.end_at,
          askScope: async () => null,
          onMoved: noop,
          onShifted: noop,
          leaving,
          actions: <ActionsPreview />,
          preview: true,
        }}
      />
    );
  }
  return listed.isSuccess && first === null ? (
    <p className="text-muted-foreground text-sm">{t("layouts:noEvents")}</p>
  ) : null;
};

/** The queue's item detail drawn with its first item. */
const QueueItemPreview = ({
  queueId,
  initiativeId,
  tree,
}: {
  queueId: number;
  initiativeId: number;
  tree: LayoutNode;
}) => {
  const { t } = useTranslation("layouts");
  const leaving = useRef(true);
  const queue = useQueue(queueId);
  const first = queue.data?.items[0];
  const layout = useMemo(() => regionsOf(tree), [tree]);
  if (first) {
    return (
      <QueueItemLayoutView
        item={first}
        layout={layout}
        editing
        context={{
          readOnly: false,
          queueId,
          initiativeId,
          leaving,
          actions: <ActionsPreview />,
          preview: true,
        }}
      />
    );
  }
  return queue.isSuccess ? (
    <p className="text-muted-foreground text-sm">{t("queueItemDetail.noItems")}</p>
  ) : null;
};

/** The gallery's picture detail drawn with its first picture. */
const GalleryImagePreview = ({
  galleryId,
  initiativeId,
  tree,
}: {
  galleryId: number;
  initiativeId: number;
  tree: LayoutNode;
}) => {
  const { t } = useTranslation("layouts");
  const leaving = useRef(true);
  const pictures = useGalleryImagesFeed(galleryId);
  const first = pictures.data?.pages[0]?.items[0];
  const layout = useMemo(() => regionsOf(tree), [tree]);
  if (first) {
    return (
      <GalleryImageLayoutView
        image={first}
        layout={layout}
        editing
        context={{
          readOnly: false,
          galleryId,
          initiativeId,
          canDeleteVersions: false,
          leaving,
          actions: <ActionsPreview />,
          preview: true,
        }}
      />
    );
  }
  return pictures.isSuccess ? (
    <p className="text-muted-foreground text-sm">{t("galleryImageDetail.noItems")}</p>
  ) : null;
};

/** A project's task detail. */
export const taskDetail = (project: LayoutProject): EditableDetail => ({
  spec: TASK_LAYOUT,
  words: {
    name: "layouts:taskLayout",
    help: "layouts:detailHelp",
    shipped: "layouts:shipped",
    titleHelp: "layouts:detailTitleHelp",
    hiddenHelp: "layouts:hiddenHelp",
    parts: "layouts:",
  },
  fields: taskFields,
  preview: (tree) => <TaskPreview project={project} tree={tree} />,
});

/** The initiative calendar's event detail. */
export const eventDetail = (initiativeId: number): EditableDetail => ({
  spec: EVENT_LAYOUT,
  words: {
    name: "layouts:eventDetail.name",
    help: "layouts:eventDetail.help",
    shipped: "layouts:eventDetail.shipped",
    titleHelp: "layouts:eventDetail.titleHelp",
    hiddenHelp: "layouts:eventDetail.hiddenHelp",
    parts: "layouts:eventDetail.",
  },
  fields: eventFields,
  preview: (tree) => <EventPreview initiativeId={initiativeId} tree={tree} />,
});

/** A queue's item detail. */
export const queueItemDetail = (queueId: number, initiativeId: number): EditableDetail => ({
  spec: QUEUE_ITEM_LAYOUT,
  words: {
    name: "layouts:queueItemDetail.name",
    help: "layouts:queueItemDetail.help",
    shipped: "layouts:queueItemDetail.shipped",
    titleHelp: "layouts:queueItemDetail.titleHelp",
    hiddenHelp: "layouts:queueItemDetail.hiddenHelp",
    parts: "layouts:queueItemDetail.",
  },
  fields: queueItemFields,
  preview: (tree) => <QueueItemPreview queueId={queueId} initiativeId={initiativeId} tree={tree} />,
});

/** A gallery's picture detail. */
export const galleryImageDetail = (galleryId: number, initiativeId: number): EditableDetail => ({
  spec: GALLERY_IMAGE_LAYOUT,
  words: {
    name: "layouts:galleryImageDetail.name",
    help: "layouts:galleryImageDetail.help",
    shipped: "layouts:galleryImageDetail.shipped",
    titleHelp: "layouts:galleryImageDetail.titleHelp",
    hiddenHelp: "layouts:galleryImageDetail.hiddenHelp",
    parts: "layouts:galleryImageDetail.",
  },
  fields: galleryImageFields,
  preview: (tree) => (
    <GalleryImagePreview galleryId={galleryId} initiativeId={initiativeId} tree={tree} />
  ),
});

/** The item detail each tool lays out on its own, with no list of its own to
 *  lay out beside it: what its editor offers. */
export const ITEM_DETAILS: Partial<
  Record<Tool, (id: number, initiativeId: number) => EditableDetail>
> = {
  [Tool.queue]: queueItemDetail,
  [Tool.gallery]: galleryImageDetail,
};

/** A project's lists' presets: its tasks' filters, and a table's sort. */
export const taskPresets = (project: LayoutProject) =>
  editablePresets({
    kind: TASK_PRESETS,
    empty: EMPTY_TASK_FILTERS,
    controls: (value, onChange) => (
      <TaskFilters
        scope={{
          kind: "project",
          memberScope: { type: "canOpen", tool: Tool.project, id: project.id },
          statuses: project.statuses,
          initiativeId: project.initiativeId,
        }}
        value={value}
        onChange={onChange}
      />
    ),
    sortable: (kind) => kind === "table",
  });

/** The initiative calendar's presets: what its tasks are, and the properties
 *  its events and tasks carry, as its page filters them. */
export const calendarPresets = (initiativeId: number) =>
  editablePresets<CalendarFilters>({
    kind: CALENDAR_PRESETS,
    empty: EMPTY_CALENDAR_FILTERS,
    controls: (value, onChange) => (
      <div className="space-y-4">
        <TaskStatusPriorityFilters
          statusFilters={value.status_categories}
          onStatusChange={(status_categories) => onChange({ ...value, status_categories })}
          priorityFilters={value.priorities}
          onPriorityChange={(priorities) => onChange({ ...value, priorities })}
        />
        <PropertyFilter
          value={value.properties}
          onChange={(properties) => onChange({ ...value, properties })}
          initiativeId={initiativeId}
        />
      </div>
    ),
    sortable: () => false,
  });
