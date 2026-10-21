/**
 * Adding a task type: one of the ready-made ones, grouped by what they are
 * for, a blank one, or a copy of one the project already has. A ready-made
 * one brings its look, what a new task of it starts with, and its fields.
 */

import { Loader2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskTypeCreate,
  TaskTypeGalleryEntry,
  TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { TaskTypeIcon, TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTaskTypeGallery } from "@/hooks/useProjects";
import { listFormat } from "@/lib/intl";
import { cn } from "@/lib/utils";

/** Where a new type starts: nothing, a ready-made one, or one of the project's. */
type Start = { kind: "blank" } | { kind: "gallery"; key: string } | { kind: "type"; id: number };

interface TaskTypeAddDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: number;
  types: TaskTypeRead[];
  saving: boolean;
  onAdd: (data: TaskTypeCreate) => void;
}

export const TaskTypeAddDialog = ({
  open,
  onOpenChange,
  projectId,
  types,
  saving,
  onAdd,
}: TaskTypeAddDialogProps) => {
  const { t, i18n } = useTranslation(["projects", "common", "errors"]);
  const gallery = useTaskTypeGallery(projectId, { enabled: open });
  const [start, setStart] = useState<Start>({ kind: "blank" });
  const [name, setName] = useState("");

  // Opened afresh each time.
  useEffect(() => {
    if (open) {
      setStart({ kind: "blank" });
      setName("");
    }
  }, [open]);

  // Names are unique within a project, whatever their case; the server says
  // so too, but the dialog can say it before the reader presses Add.
  const trimmed = name.trim();
  const has = (candidate: string) =>
    types.some((type) => type.name.toLocaleLowerCase() === candidate.toLocaleLowerCase());
  const nameTaken = has(trimmed);

  const pick = (entry: TaskTypeGalleryEntry) => {
    setStart({ kind: "gallery", key: entry.key });
    setName(entry.name);
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!trimmed || nameTaken) return;
    onAdd({
      name: trimmed,
      ...(start.kind === "gallery" ? { gallery_key: start.key } : {}),
      // The new type takes the look and page of the one it starts from.
      ...(start.kind === "type" ? { start_from_type_id: start.id } : {}),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90dvh] flex-col bg-card">
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{t("taskTypes.addTitle")}</DialogTitle>
            <DialogDescription>{t("taskTypes.addDescription")}</DialogDescription>
          </DialogHeader>

          {/* Positioned, so the hidden inputs Radix adds to form controls
              scroll with the list instead of stretching the dialog. */}
          <div className="relative min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
            <button
              type="button"
              aria-pressed={start.kind === "blank"}
              onClick={() => setStart({ kind: "blank" })}
              className={cn(
                "w-full rounded-md border px-3 py-2 text-left",
                start.kind === "blank" ? "border-primary bg-primary/10" : "hover:bg-muted"
              )}
            >
              <span className="block font-medium text-sm">{t("taskTypes.gallery.blank")}</span>
              <span className="block text-muted-foreground text-xs">
                {t("taskTypes.gallery.blankHint")}
              </span>
            </button>

            {gallery.isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : null}
            {(gallery.data ?? []).map((group) => (
              <section key={group.key} className="space-y-2">
                <h3 className="font-semibold text-muted-foreground text-xs uppercase">
                  {group.name}
                </h3>
                <div className="grid grid-cols-fill-56/2 gap-2">
                  {group.entries.map((entry) => {
                    const chosen = start.kind === "gallery" && start.key === entry.key;
                    return (
                      <button
                        key={entry.key}
                        type="button"
                        aria-pressed={chosen}
                        onClick={() => pick(entry)}
                        className={cn(
                          "flex items-start gap-2 rounded-md border px-3 py-2 text-left",
                          chosen ? "border-primary bg-primary/10" : "hover:bg-muted"
                        )}
                      >
                        <TaskTypeIcon type={entry} className="mt-0.5 h-4 w-4" />
                        <span className="min-w-0">
                          <span className="block font-medium text-sm">
                            {entry.name}
                            {has(entry.name) ? (
                              <span className="ml-1 font-normal text-muted-foreground text-xs">
                                {t("taskTypes.gallery.alreadyHere")}
                              </span>
                            ) : null}
                          </span>
                          <span className="block text-muted-foreground text-xs">{entry.hint}</span>
                          {entry.fields.length > 0 ? (
                            <span className="block text-muted-foreground text-xs">
                              {t("taskTypes.gallery.adds", {
                                fields: listFormat(i18n.language, {
                                  type: "conjunction",
                                }).format(entry.fields.map((field) => field.name)),
                              })}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}

            <div className="space-y-2">
              <Label htmlFor="new-task-type-start-from">{t("taskTypes.startFromLabel")}</Label>
              <Select
                value={start.kind === "type" ? String(start.id) : ""}
                onValueChange={(value) => setStart({ kind: "type", id: Number(value) })}
              >
                <SelectTrigger id="new-task-type-start-from">
                  <SelectValue placeholder={t("taskTypes.startFromPlaceholder")} />
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
          </div>

          <div className="space-y-2">
            <Label htmlFor="new-task-type-name">{t("taskTypes.nameLabel")}</Label>
            <Input
              id="new-task-type-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("taskTypes.namePlaceholder")}
              maxLength={100}
              aria-invalid={nameTaken || undefined}
              aria-describedby={nameTaken ? "new-task-type-name-error" : undefined}
            />
            {nameTaken ? (
              <p id="new-task-type-name-error" className="text-destructive text-sm">
                {t("errors:TASK_TYPE_NAME_TAKEN")}
              </p>
            ) : null}
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={!trimmed || nameTaken || saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("taskTypes.add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
