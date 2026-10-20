import { format } from "date-fns";
import { type ReactNode, type RefObject, useContext, useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  SearchEntityType,
  type TaskPriority,
  type TaskRead,
  type TaskStatusRead,
  type TaskUpdate,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { CommentSection } from "@/components/comments/CommentSection";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import type { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { TaskChecklist } from "@/components/tasks/TaskChecklist";
import { TaskPriorityOption } from "@/components/tasks/TaskPriorityOption";
import { statusTriggerStyle, TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { CasePanel } from "@/components/tickets/CasePanel";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useComments, useCommentsCache, useCommentThreadState } from "@/hooks/useComments";
import { useDateLocale } from "@/hooks/useDateLocale";
import { ItemDraftContext } from "@/hooks/useFieldSave";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import {
  TASK_SAVES,
  type TaskEdit,
  useGenerateTaskDescription,
  useTaskFieldSave,
  useTaskSaveOptions,
} from "@/hooks/useTasks";
import { dateRangeBounds } from "@/lib/dateRange";
import { toast } from "@/lib/mascotToast";
import { fromStored, type RecurrenceRule, rulePayload } from "@/lib/recurrence";
import { referenceRef } from "@/lib/smartChips";
import { PRIORITY_ORDER } from "@/lib/sorting";
import { dateTimePattern } from "@/lib/timeFormat";
import { taskRoute } from "@/lib/tools";
import {
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
  isAnonymizedUser,
} from "@/lib/userDisplay";

import { type DetailKind, useItemContext } from "./DetailLayoutView";
import { FieldFrame, sameIds, sameJson, useFieldDraft } from "./editing";
import { DescriptionField, TagsField, TitleField } from "./fieldEditors";
import { TASK_LAYOUT, taskFields } from "./tasks";

/** What the task's detail shares with its parts, beside the task itself. */
export interface TaskLayoutContext {
  /** The server says the reader cannot change the task. */
  readOnly: boolean;
  /** Why, when it does. */
  readOnlyMessage: string | null;
  /** The project's statuses, which the task's own joins when the project dropped it. */
  statuses: TaskStatusRead[];
  /** Whether a column takes one more task; left out where none is limited. */
  isFull?: (taskStatusId: number) => boolean;
  initiativeId: number | null;
  currentUserId?: number;
  askScope: ReturnType<typeof useScopePrompt>["ask"];
  /** The overflow menu of what else can be done with the task. */
  actions: ReactNode;
  /** Set when the detail is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  /** Drawn in the layout editor, where nothing is changed: a description
   *  draft kept on the device stays there. */
  preview?: boolean;
}

const useTaskLayout = useItemContext<TaskLayoutContext>;

type EditorProps = { item: TaskRead; label: string };

/** The task's title, which is the detail's heading. */
const TitleEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskLayout();
  return (
    <TitleField
      id="task-title"
      label={label}
      value={task.title}
      save={useTaskFieldSave(task, label, askScope)}
      readOnly={readOnly}
      placeholder={t("taskForm.titlePlaceholder")}
    />
  );
};

/** The description ({@link DescriptionField}), which AI can write a first
 *  draft of where it is on. */
const DescriptionEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, initiativeId, leaving, askScope, preview } = useTaskLayout();
  const { isEnabled: aiEnabled } = useAIEnabled();
  const generate = useGenerateTaskDescription();
  // A task being added has nothing yet for AI to write from.
  const adding = useContext(ItemDraftContext) !== null;
  return (
    <DescriptionField
      kind={TASK_SAVES}
      id={task.id}
      options={useTaskSaveOptions(task, askScope)}
      label={label}
      htmlId="task-description"
      value={task.description}
      readOnly={readOnly}
      preview={preview}
      initiativeId={initiativeId}
      subject={referenceRef(SearchEntityType.task, task.id)}
      leaving={leaving}
      placeholder={t("edit.descriptionPlaceholder")}
      suggest={
        aiEnabled && !adding
          ? {
              label: t("edit.aiGenerate"),
              run: async () => {
                const { description } = await generate.mutateAsync(task.id);
                toast.success(t("edit.descriptionGenerated"));
                return description;
              },
            }
          : undefined
      }
    />
  );
};

