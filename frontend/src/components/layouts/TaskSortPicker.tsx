import { useTranslation } from "react-i18next";

import type { SortField } from "@/api/generated/initiativeAPI.schemas";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { type FieldDef, LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import type { TranslateFn } from "@/types/i18n";

/** What a list of tasks can be sorted by, as the task list names it, and the
 *  field (or key) that names it for a reader. */
const SORTS: readonly { field: string; label: { field: string } | { key: string } }[] = [
  { field: "title", label: { field: "title" } },
  { field: "due_date", label: { field: "dueDate" } },
  { field: "start_date", label: { field: "startDate" } },
  { field: "priority", label: { field: "priority" } },
  { field: "status_position", label: { key: "tasks:columns.status" } },
  { field: "tag_name", label: { field: "tags" } },
];

/** Picked in the sort select for "no sort of its own". */
const NO_SORT = "none";

/** One field to sort a list of tasks by, and which way — what a preset and a
 *  task embed keep. `fields` names the fields as the list's columns do. */
export function TaskSortPicker({
  value,
  onChange,
  fields,
}: {
  value: SortField | null;
  onChange: (next: SortField | null) => void;
  fields: ReadonlyMap<string, FieldDef>;
}) {
  const { t } = useTranslation([...LAYOUT_NAMESPACES, "common"]);
  const translate = t as TranslateFn;
  const sortLabel = (label: (typeof SORTS)[number]["label"]) =>
    "key" in label
      ? translate(label.key)
      : translate(fields.get(label.field)?.label ?? label.field);

  return (
    <div className="grid-cols-pair grid gap-4">
      <div className="space-y-2">
        <Label htmlFor="task-sort">{translate("layoutEditor.presets.sortBy")}</Label>
        <Select
          value={value?.field ?? NO_SORT}
          onValueChange={(field) =>
            onChange(field === NO_SORT ? null : { field, dir: value?.dir ?? "asc" })
          }
        >
          <SelectTrigger id="task-sort">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_SORT}>{translate("layoutEditor.presets.noSort")}</SelectItem>
            {SORTS.map(({ field, label }) => (
              <SelectItem key={field} value={field}>
                {sortLabel(label)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex items-center gap-2 self-end pb-2">
        <Switch
          id="task-sort-descending"
          checked={value?.dir === "desc"}
          disabled={!value}
          onCheckedChange={(checked) =>
            value && onChange({ ...value, dir: checked ? "desc" : "asc" })
          }
        />
        <Label htmlFor="task-sort-descending">{translate("layoutEditor.presets.descending")}</Label>
      </div>
    </div>
  );
}
