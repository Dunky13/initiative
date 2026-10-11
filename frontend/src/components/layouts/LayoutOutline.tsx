import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  Columns2,
  EyeOff,
  FileText,
  GripVertical,
  LayoutList,
  ListCollapse,
  type LucideIcon,
  Plus,
  Search,
  Square,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { listLayoutLooks } from "@/components/projects/projectTasksConfig";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { LAYOUT_REGIONS } from "@/lib/layouts/detailLayout";
import {
  addableFields,
  addablePluginParts,
  cardOf,
  columnsOf,
  dropInto,
  dropOn,
  HOLDERS,
  holdsPart,
  type ListLayout,
  type NodePath,
  namedFields,
  pathKey,
  pathOf,
  removable,
  type Selection,
  sameSelection,
} from "@/lib/layouts/draft";
import { type FieldDef, LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import type { PluginOnItems } from "@/lib/layouts/plugins";
import type { LayoutNode } from "@/lib/layouts/tree";
import { cn } from "@/lib/utils";
import { localized } from "@/lib/widgets/widgetMeta";
import type { TranslateFn } from "@/types/i18n";

import type { EditableDetail } from "./details";
import type { LayoutEdits } from "./LayoutEditor";

/** A plug-in as the picker offers it: its name, and its parts by theirs. */
type PickerPlugin = {
  id: number;
  name: string;
  parts: { id: string; name: string; description?: string }[];
};

/** A part the picker offers beside the fields: a layout block, drawn as a
 *  tile with its icon and what it does, or one of the tool's panels. */
type PickerPart = {
  group: "layout" | "panel";
  label: string;
  node: LayoutNode;
  icon?: LucideIcon;
  description?: string;
};

/** The layout blocks: an accordion opens and closes under its title, a box
 *  groups what it holds, and a row puts it side by side. */
const LAYOUT_BLOCKS = {
  accordion: { icon: ListCollapse },
  box: { icon: Square },
  row: { icon: Columns2 },
} as const;

const block = (
  name: keyof typeof LAYOUT_BLOCKS,
  node: LayoutNode,
  translate: TranslateFn
): PickerPart => ({
  group: "layout",
  label: translate(`layoutEditor.blocks.${name}`),
  description: translate(`layoutEditor.blocks.${name}Help`),
  icon: LAYOUT_BLOCKS[name].icon,
  node,
});

/** A row as a card or a detail draws one: side by side, wrapping when narrow. */
const ROW: LayoutNode = { type: "stack", props: { direction: "row", wrap: true }, children: [] };

/** The title an accordion is added with, selected so typing names it. */
export const accordionTitle = (translate: TranslateFn) =>
  translate("layoutEditor.blocks.accordion");

/** What Add offers where something is added: the fields, each plug-in's
 *  parts, and the other parts. */
export type AddChoices = { fields: FieldDef[]; plugins: PickerPlugin[]; parts: PickerPart[] };

/** What a pick in the Add picker does. */
export type Adders = {
  onField: (field: FieldDef) => void;
  onPart: (plugin: number, part: string) => void;
  onNode: (node: LayoutNode) => void;
};

/** What a list layout can add: a card's fields and parts, or a table's
 *  columns. */
export const listChoices = (
  layout: ListLayout,
  fields: ReadonlyMap<string, FieldDef>,
  plugins: PickerPlugin[],
  translate: TranslateFn
): AddChoices => {
  if (layout.kind === "calendar") return { fields: [], plugins: [], parts: [] };
  const card = cardOf(layout.definition);
  const board = layout.kind === "board";
  return {
    fields: addableFields(layout, fields),
    // A table draws fields only; a card takes parts as well.
    plugins: plugins.map((plugin) => ({
      ...plugin,
      parts: board ? addablePluginParts(card, plugin.id, plugin.parts) : [],
    })),
    parts: board
      ? [
          block("row", ROW, translate),
          ...(holdsPart(card, "properties")
            ? []
            : [
                {
                  group: "panel" as const,
                  label: translate("layoutEditor.allProperties"),
                  node: { type: "properties" },
                },
              ]),
        ]
      : [],
  };
};

/** What a detail can add: the layout blocks, its fields not placed, its own
 *  parts once each, and plug-in parts. */
export const detailChoices = (
  detail: LayoutNode,
  { spec, words }: EditableDetail,
  fields: ReadonlyMap<string, FieldDef>,
  plugins: PickerPlugin[],
  translate: TranslateFn
): AddChoices => {
  const named = namedFields(detail);
  return {
    fields: [...fields.values()].filter(
      (field) =>
        !named.has(field.id) &&
        ((field.source === "builtin" && spec.detailFields.has(field.id)) ||
          field.source === "plugin")
    ),
    plugins: plugins.map((plugin) => ({
      ...plugin,
      parts: addablePluginParts(detail, plugin.id, plugin.parts),
    })),
    parts: [
      block(
        "accordion",
        { type: "section", props: { title: accordionTitle(translate) }, children: [] },
        translate
      ),
      block("box", { type: "section", children: [] }, translate),
      block("row", ROW, translate),
      ...spec.ownParts
        .filter((type) => !holdsPart(detail, type))
        .map((type) => ({
          group: "panel" as const,
          label: translate(`${words.parts}.parts.${type}`),
          node: { type },
        })),
      ...(holdsPart(detail, "properties")
        ? []
        : [
            {
              group: "panel" as const,
              label: translate("layoutEditor.allProperties"),
              node: { type: "properties" },
            },
          ]),
    ],
  };
};

/** Rows that stay where they are: a detail's regions. */
const FIXED = new Set<string>(LAYOUT_REGIONS);

const INTO = "into:";

const usePickerPlugins = (plugins: ReadonlyMap<number, PluginOnItems>): PickerPlugin[] => {
  const { i18n } = useTranslation();
  return [...plugins.values()].map((plugin) => ({
    id: plugin.id,
    name: plugin.name,
    parts: [...plugin.parts.values()].map((part) => ({
      id: part.id,
      name: localized(part.name, i18n.language) ?? part.id,
      description: localized(part.description, i18n.language),
    })),
  }));
};

/** What a part is called in the outline and the settings. */
export const usePartLabel = (
  fields: ReadonlyMap<string, FieldDef>,
  plugins: ReadonlyMap<number, PluginOnItems>,
  /** Where the names of the open detail's own parts are. */
  partWords = "layoutEditor"
) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const pickerPlugins = usePickerPlugins(plugins);
  const labelOf = (field: FieldDef) =>
    field.source === "builtin" ? translate(field.label) : field.label;
  const partLabel = (node: LayoutNode): string => {
    switch (node.type) {
      case "card":
        return translate("layoutEditor.card");
      case "stack":
        return node.props?.direction === "row"
          ? translate("layoutEditor.row")
          : translate("layoutEditor.group");
      // An accordion by its title; a box by what it starts with.
      case "section": {
        if (typeof node.props?.title === "string" && node.props.title) return node.props.title;
        const [first] = node.children ?? [];
        return first
          ? translate("layoutEditor.boxWith", { name: partLabel(first) })
          : translate("layoutEditor.blocks.box");
      }
      case "properties":
        return translate("layoutEditor.allProperties");
      case "plugin": {
        const plugin = pickerPlugins.find((each) => each.id === Number(node.props?.plugin));
        const part = plugin?.parts.find((each) => each.id === node.props?.part);
        return part?.name ?? translate("layoutEditor.missingPart");
      }
      case "field": {
        const field = fields.get(String(node.props?.field));
        return field ? labelOf(field) : translate("layoutEditor.missingField");
      }
      case "header":
      case "main":
      case "side":
        return translate(`layoutEditor.parts.${node.type}`);
      default:
        return translate(`${partWords}.parts.${node.type}`);
    }
  };
  return { labelOf, partLabel, pickerPlugins };
};

