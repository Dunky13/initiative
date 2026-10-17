import type { GroupingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { LayoutGrouping, TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ListLayout } from "@/lib/layouts/draft";
import { type FieldDef, LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import {
  groupingsOf,
  MAX_GROUPINGS,
  MAX_HIDDEN_GROUPS,
  NO_GROUP,
  type OfferedGrouping,
  taskGroupings,
} from "@/lib/layouts/grouping";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

import type { LayoutEdits } from "./LayoutEditor";

const NOT_GROUPED = "__none__";

/**
 * What a list offers to group by: every field whose values group, ticked
 * where the list offers it, in the order it offers them, and the one everyone
 * starts on. Saved with the layout.
 */
export const LayoutGroupings = ({
  layout,
  fields,
  edits,
}: {
  layout: ListLayout;
  fields: ReadonlyMap<string, FieldDef>;
  edits: LayoutEdits;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const all = useMemo(
    () => taskGroupings({ fields, statuses: [], tasks: [], t: translate }),
    [fields, translate]
  );
  const { groupings, group_by: groupBy = null } = layout.definition;
  const entries = groupingsOf(groupings);
  const byId = new Map(all.map((each) => [each.id, each]));
  const ticked = entries.flatMap((entry) => byId.get(entry.field) ?? []);
  const unticked = all.filter((each) => !entries.some((entry) => entry.field === each.id));
  const full = entries.length >= MAX_GROUPINGS;

  const change = (next: LayoutGrouping[], startsOn: string | null = groupBy) =>
    edits.changeGroupings(
      next,
      startsOn !== null && next.some((entry) => entry.field === startsOn) ? startsOn : null
    );
  // Moves the offered grouping at `index` by `by` among the ones shown.
  const move = (index: number, by: number) => {
    const from = entries.findIndex((entry) => entry.field === ticked[index].id);
    const to = entries.findIndex((entry) => entry.field === ticked[index + by].id);
    const next = [...entries];
    [next[from], next[to]] = [next[to], next[from]];
    change(next);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h3 className="font-medium text-sm">{translate("layouts:groupings.heading")}</h3>
        <p className="text-muted-foreground text-xs">{translate("layouts:groupings.help")}</p>
      </div>
      <ul className="space-y-1">
        {ticked.map((grouping, index) => (
          <li key={grouping.id} className="flex items-center gap-2">
            <Checkbox
              id={`grouping-${grouping.id}`}
              checked
              onCheckedChange={() => change(entries.filter((entry) => entry.field !== grouping.id))}
            />
            <Label htmlFor={`grouping-${grouping.id}`} className="min-w-0 flex-1 truncate">
              {grouping.label}
            </Label>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={translate("layouts:groupings.moveUp", { name: grouping.label })}
              disabled={index === 0}
              onClick={() => move(index, -1)}
            >
              <ArrowUp className="h-3.5 w-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={translate("layouts:groupings.moveDown", { name: grouping.label })}
              disabled={index === ticked.length - 1}
              onClick={() => move(index, 1)}
            >
              <ArrowDown className="h-3.5 w-3.5" />
            </Button>
          </li>
        ))}
        {unticked.map((grouping) => (
          <li key={grouping.id} className="flex items-center gap-2">
            <Checkbox
              id={`grouping-${grouping.id}`}
              checked={false}
              disabled={full}
              onCheckedChange={() => change([...entries, { field: grouping.id }])}
            />
            <Label htmlFor={`grouping-${grouping.id}`} className="min-w-0 flex-1 truncate">
              {grouping.label}
            </Label>
          </li>
        ))}
      </ul>
      {full && unticked.length > 0 ? (
        <p className="text-muted-foreground text-xs">
          {translate("layouts:groupings.full", { count: MAX_GROUPINGS })}
        </p>
      ) : null}
      <div className="space-y-1">
        <Label htmlFor="layout-group-by">{translate("layouts:groupings.startsOn")}</Label>
        <Select
          value={groupBy ?? NOT_GROUPED}
          onValueChange={(value) => change(entries, value === NOT_GROUPED ? null : value)}
        >
          <SelectTrigger id="layout-group-by">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NOT_GROUPED}>{translate("layouts:groupings.notGrouped")}</SelectItem>
            {ticked.map((grouping) => (
              <SelectItem key={grouping.id} value={grouping.id}>
                {grouping.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
};

/**
 * What the canvas is grouped by, picked from what the list offers, and the
 * groups of it, every one, hidden ones included: clicking one leaves it out
 * of the list, or puts it back.
 */
export const CanvasGrouping = ({
  offered,
  grouping: picked,
  onGroupingChange,
  tasks,
  disabled,
  onToggle,
}: {
  offered: OfferedGrouping[];
  grouping: GroupingState;
  onGroupingChange: (next: GroupingState) => void;
  tasks: TaskListRead[];
  /** A save is under way, and nothing changes until it answers. */
  disabled: boolean;
  onToggle: (id: string, key: string, shown: boolean) => void;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const active = offered.find((each) => picked.includes(each.grouping.column));
  const hiddenFull = (active?.hidden.size ?? 0) >= MAX_HIDDEN_GROUPS;
  const keys = useMemo(() => {
    if (!active) return [];
    const { grouping, hidden } = active;
    const seen = new Set<string>([...(grouping.values ?? []), ...hidden]);
    for (const task of tasks) {
      const held = grouping.keys(task);
      for (const key of held.length > 0 ? held : [NO_GROUP]) seen.add(key);
    }
    return [...seen].sort(grouping.compare);
  }, [active, tasks]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Label htmlFor="canvas-group-by" className="text-sm">
        {t("layouts:groupings.heading")}
      </Label>
      <Select
        value={active?.grouping.column ?? NOT_GROUPED}
        onValueChange={(value) => onGroupingChange(value === NOT_GROUPED ? [] : [value])}
      >
        <SelectTrigger id="canvas-group-by" className="w-44">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NOT_GROUPED}>{t("layouts:groupings.notGrouped")}</SelectItem>
          {offered.map(({ grouping }) => (
            <SelectItem key={grouping.id} value={grouping.column}>
              {grouping.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {active ? (
        <>
          <span className="text-muted-foreground text-sm">{t("layouts:groupings.shown")}</span>
          {keys.map((key) => {
            const shown = !active.hidden.has(key);
            return (
              <button
                key={key}
                type="button"
                aria-pressed={shown}
                disabled={disabled || (shown && hiddenFull)}
                onClick={() => onToggle(active.grouping.id, key, !shown)}
                className={cn(
                  "inline-flex items-center rounded-md border px-2 py-1",
                  !shown && "border-dashed opacity-50 line-through"
                )}
              >
                {active.grouping.header(key)}
              </button>
            );
          })}
          {hiddenFull ? (
            <p className="w-full text-muted-foreground text-xs">
              {t("layouts:groupings.hiddenFull", { count: MAX_HIDDEN_GROUPS })}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
};