const StatusEditor = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation(["tasks", "projects"]);
  const { readOnly, statuses, isFull, askScope } = useTaskLayout();
  const label = t("taskForm.statusLabel");
  const save = useTaskFieldSave(task, label, askScope);
  // A task keeps the status it was given after the project drops it, and the
  // select can only name a status it lists.
  const options = statuses.some((status) => status.id === task.task_status_id)
    ? statuses
    : [...statuses, task.task_status];
  const edit = (status: TaskStatusRead): TaskEdit => ({
    patch: { task_status_id: status.id },
    shows: { task_status_id: status.id, task_status: status },
  });
  return (
    <FieldFrame label={label} htmlFor="task-status" save={save}>
      <Select
        value={String(task.task_status_id)}
        onValueChange={(selected) => {
          const next = options.find((status) => String(status.id) === selected);
          if (next && next.id !== task.task_status_id) {
            void save.save(edit(next), edit(task.task_status));
          }
        }}
        disabled={readOnly}
      >
        <SelectTrigger
          id="task-status"
          className="border-2"
          style={statusTriggerStyle(task.task_status)}
        >
          <TaskStatusOption status={task.task_status} />
        </SelectTrigger>
        <SelectContent>
          {options.map((status) => {
            const full = status.id !== task.task_status_id && isFull?.(status.id) === true;
            return (
              <SelectItem key={status.id} value={String(status.id)} disabled={full}>
                <TaskStatusOption status={status} />
                {full ? (
                  <span className="text-muted-foreground text-xs">{t("projects:kanban.full")}</span>
                ) : null}
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>
    </FieldFrame>
  );
};

const PriorityEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskLayout();
  const save = useTaskFieldSave(task, label, askScope);
  return (
    <FieldFrame label={label} htmlFor="task-priority" save={save}>
      <Select
        value={task.priority}
        onValueChange={(selected) => {
          const priority = selected as TaskPriority;
          void save.save({ patch: { priority }, shows: { priority } });
        }}
        disabled={readOnly}
      >
        <SelectTrigger id="task-priority">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PRIORITY_ORDER.map((option) => (
            <SelectItem key={option} value={option}>
              <TaskPriorityOption priority={option} label={t(`priority.${option}` as never)} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FieldFrame>
  );
};

const AssigneesEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, currentUserId, askScope } = useTaskLayout();
  const save = useTaskFieldSave(task, label, askScope);
  const saved = task.assignees.map((assignee) => assignee.id);
  // Who is added shows from the draft until the task comes back naming them.
  const edit = (ids: number[]): TaskEdit => ({
    patch: { assignee_ids: ids },
    shows: { assignees: task.assignees.filter((assignee) => ids.includes(assignee.id)) },
  });
  const draft = useFieldDraft(
    saved,
    (ids) =>
      save.save(
        edit(ids),
        ids.length === 0
          ? { patch: { assignee_ids: saved }, shows: { assignees: task.assignees } }
          : undefined
      ),
    sameIds
  );
  return (
    <FieldFrame label={label} save={save}>
      <MemberMultiSelect
        scope={{ type: "canOpen", tool: Tool.project, id: task.project_id }}
        selectedIds={draft.value}
        selectedUsers={task.assignees}
        onChange={draft.edit}
        disabled={readOnly}
        emptyMessage={t("taskForm.assigneesEmptyMessage")}
        currentUserId={currentUserId}
      />
    </FieldFrame>
  );
};

const TagsEditor = ({ item: task, label }: EditorProps) => {
  const { t } = useTranslation("tasks");
  const { readOnly, askScope } = useTaskLayout();
  return (
    <TagsField
      label={label}
      tags={task.tags}
      save={useTaskFieldSave(task, label, askScope)}
      readOnly={readOnly}
      placeholder={t("taskForm.tagsPlaceholder")}
    />
  );
};

/** A stored date as the pickers hold it: local, to the minute. */
const toLocalInputValue = (value: string | null) => {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  const pad = (segment: number) => segment.toString().padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const DATE_FIELDS = [
  { key: "start", field: "start_date", label: "taskForm.startDateLabel", id: "task-start-date" },
  { key: "due", field: "due_date", label: "taskForm.dueDateLabel", id: "task-due-date" },
] as const;

type DatePair = Record<(typeof DATE_FIELDS)[number]["key"], string>;

/** The start and due dates, as one control: checked and saved as a pair. */
const DatesEditor = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { readOnly, askScope } = useTaskLayout();
  const save = useTaskFieldSave(task, t("taskForm.sections.schedule"), askScope);
  const saved: DatePair = {
    start: toLocalInputValue(task.start_date),
    due: toLocalInputValue(task.due_date),
  };
  const inverted = (pair: DatePair) => dateRangeBounds(pair.start, pair.due).isInverted;
  // Only the dates that moved are sent; Undo puts back what was stored.
  const draft = useFieldDraft(
    saved,
    (pair) => {
      const moved = DATE_FIELDS.filter(({ key }) => pair[key] !== saved[key]);
      const at = (local: string) => (local ? new Date(local).toISOString() : null);
      const edit: TaskEdit = { patch: {}, shows: {} };
      const undo: TaskEdit = { patch: {}, shows: {} };
      for (const { key, field } of moved) {
        edit.patch[field] = at(pair[key]);
        edit.shows[field] = at(pair[key]);
        undo.patch[field] = task[field];
        undo.shows[field] = task[field];
      }
      return save.save(edit, moved.some(({ key }) => !pair[key]) ? undo : undefined);
    },
    sameJson,
    (pair) => !inverted(pair)
  );
  const range = dateRangeBounds(draft.value.start, draft.value.due);
  const calendarProps = { start: range.startCalendarProps, due: range.endCalendarProps };
  return (
    <FieldFrame
      label={t("taskForm.sections.schedule")}
      save={save}
      changed={draft.changed}
      keys={draft.keys}
    >
      <div className="grid grid-cols-pair gap-4">
        {DATE_FIELDS.map(({ key, label, id }) => (
          <div key={key} className="space-y-2">
            <Label htmlFor={id} className="font-normal text-muted-foreground text-xs">
              {t(label)}
            </Label>
            <DateTimePicker
              id={id}
              value={draft.value[key]}
              onChange={(next) => draft.edit({ ...draft.value, [key]: next })}
              disabled={readOnly}
              placeholder={t("common:optional")}
              calendarProps={calendarProps[key]}
            />
          </div>
        ))}
      </div>
      {range.isInverted ? (
        <p className="text-destructive text-sm" role="alert">
          {t("dates:invalidRange")}
        </p>
      ) : null}
    </FieldFrame>
  );
};

type Repeat = { rule: RecurrenceRule | "custom" | null; strategy: TaskRead["recurrence_strategy"] };

const TaskRecurrenceEditor = ({ item: task, label }: EditorProps) => {
  const { readOnly, askScope } = useTaskLayout();
  const save = useTaskFieldSave(task, label, askScope);
  const start = task.due_date ?? task.start_date;
  const saved: Repeat = {
    rule: fromStored(task.recurrence, start, task.recurrence_shift),
    strategy: task.recurrence_strategy ?? "fixed",
  };
  const edit = ({ rule, strategy }: Repeat): TaskEdit => ({
    patch: { ...rulePayload(rule), recurrence_strategy: rule ? strategy : "fixed" },
    // The stored rule is the server's to work out from the zone it is sent with.
    shows: rule
      ? { recurrence_strategy: strategy }
      : { recurrence: null, recurrence_strategy: "fixed" },
  });
  // A rule this editor cannot show cannot be sent back, so only a rule it can
  // is offered back after it is removed.
  const draft = useFieldDraft(
    saved,
    (repeat) =>
      save.save(
        edit(repeat),
        repeat.rule === null && saved.rule !== "custom"
          ? {
              ...edit(saved),
              shows: { recurrence: task.recurrence, recurrence_strategy: saved.strategy },
            }
          : undefined
      ),
    sameJson
  );
  return (
    <FieldFrame label={label} hideLabel save={save} changed={draft.changed} keys={draft.keys}>
      <RecurrenceEditor
        kind="task"
        value={draft.value.rule}
        onChange={(rule) => draft.edit({ ...draft.value, rule })}
        strategy={draft.value.strategy}
        onStrategyChange={(strategy) => draft.edit({ ...draft.value, strategy })}
        disabled={readOnly}
        referenceDate={start}
        stored={task.recurrence ? { rule: task.recurrence, shift: task.recurrence_shift } : null}
      />
    </FieldFrame>
  );
};

const Checklist = ({ item: task }: EditorProps) => {
  const { readOnly } = useTaskLayout();
  // Its items are each saved on a task that exists.
  if (useContext(ItemDraftContext) !== null) return null;
  return <TaskChecklist taskId={task.id} items={task.checklist ?? []} canEdit={!readOnly} />;
};

/** Who made the task and when. */
const Byline = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation("tasks");
  const dateLocale = useDateLocale();
  const createdAt = useMemo(() => new Date(task.created_at), [task.created_at]);
  const relative = useRelativeTime(createdAt);
  const creator = task.creator;
  const anonymized = isAnonymizedUser(creator);
  // A creator who has since left the community is named by id.
  const name =
    creator || task.created_by != null
      ? getUserDisplayName(creator ?? { id: task.created_by })
      : null;
  const avatarSrc = creator && !anonymized ? getAvatarSrc(creator) : undefined;
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex w-fit items-center gap-2 text-muted-foreground text-xs">
            {name ? (
              <Avatar className="h-5 w-5 border text-3xs">
                {avatarSrc ? <AvatarImage src={avatarSrc} alt={name} /> : null}
                <AvatarFallback userId={anonymized ? null : (creator?.id ?? null)}>
                  {getInitialsForUser(creator)}
                </AvatarFallback>
              </Avatar>
            ) : null}
            <span>
              {name
                ? t("edit.createdBy", { name, time: relative })
                : t("edit.createdAt", { time: relative })}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent>
          {format(createdAt, dateTimePattern("PP", { seconds: true }), { locale: dateLocale })}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

const Notice = () => {
  const { readOnlyMessage } = useTaskLayout();
  return readOnlyMessage ? (
    <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-muted-foreground text-sm">
      {readOnlyMessage}
    </p>
  ) : null;
};

const Case = ({ task }: { task: TaskRead }) => (
  <CasePanel
    taskId={task.id}
    canEdit={!useTaskLayout().readOnly}
    assigneeIds={task.assignees.map((assignee) => assignee.id)}
  />
);

const Comments = ({ task }: { task: TaskRead }) => {
  const { t } = useTranslation("tasks");
  const { initiativeId } = useTaskLayout();
  const params = { task_id: task.id };
  const query = useComments(params);
  const cache = useCommentsCache(params);
  const thread = useCommentThreadState(params);
  return (
    <>
      {query.isError ? <p className="text-destructive text-sm">{t("edit.commentsError")}</p> : null}
      <CommentSection
        entityType="task"
        entityId={task.id}
        comments={query.data ?? []}
        isLoading={query.isLoading}
        hasOlder={query.hasNextPage}
        isLoadingOlder={query.isFetchingNextPage}
        onLoadOlder={() => void query.fetchNextPage()}
        onCommentCreated={cache.putComment}
        onCommentDeleted={cache.removeComment}
        onCommentUpdated={cache.putComment}
        initiativeId={initiativeId ?? 0}
        locked={thread.data?.locked ?? false}
        canModerate={thread.data?.canModerate ?? false}
      />
    </>
  );
};

/** A task's detail: its fields, its own parts and where it lives. A task is
 *  addressed inside its project, so that is the tool its links refresh. */
export const TASK_DETAIL: DetailKind<TaskRead, TaskLayoutContext, TaskUpdate> = {
  spec: TASK_LAYOUT,
  fields: taskFields,
  namespaces: ["projects"],
  editors: {
    title: TitleEditor,
    description: DescriptionEditor,
    assignees: AssigneesEditor,
    priority: PriorityEditor,
    recurrence: TaskRecurrenceEditor,
    tags: TagsEditor,
    checklist: Checklist,
  },
  parts: {
    status: (_node, task) => <StatusEditor task={task} />,
    dates: (_node, task) => <DatesEditor task={task} />,
    byline: (_node, task) => <Byline task={task} />,
    notice: () => <Notice />,
    case: (_node, task) => <Case task={task} />,
    comments: (_node, task) => <Comments task={task} />,
  },
  home: (task, context) => ({
    saves: TASK_SAVES,
    readOnly: context.readOnly,
    initiativeId: context.initiativeId,
    canOpen: { tool: Tool.project, id: task.project_id },
    links: {
      entity: { id: task.project_id, initiative_id: task.project?.initiative_id ?? null },
      target: { type: SearchEntityType.task, id: task.id },
      title: task.title,
      layout: "rows",
    },
    actions: context.actions,
  }),
  taskRoute: (task, context, taskId) => taskRoute(context.initiativeId, task.project_id, taskId),
  addingParts: ["status", "dates"],
};

/** A task not yet added to `projectId`, in `status`, as its detail draws it
 *  while it is. */
export const blankTask = (projectId: number, status: TaskStatusRead): TaskRead => ({
  id: 0,
  project_id: projectId,
  title: "",
  description: null,
  priority: "medium",
  start_date: null,
  due_date: null,
  recurrence: null,
  recurrence_strategy: "fixed",
  recurrence_occurrence_count: 0,
  recurrence_shift: 0,
  recurrence_anchor: null,
  recurrence_anchor_count: 0,
  recurrence_until: null,
  series_id: null,
  series_size: 0,
  task_status_id: status.id,
  task_status: status,
  created_at: "",
  updated_at: "",
  completed_at: null,
  position: 0,
  archived_at: null,
  created_by: null,
  creator: null,
  assignees: [],
  comment_count: 0,
  blocked_by_open_count: 0,
  project: null,
  checklist: [],
  checklist_progress: null,
  tags: [],
  properties: [],
  plugin_values: [],
});
