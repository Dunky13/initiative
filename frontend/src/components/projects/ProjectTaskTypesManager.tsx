/**
 * A project's task types: the kinds of task it holds (a task, a bug, an idea),
 * each with its own icon, colour and page. Every project starts with four, and
 * always keeps at least one; one of them is the default a new task takes.
 *
 * Laid out as the status manager is: a table of drafts saved together, drag to
 * reorder, and a dialog asking where a deleted type's tasks go. A type's page
 * is changed in the project's layout editor, which "Edit page" opens on it.
 */

import {
  DndContext,
  type DragEndEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Link } from "@tanstack/react-router";
import type { TFunction } from "i18next";
import { GripVertical, Loader2, Pencil, Plus, Save, Trash2 } from "lucide-react";
import type { IconName } from "lucide-react/dynamic";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type TaskTypeRead,
  type TaskTypeUpdate,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { IconPicker } from "@/components/ui/icon-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateTaskType,
  useDeleteTaskType,
  useProjectTaskTypes,
  useReorderTaskTypes,
  useUpdateTaskType,
} from "@/hooks/useProjects";
import { useInstanceLayouts } from "@/hooks/useToolLayouts";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { useCommunityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

/** The most types a project may have; the server holds it to the same. */
export const MAX_TASK_TYPES = 20;

type TypeDraft = { name: string; color: string; icon: IconName };
type DraftField = keyof TypeDraft;

const sortTypes = (items: TaskTypeRead[]): TaskTypeRead[] => {
  return [...items].sort((a, b) => {
    if (a.position === b.position) {
      return a.id - b.id;
    }
    return a.position - b.position;
  });
};

/** The `?layout=` value that opens the layout editor on one type's page. */
export const taskTypeLayout = (typeId: number): string => `task:${typeId}`;

/** Where a deleted type's tasks go unless the reader picks another: the
 *  project's default, or, when the default is the one going, the first type
 *  left. */
const defaultFallback = (types: TaskTypeRead[], target: TaskTypeRead): number | null => {
  const others = types.filter((type) => type.id !== target.id);
  return (others.find((type) => type.is_default) ?? others[0])?.id ?? null;
};

interface ProjectTaskTypesManagerProps {
  projectId: number;
  initiativeId: number;
  canManage: boolean;
}

export const ProjectTaskTypesManager = ({
  projectId,
  initiativeId,
  canManage,
}: ProjectTaskTypesManagerProps) => {
  const { t } = useTranslation(["projects", "common", "errors"]);
  const gp = useCommunityPath();
  // The layout editor needs a tablet-sized screen, and a step above write
  // access, which the project's layouts say.
  const wide = atLeast(useWidthClass(), "md");
  const canConfigurePages =
    useInstanceLayouts(Tool.project, projectId).data?.can_configure ?? false;
  const editor = gp(`${toolDetailRoute(Tool.project, initiativeId, projectId)}/layouts`);

  const [orderedTypes, setOrderedTypes] = useState<TaskTypeRead[]>([]);
  const [drafts, setDrafts] = useState<Record<number, TypeDraft>>({});
  const [addOpen, setAddOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [startFromId, setStartFromId] = useState<string>("");
  const [deleteTarget, setDeleteTarget] = useState<TaskTypeRead | null>(null);
  const [fallbackId, setFallbackId] = useState<string>("");

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 200,
        tolerance: 8,
      },
    })
  );

  const typesQuery = useProjectTaskTypes(projectId);

  const reorderTypes = useReorderTaskTypes(projectId, {
    onSuccess: (data) => {
      setOrderedTypes(sortTypes(data));
      toast.success(t("taskTypes.orderSaved"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:taskTypes.reorderError"));
    },
  });

  useEffect(() => {
    if (!typesQuery.data || reorderTypes.isPending) {
      return;
    }
    const sorted = sortTypes(typesQuery.data);
    setOrderedTypes(sorted);
    const nextDrafts: Record<number, TypeDraft> = {};
    sorted.forEach((type) => {
      nextDrafts[type.id] = { name: type.name, color: type.color, icon: type.icon as IconName };
    });
    setDrafts(nextDrafts);
  }, [typesQuery.data, reorderTypes.isPending]);

  const createType = useCreateTaskType(projectId, {
    onSuccess: () => {
      setNewName("");
      setAddOpen(false);
      toast.success(t("taskTypes.created"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:taskTypes.createError"));
    },
  });

  const updateType = useUpdateTaskType(projectId, {
    onSuccess: () => {
      toast.success(t("taskTypes.updated"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:taskTypes.updateError"));
    },
  });

  const deleteTypeMutation = useDeleteTaskType(projectId, {
    onSuccess: () => {
      toast.success(t("taskTypes.deleted"));
      setDeleteTarget(null);
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:taskTypes.deleteError"));
    },
  });

  // Separate instance for bulk updates in handleSaveAll, so each row's result
  // is reported once by the summary rather than by the single-row toasts.
  const bulkUpdateType = useUpdateTaskType(projectId);

  const types = useMemo(() => {
    const source = orderedTypes.length ? orderedTypes : (typesQuery.data ?? []);
    return sortTypes(source);
  }, [orderedTypes, typesQuery.data]);

  const defaultType = types.find((type) => type.is_default) ?? types[0];
  const atLimit = types.length >= MAX_TASK_TYPES;

  const handleDragEnd = (event: DragEndEvent) => {
    if (!canManage) {
      return;
    }
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }
    setOrderedTypes((prev) => {
      const oldIndex = prev.findIndex((type) => type.id === Number(active.id));
      const newIndex = prev.findIndex((type) => type.id === Number(over.id));
      if (oldIndex === -1 || newIndex === -1) {
        return prev;
      }
      const next = arrayMove(prev, oldIndex, newIndex);
      reorderTypes.mutate({ items: next.map((type, index) => ({ id: type.id, position: index })) });
      return next.map((type, index) => ({ ...type, position: index }));
    });
  };

  const handleFieldChange = (typeId: number, field: DraftField, value: string) => {
    setDrafts((prev) => {
      const source = types.find((type) => type.id === typeId);
      const existing = prev[typeId] ?? {
        name: source?.name ?? "",
        color: source?.color ?? "",
        icon: (source?.icon ?? "") as IconName,
      };
      return { ...prev, [typeId]: { ...existing, [field]: value } };
    });
  };

  /** What a row's draft changes, or null where it changes nothing. */
  const changesOf = (type: TaskTypeRead): TaskTypeUpdate | null => {
    const draft = drafts[type.id];
    if (!draft) {
      return null;
    }
    const payload: TaskTypeUpdate = {};
    const trimmedName = draft.name.trim();
    if (trimmedName && trimmedName !== type.name) {
      payload.name = trimmedName;
    }
    if (draft.color && draft.color !== type.color) {
      payload.color = draft.color;
    }
    if (draft.icon && draft.icon !== type.icon) {
      payload.icon = draft.icon;
    }
    return Object.keys(payload).length > 0 ? payload : null;
  };

  const hasChanges = types.some((type) => changesOf(type) !== null);

  const handleSaveAll = async () => {
    const updates = types.flatMap((type) => {
      const data = changesOf(type);
      return data ? [{ typeId: type.id, data, typeName: type.name }] : [];
    });

    if (updates.length === 0) {
      toast.info(t("taskTypes.noChanges"));
      return;
    }

    const results = await Promise.allSettled(
      updates.map(({ typeId, data }) => bulkUpdateType.mutateAsync({ typeId, data }))
    );

    let succeeded = 0;
    results.forEach((result, index) => {
      if (result.status === "fulfilled") {
        succeeded += 1;
        return;
      }
      toast.error(
        t("taskTypes.bulkUpdateError", {
          name: updates[index].typeName,
          error: getErrorMessage(result.reason, "projects:taskTypes.updateError"),
        })
      );
    });

    if (succeeded > 0) {
      toast.success(t("taskTypes.bulkUpdated", { count: succeeded }));
    }
  };

  const handleDefaultChange = (typeId: number) => {
    if (typeId === defaultType?.id) {
      return;
    }
    updateType.mutate({ typeId, data: { is_default: true } });
  };

  const openAdd = () => {
    setNewName("");
    setStartFromId(defaultType ? String(defaultType.id) : "");
    setAddOpen(true);
  };

  // Names are unique within a project, whatever their case; the server says
  // so too, but the dialog can say it before the reader presses Add.
  const trimmedNewName = newName.trim();
  const nameTaken = types.some(
    (type) => type.name.toLocaleLowerCase() === trimmedNewName.toLocaleLowerCase()
  );

  const handleAddSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!trimmedNewName || nameTaken) {
      return;
    }
    const startFrom = Number(startFromId);
    createType.mutate({
      name: trimmedNewName,
      // The new type takes the look and page of the one it starts from.
      start_from_type_id: startFromId && Number.isFinite(startFrom) ? startFrom : null,
    });
  };

  const openDelete = (type: TaskTypeRead) => {
    const fallback = defaultFallback(types, type);
    setFallbackId(fallback === null ? "" : String(fallback));
    setDeleteTarget(type);
  };

  const handleDeleteConfirm = () => {
    if (!deleteTarget || !fallbackId) {
      return;
    }
    deleteTypeMutation.mutate({
      typeId: deleteTarget.id,
      data: { fallback_type_id: Number(fallbackId) },
    });
  };

  const fallbackOptions = deleteTarget ? types.filter((type) => type.id !== deleteTarget.id) : [];
  const isOnlyType = Boolean(deleteTarget) && fallbackOptions.length === 0;

  const isLoading = typesQuery.isLoading || typesQuery.isRefetching;

  return (
    <Card>
      <CardHeader>
        <CardDescription>{t("taskTypes.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {!canManage ? (
          <p className="text-muted-foreground text-sm">{t("taskTypes.noManagePermission")}</p>
        ) : null}

        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-semibold text-sm">{t("taskTypes.existingTypes")}</h4>
            <div className="flex items-center gap-2">
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : null}
              {canManage ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleSaveAll}
                    disabled={!hasChanges || bulkUpdateType.isPending}
                  >
                    <Save className="h-4 w-4" />
                    {t("taskTypes.saveChanges")}
                  </Button>
                  <Button size="sm" onClick={openAdd} disabled={atLimit}>
                    <Plus className="h-4 w-4" />
                    {t("taskTypes.addType")}
                  </Button>
                </>
              ) : null}
            </div>
          </div>
          {canManage && atLimit ? (
            <p className="text-muted-foreground text-sm">
              {t("taskTypes.limitReached", { max: MAX_TASK_TYPES })}
            </p>
          ) : null}
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10" />
                  <TableHead className="min-w-40">{t("common:name")}</TableHead>
                  <TableHead className="w-32">{t("taskTypes.iconColumn")}</TableHead>
                  <TableHead className="w-40">{t("taskTypes.colorColumn")}</TableHead>
                  <TableHead className="w-24 text-center">{t("taskTypes.defaultColumn")}</TableHead>
                  <TableHead className="text-right">{t("common:actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
                  <SortableContext
                    items={types.map((type) => type.id)}
                    strategy={verticalListSortingStrategy}
                  >
                    {types.map((type) => (
                      <SortableTypeRow
                        key={type.id}
                        type={type}
                        draft={drafts[type.id]}
                        disabled={!canManage}
                        isDefault={type.id === defaultType?.id}
                        editPage={
                          canConfigurePages && wide
                            ? { to: editor, layout: taskTypeLayout(type.id) }
                            : null
                        }
                        onFieldChange={handleFieldChange}
                        onSetDefault={handleDefaultChange}
                        onDelete={() => openDelete(type)}
                        t={t}
                      />
                    ))}
                  </SortableContext>
                </DndContext>
                {types.length === 0 && !isLoading ? (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="py-6 text-center text-muted-foreground text-sm"
                    >
                      {t("taskTypes.noTypes")}
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
          {/* The editor says so itself too, but a row's missing button would
              otherwise be unexplained. */}
          {canConfigurePages && !wide ? (
            <p className="text-muted-foreground text-sm">{t("taskTypes.pagesOnWiderScreen")}</p>
          ) : null}
        </div>
      </CardContent>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="bg-card">
          <form onSubmit={handleAddSubmit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{t("taskTypes.addTitle")}</DialogTitle>
              <DialogDescription>{t("taskTypes.addDescription")}</DialogDescription>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor="new-task-type-name">{t("taskTypes.nameLabel")}</Label>
              <Input
                id="new-task-type-name"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                placeholder={t("taskTypes.namePlaceholder")}
                maxLength={100}
                aria-invalid={nameTaken || undefined}
                aria-describedby={nameTaken ? "new-task-type-name-error" : undefined}
                autoFocus
              />
              {nameTaken ? (
                <p id="new-task-type-name-error" className="text-destructive text-sm">
                  {t("errors:TASK_TYPE_NAME_TAKEN")}
                </p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-task-type-start-from">{t("taskTypes.startFromLabel")}</Label>
              <Select value={startFromId} onValueChange={setStartFromId}>
                <SelectTrigger id="new-task-type-start-from">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {types.map((type) => (
                    <SelectItem key={type.id} value={String(type.id)}>
                      <TaskTypeOption type={type} />
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">{t("taskTypes.startFromHint")}</p>
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setAddOpen(false)}>
                {t("common:cancel")}
              </Button>
              <Button type="submit" disabled={!trimmedNewName || nameTaken || createType.isPending}>
                {createType.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {t("taskTypes.add")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="bg-card">
          <DialogHeader>
            <DialogTitle>{t("taskTypes.deleteTitle")}</DialogTitle>
            <DialogDescription>
              {t("taskTypes.deleteDescription", { name: deleteTarget?.name })}
            </DialogDescription>
          </DialogHeader>
          {isOnlyType ? (
            <p className="text-muted-foreground text-sm">{t("taskTypes.onlyType")}</p>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="fallback-task-type">{t("taskTypes.fallbackLabel")}</Label>
              <Select value={fallbackId} onValueChange={setFallbackId}>
                <SelectTrigger id="fallback-task-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {fallbackOptions.map((option) => (
                    <SelectItem key={option.id} value={String(option.id)}>
                      <TaskTypeOption type={option} />
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              {t("common:cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteTypeMutation.isPending || isOnlyType || !fallbackId}
            >
              {deleteTypeMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("common:delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
};

interface SortableTypeRowProps {
  type: TaskTypeRead;
  draft?: TypeDraft;
  disabled: boolean;
  isDefault: boolean;
  /** Where its page is edited, or null where this reader cannot edit it here. */
  editPage: { to: string; layout: string } | null;
  onFieldChange: (typeId: number, field: DraftField, value: string) => void;
  onSetDefault: (typeId: number) => void;
  onDelete: () => void;
  t: TFunction<"projects">;
}

const SortableTypeRow = ({
  type,
  draft,
  disabled,
  isDefault,
  editPage,
  onFieldChange,
  onSetDefault,
  onDelete,
  t,
}: SortableTypeRowProps) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: type.id,
    disabled,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <TableRow ref={setNodeRef} style={style} className={cn(isDragging && "bg-muted/40")}>
      <TableCell>
        <button
          type="button"
          className="text-muted-foreground"
          {...attributes}
          {...listeners}
          disabled={disabled}
          aria-label={t("taskTypes.reorder")}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      </TableCell>
      <TableCell>
        <Input
          value={draft?.name ?? type.name}
          onChange={(event) => onFieldChange(type.id, "name", event.target.value)}
          disabled={disabled}
          maxLength={100}
          aria-label={t("taskTypes.nameLabel")}
        />
      </TableCell>
      <TableCell>
        <IconPicker
          value={(draft?.icon ?? type.icon) as IconName}
          onValueChange={(icon) => onFieldChange(type.id, "icon", icon)}
          triggerPlaceholder={t("taskTypes.iconPlaceholder")}
          disabled={disabled}
        />
      </TableCell>
      <TableCell>
        <ColorPickerPopover
          className="h-9"
          value={draft?.color ?? type.color}
          onChangeComplete={(hex) => onFieldChange(type.id, "color", hex)}
          disabled={disabled}
          triggerLabel={t("taskTypes.colorPlaceholder")}
        />
      </TableCell>
      <TableCell className="text-center">
        <Checkbox
          checked={isDefault}
          onCheckedChange={(checked) => {
            if (checked) {
              onSetDefault(type.id);
            }
          }}
          aria-label={t("taskTypes.makeDefault", { name: type.name })}
          disabled={disabled || isDefault}
        />
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          {editPage ? (
            <Button asChild variant="ghost" size="sm">
              <Link
                to={editPage.to}
                search={{ layout: editPage.layout }}
                aria-label={t("taskTypes.editPageFor", { name: type.name })}
              >
                <Pencil className="h-4 w-4" />
                {t("taskTypes.editPage")}
              </Link>
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive"
            onClick={onDelete}
            disabled={disabled}
            aria-label={t("taskTypes.deleteType", { name: type.name })}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
};