const useOutlineSensors = () =>
  useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

/**
 * What the view is made of, as a list beside the canvas: the view itself,
 * then a board's card part by part or a table's columns in order. A row is
 * dragged to move it, into another group as well, hidden from its own row,
 * and selected to change it. Add offers what is not there yet, under where it
 * comes from.
 */
export const ListLayoutOutline = ({
  layout: open,
  fields,
  plugins,
  choices,
  adders,
  selection,
  edits,
  locked,
}: {
  layout: ListLayout;
  fields: ReadonlyMap<string, FieldDef>;
  plugins: ReadonlyMap<number, PluginOnItems>;
  /** What Add offers, and what a pick does. */
  choices: AddChoices;
  adders: Adders;
  selection: Selection;
  edits: LayoutEdits;
  /** A save is under way, and nothing changes until it answers. */
  locked: boolean;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const sensors = useOutlineSensors();
  const { labelOf, partLabel } = usePartLabel(fields, plugins);
  const { definition, kind: layout } = open;
  const card = cardOf(definition);
  const columns = columnsOf(definition);
  const isSelected = (other: Selection) => sameSelection(selection, other);

  const onColumnDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    edits.moveColumn(columns.indexOf(String(active.id)), columns.indexOf(String(over.id)));
  };

  return (
    <nav aria-label={translate("layoutEditor.outline")} className="flex h-full flex-col">
      <div className="flex-1 space-y-1 overflow-y-auto p-3">
        <OutlineRow
          id="layout"
          depth={0}
          label={translate(listLayoutLooks[layout].labelKey)}
          icon={<LayoutList className="h-4 w-4" aria-hidden="true" />}
          selected={isSelected({ kind: "layout" })}
          onSelect={() => edits.select({ kind: "layout" })}
          fixed
        />
        {layout === "board" ? (
          <>
            <OutlineRow
              id="card"
              depth={1}
              label={partLabel(card)}
              selected={isSelected({ kind: "part", path: [] })}
              onSelect={() => edits.select({ kind: "part", path: [] })}
              fixed
            />
            <PartTree
              root={card}
              depth={2}
              partLabel={partLabel}
              hideAction={(node) =>
                removable(node, fields)
                  ? translate("layoutEditor.hide", { name: partLabel(node) })
                  : null
              }
              selection={selection}
              edits={edits}
              locked={locked}
            />
          </>
        ) : null}
        {layout === "table" ? (
          <DndContext sensors={sensors} onDragEnd={onColumnDragEnd}>
            <p className="px-2 pt-2 font-medium text-muted-foreground text-xs">
              {translate("layoutEditor.columns")}
            </p>
            <SortableContext items={columns} strategy={verticalListSortingStrategy}>
              {columns.map((id) => {
                const field = fields.get(id);
                const label = field ? labelOf(field) : translate("layoutEditor.missingField");
                return (
                  <OutlineRow
                    key={id}
                    id={id}
                    depth={1}
                    label={label}
                    selected={isSelected({ kind: "column", field: id })}
                    onSelect={() => edits.select({ kind: "column", field: id })}
                    // A table always has its title.
                    hide={
                      field?.hideable === false
                        ? undefined
                        : {
                            label: translate("layoutEditor.hide", { name: label }),
                            run: () => edits.removeColumn(id),
                          }
                    }
                    locked={locked}
                  />
                );
              })}
            </SortableContext>
          </DndContext>
        ) : null}
      </div>
      {layout === "calendar" ? null : (
        <div className="border-t p-3">
          <AddPicker choices={choices} labelOf={labelOf} adders={adders} locked={locked} />
        </div>
      )}
    </nav>
  );
};

