/**
 * A person's home page: which widgets it holds and where each one sits.
 *
 * The layout is personal and spans communities, so it is one of the reader's
 * own preferences (one per view, see `views.ts`) rather than a row in any
 * community. It holds
 * nothing but placement and each widget's few options; what a widget shows is
 * read live when it renders.
 *
 * The grid is the dashboard canvas's: twelve columns, each widget carrying its
 * own `{x, y, w, h}`. A stored layout is read through {@link readHomeLayout},
 * which drops what this build no longer knows rather than failing on it.
 */

import { HOME_WIDGET_SIZES, HOME_WIDGET_TYPES, type HomeWidgetType } from "./widgetTypes";

export const HOME_LAYOUT_VERSION = 1;
export const HOME_GRID_COLUMNS = 12;
/** More than anyone arranges on one page, and well inside the preference's size. */
export const MAX_HOME_WIDGETS = 24;
/** The preference store refuses a value over 16 KiB; this leaves room for the envelope. */
export const MAX_HOME_LAYOUT_BYTES = 15 * 1024;
/** The tallest a widget may be, in rows. */
const MAX_ROWS = 40;

export type HomeWidgetOptions = Record<string, unknown>;

export interface HomeGrid {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface HomeWidget {
  id: string;
  type: HomeWidgetType;
  grid: HomeGrid;
  options?: HomeWidgetOptions;
}

export interface HomeLayout {
  version: typeof HOME_LAYOUT_VERSION;
  /** The starting layout this one came from, for the picker to mark. */
  preset?: string;
  widgets: HomeWidget[];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const isWidgetType = (value: unknown): value is HomeWidgetType =>
  typeof value === "string" && (HOME_WIDGET_TYPES as readonly string[]).includes(value);

const whole = (value: unknown, fallback: number) =>
  typeof value === "number" && Number.isFinite(value) ? Math.round(value) : fallback;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/** A grid that fits the canvas and the widget's own minimum. */
export const clampGrid = (type: HomeWidgetType, grid: Partial<HomeGrid>): HomeGrid => {
  const size = HOME_WIDGET_SIZES[type];
  const w = clamp(whole(grid.w, size.w), size.minW, HOME_GRID_COLUMNS);
  const h = clamp(whole(grid.h, size.h), size.minH, MAX_ROWS);
  const x = clamp(whole(grid.x, 0), 0, HOME_GRID_COLUMNS - w);
  const y = Math.max(whole(grid.y, 0), 0);
  return { x, y, w, h };
};

/**
 * A stored layout as this build can draw it, or `null` when there is none.
 *
 * A widget type a later build added, and then this one does not know, is left
 * out rather than breaking the page; so is a second copy of a widget that may
 * appear only once.
 */
export const readHomeLayout = (raw: unknown): HomeLayout | null => {
  if (!isRecord(raw) || !Array.isArray(raw.widgets)) return null;
  const seen = new Set<string>();
  const singles = new Set<HomeWidgetType>();
  const widgets: HomeWidget[] = [];
  for (const item of raw.widgets) {
    if (widgets.length >= MAX_HOME_WIDGETS) break;
    if (!isRecord(item) || !isWidgetType(item.type)) continue;
    const id = typeof item.id === "string" && item.id ? item.id : null;
    if (!id || seen.has(id)) continue;
    if (HOME_WIDGET_SIZES[item.type].single) {
      if (singles.has(item.type)) continue;
      singles.add(item.type);
    }
    seen.add(id);
    widgets.push({
      id,
      type: item.type,
      grid: clampGrid(item.type, isRecord(item.grid) ? item.grid : {}),
      ...(isRecord(item.options) ? { options: item.options } : {}),
    });
  }
  return {
    version: HOME_LAYOUT_VERSION,
    ...(typeof raw.preset === "string" ? { preset: raw.preset } : {}),
    widgets,
  };
};

/** Top to bottom, then left to right: the order a narrow screen stacks them in. */
export const readingOrder = (widgets: readonly HomeWidget[]): HomeWidget[] =>
  [...widgets].sort((a, b) => a.grid.y - b.grid.y || a.grid.x - b.grid.x);

/** Whether the layout still fits the preference it is saved in. */
export const layoutFits = (layout: HomeLayout): boolean =>
  new TextEncoder().encode(JSON.stringify(layout)).length <= MAX_HOME_LAYOUT_BYTES;

/** Whether one more of this widget is allowed on the page. */
export const canAddWidget = (layout: HomeLayout, type: HomeWidgetType): boolean =>
  layout.widgets.length < MAX_HOME_WIDGETS &&
  !(HOME_WIDGET_SIZES[type].single && layout.widgets.some((widget) => widget.type === type));

const newWidgetId = (type: HomeWidgetType, taken: ReadonlySet<string>) => {
  for (let n = 1; ; n++) {
    const id = n === 1 ? type : `${type}-${n}`;
    if (!taken.has(id)) return id;
  }
};

/** A widget at its default size, placed under everything already there. */
export const addWidget = (
  layout: HomeLayout,
  type: HomeWidgetType,
  options?: HomeWidgetOptions
): HomeLayout => {
  if (!canAddWidget(layout, type)) return layout;
  const size = HOME_WIDGET_SIZES[type];
  const bottom = layout.widgets.reduce(
    (max, widget) => Math.max(max, widget.grid.y + widget.grid.h),
    0
  );
  const widget: HomeWidget = {
    id: newWidgetId(type, new Set(layout.widgets.map((each) => each.id))),
    type,
    grid: { x: 0, y: bottom, w: size.w, h: size.h },
    ...(options ? { options } : {}),
  };
  return { ...layout, preset: undefined, widgets: [...layout.widgets, widget] };
};

export const removeWidget = (layout: HomeLayout, id: string): HomeLayout => ({
  ...layout,
  preset: undefined,
  widgets: layout.widgets.filter((widget) => widget.id !== id),
});

export const setWidgetOptions = (
  layout: HomeLayout,
  id: string,
  options: HomeWidgetOptions
): HomeLayout => ({
  ...layout,
  widgets: layout.widgets.map((widget) => (widget.id === id ? { ...widget, options } : widget)),
});

/** New positions from the grid, keyed by widget id; anything not named stays put. */
export const applyGrid = (
  layout: HomeLayout,
  placed: readonly ({ i: string } & HomeGrid)[]
): HomeLayout => {
  const byId = new Map(placed.map((item) => [item.i, item]));
  const widgets = layout.widgets.map((widget) => {
    const item = byId.get(widget.id);
    return item ? { ...widget, grid: clampGrid(widget.type, item) } : widget;
  });
  const same = widgets.every((widget, index) => {
    const before = layout.widgets[index]?.grid;
    return (
      before &&
      before.x === widget.grid.x &&
      before.y === widget.grid.y &&
      before.w === widget.grid.w &&
      before.h === widget.grid.h
    );
  });
  return same ? layout : { ...layout, preset: undefined, widgets };
};

/**
 * One step up or down the stacked order, for a narrow screen where there is
 * no grid to drag on. The widget trades places with its neighbour, each taking
 * the other's spot, so the wide arrangement changes by exactly that swap.
 */
export const moveWidget = (layout: HomeLayout, id: string, step: -1 | 1): HomeLayout => {
  const order = readingOrder(layout.widgets);
  const index = order.findIndex((widget) => widget.id === id);
  const self = order[index];
  const other = order[index + step];
  if (!self || !other) return layout;
  const into = (widget: HomeWidget, spot: HomeWidget): HomeWidget => ({
    ...widget,
    grid: clampGrid(widget.type, { ...widget.grid, x: spot.grid.x, y: spot.grid.y }),
  });
  const movedSelf = into(self, other);
  const movedOther = into(other, self);
  // Clamping a wide widget into a narrower one's column can tie the two on a
  // row in the old order; the one that moved down then drops a row. The grid
  // settles any overlap that leaves the next time it is drawn wide.
  const [earlier, later] = step === -1 ? [movedSelf, movedOther] : [movedOther, movedSelf];
  if (readingOrder([later, earlier])[0] === later) {
    later.grid = { ...later.grid, y: earlier.grid.y + 1 };
  }
  return {
    ...layout,
    preset: undefined,
    widgets: layout.widgets.map((widget) =>
      widget.id === self.id ? movedSelf : widget.id === other.id ? movedOther : widget
    ),
  };
};