/**
 * A task's detail as a list beside the canvas: the layout, its header, main and
 * side with their parts. A row is dragged to move it, into another region or
 * section as well; a part taken off is hidden, and Add puts it back.
 */
export const DetailLayoutOutline = ({
  detail,
  of,
  fields,
  plugins,
  choices,
  adders,
  selection,
  edits,
  locked,
}: {
  /** The detail as one tree: the layout, holding its header, main and side. */
  detail: LayoutNode;
  /** Which kind of detail it is. */
  of: EditableDetail;
  fields: ReadonlyMap<string, FieldDef>;
  plugins: ReadonlyMap<number, PluginOnItems>;
  choices: AddChoices;
  adders: Adders;
  selection: Selection;
  edits: LayoutEdits;
  locked: boolean;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const { labelOf, partLabel } = usePartLabel(fields, plugins, of.words.parts);
  return (
    <nav aria-label={translate("layoutEditor.outline")} className="flex h-full flex-col">
      <div className="flex-1 space-y-1 overflow-y-auto p-3">
        <OutlineRow
          id="layout"
          depth={0}
          label={translate(of.words.name)}
          icon={<FileText className="h-4 w-4" aria-hidden="true" />}
          selected={sameSelection(selection, { kind: "layout" })}
          onSelect={() => edits.select({ kind: "layout" })}
          fixed
        />
        <PartTree
          root={detail}
          depth={1}
          partLabel={partLabel}
          hideAction={(node) =>
            FIXED.has(node.type) || !removable(node, fields)
              ? null
              : translate("layoutEditor.hide", { name: partLabel(node) })
          }
          selection={selection}
          edits={edits}
          locked={locked}
        />
      </div>
      <div className="border-t p-3">
        <AddPicker choices={choices} labelOf={labelOf} adders={adders} locked={locked} />
      </div>
    </nav>
  );
};

/**
 * A tree's parts as rows under its root, each group's below it. A row is
 * dragged onto another to take its place, in its own group or another, or
 * onto the slot at the end of a group, which each group shows while a row is
 * dragged (and an empty one always).
 */
const PartTree = ({
  root,
  depth,
  partLabel,
  hideAction,
  selection,
  edits,
  locked,
}: {
  root: LayoutNode;
  depth: number;
  partLabel: (node: LayoutNode) => string;
  /** What hiding the part is called, or null when it stays. */
  hideAction: (node: LayoutNode) => string | null;
  selection: Selection;
  edits: LayoutEdits;
  locked: boolean;
}) => {
  const sensors = useOutlineSensors();
  const [dragging, setDragging] = useState(false);

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setDragging(false);
    if (!over) return;
    const from = pathOf(String(active.id));
    const target = String(over.id);
    const to = target.startsWith(INTO)
      ? dropInto(root, from, pathOf(target.slice(INTO.length)))
      : dropOn(from, pathOf(target));
    if (to && pathKey(to) !== pathKey(from)) edits.movePart(from, to);
  };

  const rows = (parent: LayoutNode, parentPath: NodePath, at: number): ReactNode => {
    const children = parent.children ?? [];
    const keys = children.map((_, index) => pathKey([...parentPath, index]));
    return (
      <SortableContext
        items={keys.filter((_, index) => !FIXED.has(children[index].type))}
        strategy={verticalListSortingStrategy}
      >
        {children.map((child, index) => {
          const path = [...parentPath, index];
          const hide = hideAction(child);
          return (
            <div key={keys[index]}>
              <OutlineRow
                id={keys[index]}
                depth={at}
                label={partLabel(child)}
                selected={sameSelection(selection, { kind: "part", path })}
                onSelect={() => edits.select({ kind: "part", path })}
                hide={hide ? { label: hide, run: () => edits.removePart(path) } : undefined}
                fixed={FIXED.has(child.type)}
                locked={locked}
              />
              {HOLDERS.has(child.type) ? (
                <>
                  {rows(child, path, at + 1)}
                  {dragging || !child.children?.length ? (
                    <EndSlot
                      id={`${INTO}${keys[index]}`}
                      depth={at + 1}
                      empty={!child.children?.length}
                    />
                  ) : null}
                </>
              ) : null}
            </div>
          );
        })}
      </SortableContext>
    );
  };

  return (
    <DndContext
      sensors={sensors}
      onDragStart={() => setDragging(true)}
      onDragEnd={onDragEnd}
      onDragCancel={() => setDragging(false)}
    >
      {rows(root, [], depth)}
      {dragging && HOLDERS.has(root.type) ? (
        <EndSlot id={INTO} depth={depth} empty={false} />
      ) : null}
    </DndContext>
  );
};

/** Where a dragged row goes to the end of a group. */
const EndSlot = ({ id, depth, empty }: { id: string; depth: number; empty: boolean }) => {
  const { t } = useTranslation("projects");
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "rounded-md border border-transparent border-dashed py-1 pr-1 text-muted-foreground text-xs",
        isOver && "border-primary bg-muted"
      )}
      style={{ paddingLeft: `${depth * 0.75 + 1.75}rem` }}
    >
      {empty ? t("layoutEditor.empty") : t("layoutEditor.dropHere")}
    </div>
  );
};

const OutlineRow = ({
  id,
  depth,
  label,
  icon,
  selected,
  onSelect,
  hide,
  fixed = false,
  locked = false,
}: {
  id: string;
  depth: number;
  label: string;
  icon?: ReactNode;
  selected: boolean;
  onSelect: () => void;
  /** Absent: the row cannot be hidden. */
  hide?: { label: string; run: () => void };
  /** It has no place to move to. */
  fixed?: boolean;
  locked?: boolean;
}) => {
  const { t } = useTranslation("projects");
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled: fixed || locked,
  });
  return (
    <div
      ref={fixed ? undefined : setNodeRef}
      style={fixed ? undefined : { transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "group flex items-center gap-1 rounded-md pr-1 text-sm",
        selected ? "bg-accent text-accent-foreground" : "hover:bg-muted",
        isDragging && "opacity-60"
      )}
    >
      <span aria-hidden="true" style={{ width: `${depth * 0.75}rem` }} className="shrink-0" />
      {fixed ? (
        <span className="flex h-7 w-6 items-center justify-center text-muted-foreground">
          {icon}
        </span>
      ) : (
        <button
          type="button"
          className="flex h-7 w-6 cursor-grab items-center justify-center text-muted-foreground disabled:cursor-not-allowed"
          aria-label={t("layoutEditor.move", { name: label })}
          disabled={locked}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      )}
      <button
        type="button"
        className="min-w-0 flex-1 truncate py-1 text-left"
        aria-pressed={selected}
        onClick={onSelect}
      >
        {label}
      </button>
      {hide ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
          aria-label={hide.label}
          disabled={locked}
          onClick={hide.run}
        >
          <EyeOff className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  );
};

/** Whether `text` holds what was searched for. */
const matches = (text: string, query: string) => !query || text.toLocaleLowerCase().includes(query);

/** What can be added, shown as things rather than ids: the layout blocks as
 *  tiles, then every field in one list, each with where it comes from, then
 *  the panels, the tool's and each plug-in's. A search narrows all of it.
 *  Opened from the outline's Add, or from a point on the canvas. */
export const AddPicker = ({
  choices: { fields, plugins, parts },
  labelOf,
  adders: { onField, onPart, onNode },
  locked,
  trigger,
  onOpenChange,
}: {
  choices: AddChoices;
  labelOf: (field: FieldDef) => string;
  adders: Adders;
  locked: boolean;
  /** In place of the outline's Add button. */
  trigger?: ReactNode;
  onOpenChange?: (open: boolean) => void;
}) => {
  const { t } = useTranslation("projects");
  const [open, setOpenState] = useState(false);
  const [search, setSearch] = useState("");
  const setOpen = (next: boolean) => {
    setOpenState(next);
    if (!next) setSearch("");
    onOpenChange?.(next);
  };
  const query = search.trim().toLocaleLowerCase();
  const pluginName = new Map(plugins.map((plugin) => [plugin.id, plugin.name]));
  const sourceOf = (field: FieldDef) =>
    field.source === "plugin"
      ? (pluginName.get(field.plugin?.install ?? 0) ?? "")
      : t(field.source === "property" ? "layoutEditor.fromProperty" : "layoutEditor.builtIn");
  const blocks = parts.filter((part) => part.group === "layout" && matches(part.label, query));
  const shownFields = fields.filter((field) => matches(labelOf(field), query));
  const panels = parts.filter((part) => part.group === "panel" && matches(part.label, query));
  const pluginPanels = plugins
    .map((plugin) => ({
      ...plugin,
      parts: plugin.parts.filter((part) => matches(part.name, query)),
    }))
    .filter((plugin) => plugin.parts.length > 0);
  const offers =
    parts.length + fields.length + plugins.reduce((count, each) => count + each.parts.length, 0);
  const found = blocks.length + shownFields.length + panels.length + pluginPanels.length;
  const pick = (run: () => void) => {
    run();
    setOpen(false);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={offers === 0 || locked}>
        {trigger ?? (
          <Button type="button" variant="outline" size="sm" className="w-full">
            <Plus className="h-4 w-4" />
            {t("layoutEditor.add")}
          </Button>
        )}
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="max-h-[28rem] w-96 overflow-y-auto p-2"
        aria-label={t("layoutEditor.add")}
      >
        <div className="relative mb-2">
          <Search
            className="absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("layoutEditor.search")}
            aria-label={t("layoutEditor.search")}
            className="pl-8"
            autoFocus
          />
        </div>
        {blocks.length > 0 ? (
          <PickerGroup heading={t("layoutEditor.layoutParts")}>
            <div className="grid grid-cols-3 gap-1">
              {blocks.map((part) => {
                const Icon = part.icon;
                return (
                  <button
                    key={part.label}
                    type="button"
                    className="flex flex-col items-center gap-1 rounded-md border p-2 text-center text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
                    title={part.description}
                    onClick={() => pick(() => onNode(part.node))}
                  >
                    {Icon ? (
                      <Icon className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
                    ) : null}
                    <span>{part.label}</span>
                    {part.description ? (
                      <span className="text-muted-foreground text-xs">{part.description}</span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </PickerGroup>
        ) : null}
        {shownFields.length > 0 ? (
          <PickerGroup heading={t("layoutEditor.fieldsGroup")}>
            {shownFields.map((field) => {
              const Icon = field.icon;
              return (
                <PickerItem
                  key={field.id}
                  note={sourceOf(field)}
                  onClick={() => pick(() => onField(field))}
                >
                  {Icon ? (
                    <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  ) : null}
                  {labelOf(field)}
                </PickerItem>
              );
            })}
          </PickerGroup>
        ) : null}
        {panels.length > 0 ? (
          <PickerGroup heading={t("layoutEditor.panels")}>
            {panels.map((part) => (
              <PickerItem key={part.label} onClick={() => pick(() => onNode(part.node))}>
                {part.label}
              </PickerItem>
            ))}
          </PickerGroup>
        ) : null}
        {pluginPanels.map((plugin) => (
          <PickerGroup key={`plugin:${plugin.id}`} heading={plugin.name}>
            {plugin.parts.map((part) => (
              <PickerItem
                key={`part:${part.id}`}
                description={part.description}
                onClick={() => pick(() => onPart(plugin.id, part.id))}
              >
                {part.name}
              </PickerItem>
            ))}
          </PickerGroup>
        ))}
        {found === 0 ? (
          <p className="px-2 py-3 text-muted-foreground text-sm">{t("layoutEditor.noMatches")}</p>
        ) : null}
      </PopoverContent>
    </Popover>
  );
};

const PickerGroup = ({ heading, children }: { heading: string; children: ReactNode }) => (
  <div className="py-1">
    <p className="px-2 pb-1 font-medium text-muted-foreground text-xs">{heading}</p>
    {children}
  </div>
);

const PickerItem = ({
  description,
  note,
  onClick,
  children,
}: {
  description?: string;
  /** Where it comes from, set apart at the end of the row. */
  note?: string;
  onClick: () => void;
  children: ReactNode;
}) => (
  <button
    type="button"
    className="flex w-full flex-col items-start rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
    onClick={onClick}
  >
    <span className="flex w-full items-center gap-2">
      {children}
      {note ? <span className="ml-auto truncate text-muted-foreground text-xs">{note}</span> : null}
    </span>
    {description ? <span className="text-muted-foreground text-xs">{description}</span> : null}
  </button>
);
