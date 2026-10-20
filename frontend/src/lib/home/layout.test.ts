import { describe, expect, it } from "vitest";

import {
  addWidget,
  applyGrid,
  canAddWidget,
  HOME_GRID_COLUMNS,
  HOME_LAYOUT_VERSION,
  type HomeLayout,
  layoutFits,
  MAX_HOME_WIDGETS,
  moveWidget,
  readHomeLayout,
  readingOrder,
  removeWidget,
  setViewBanner,
  setWidgetOptions,
} from "./layout";
import { HOME_WIDGET_SIZES } from "./widgetTypes";

const layoutOf = (...widgets: HomeLayout["widgets"]): HomeLayout => ({
  version: HOME_LAYOUT_VERSION,
  widgets,
});

describe("readHomeLayout", () => {
  it("has nothing to read from a value that is not a layout", () => {
    expect(readHomeLayout(null)).toBeNull();
    expect(readHomeLayout("tasks")).toBeNull();
    expect(readHomeLayout({ widgets: "nope" })).toBeNull();
  });

  it("drops what this build cannot draw rather than failing on it", () => {
    const layout = readHomeLayout({
      version: 1,
      widgets: [
        { id: "tasks", type: "tasks", grid: { x: 0, y: 0, w: 12, h: 10 } },
        // A widget a later build added.
        { id: "weather", type: "weather", grid: { x: 0, y: 10, w: 4, h: 4 } },
        // No id, and a repeated one.
        { type: "clock", grid: { x: 0, y: 0, w: 4, h: 4 } },
        { id: "tasks", type: "clock", grid: { x: 0, y: 0, w: 4, h: 4 } },
        // A second copy of a widget that may appear once.
        { id: "tasks-2", type: "tasks", grid: { x: 0, y: 20, w: 12, h: 10 } },
        "garbage",
      ],
    });
    expect(layout?.widgets.map((widget) => widget.id)).toEqual(["tasks"]);
  });

  it("fits every grid to the canvas and the widget's minimum", () => {
    const layout = readHomeLayout({
      widgets: [
        { id: "a", type: "clock", grid: { x: 10, y: -3, w: 6, h: 1 } },
        { id: "b", type: "clock", grid: { x: "left", y: 2.6 } },
      ],
    });
    const [a, b] = layout?.widgets ?? [];
    expect(a.grid).toEqual({
      x: HOME_GRID_COLUMNS - 6,
      y: 0,
      w: 6,
      h: HOME_WIDGET_SIZES.clock.minH,
    });
    expect(b.grid).toEqual({
      x: 0,
      y: 3,
      w: HOME_WIDGET_SIZES.clock.w,
      h: HOME_WIDGET_SIZES.clock.h,
    });
  });

  it("keeps no more widgets than a page holds", () => {
    const widgets = Array.from({ length: MAX_HOME_WIDGETS + 5 }, (_, i) => ({
      id: `n${i}`,
      type: "clock",
      grid: { x: 0, y: i * 4, w: 4, h: 4 },
    }));
    expect(readHomeLayout({ widgets })?.widgets).toHaveLength(MAX_HOME_WIDGETS);
  });
});

describe("addWidget", () => {
  it("places a new widget under everything, at its default size, with an id of its own", () => {
    const start = layoutOf(
      { id: "clock", type: "clock", grid: { x: 0, y: 0, w: 4, h: 5 } },
      { id: "focus", type: "focus", grid: { x: 4, y: 2, w: 8, h: 5 } }
    );
    const next = addWidget(start, "clock");
    const added = next.widgets.at(-1);
    expect(added?.id).toBe("clock-2");
    expect(added?.grid).toEqual({
      x: 0,
      y: 7,
      w: HOME_WIDGET_SIZES.clock.w,
      h: HOME_WIDGET_SIZES.clock.h,
    });
  });

  it("adds a once-only widget only once", () => {
    const start = layoutOf({ id: "tasks", type: "tasks", grid: { x: 0, y: 0, w: 12, h: 10 } });
    expect(canAddWidget(start, "tasks")).toBe(false);
    expect(addWidget(start, "tasks")).toBe(start);
    expect(canAddWidget(start, "clock")).toBe(true);
  });

  it("stops marking the page as a starting layout once it changes", () => {
    const start: HomeLayout = { ...layoutOf(), preset: "tasks" };
    expect(addWidget(start, "clock").preset).toBeUndefined();
    expect(removeWidget(start, "x").preset).toBeUndefined();
  });
});

describe("applyGrid", () => {
  const start = layoutOf(
    { id: "a", type: "clock", grid: { x: 0, y: 0, w: 4, h: 5 } },
    { id: "b", type: "clock", grid: { x: 4, y: 0, w: 4, h: 5 } }
  );

  it("is the same layout when nothing moved, so nothing is saved", () => {
    expect(
      applyGrid(start, [
        { i: "a", x: 0, y: 0, w: 4, h: 5 },
        { i: "b", x: 4, y: 0, w: 4, h: 5 },
      ])
    ).toBe(start);
  });

  it("takes the grid's positions for the widgets it names", () => {
    const next = applyGrid(start, [{ i: "b", x: 0, y: 5, w: 6, h: 4 }]);
    expect(next.widgets.map((widget) => widget.grid)).toEqual([
      { x: 0, y: 0, w: 4, h: 5 },
      { x: 0, y: 5, w: 6, h: 4 },
    ]);
  });
});

describe("moveWidget", () => {
  const stack = layoutOf(
    { id: "greeting", type: "greeting", grid: { x: 0, y: 0, w: 12, h: 2 } },
    { id: "clock", type: "clock", grid: { x: 0, y: 2, w: 4, h: 5 } },
    { id: "comingUp", type: "comingUp", grid: { x: 4, y: 2, w: 8, h: 8 } }
  );
  const order = (layout: HomeLayout) => readingOrder(layout.widgets).map((widget) => widget.id);

  it("trades places with the neighbour in the stacked order", () => {
    expect(order(moveWidget(stack, "comingUp", -1))).toEqual(["greeting", "comingUp", "clock"]);
    expect(order(moveWidget(stack, "greeting", 1))).toEqual(["clock", "greeting", "comingUp"]);
  });

  it("goes nowhere past either end", () => {
    expect(moveWidget(stack, "greeting", -1)).toBe(stack);
    expect(moveWidget(stack, "comingUp", 1)).toBe(stack);
  });

  it("keeps the new order when a wide widget cannot take a narrow one's column", () => {
    const side = layoutOf(
      { id: "clock", type: "clock", grid: { x: 0, y: 0, w: 4, h: 5 } },
      { id: "tasks", type: "tasks", grid: { x: 4, y: 0, w: 8, h: 10 } }
    );
    expect(order(moveWidget(side, "tasks", -1))).toEqual(["tasks", "clock"]);
  });
});

describe("setWidgetOptions", () => {
  it("replaces one widget's options", () => {
    const start = layoutOf({ id: "clock", type: "clock", grid: { x: 0, y: 0, w: 4, h: 5 } });
    expect(setWidgetOptions(start, "clock", { mode: "timer" }).widgets[0].options).toEqual({
      mode: "timer",
    });
  });
});

describe("layoutFits", () => {
  it("refuses a layout bigger than the preference it is kept in", () => {
    const withOption = (text: string) =>
      layoutOf({ id: "clock", type: "clock", grid: { x: 0, y: 0, w: 4, h: 5 }, options: { text } });
    expect(layoutFits(withOption("short"))).toBe(true);
    expect(layoutFits(withOption("x".repeat(16 * 1024)))).toBe(false);
  });
});

describe("a view's banner", () => {
  const start: HomeLayout = {
    version: HOME_LAYOUT_VERSION,
    preset: "myDay",
    widgets: [{ id: "clock", type: "clock", grid: { x: 0, y: 0, w: 4, h: 4 } }],
  };

  it("is kept with the layout it belongs to", () => {
    expect(readHomeLayout({ ...start, banner: "core.aurora" })?.banner).toBe("core.aurora");
    expect(readHomeLayout({ ...start, banner: 7 })?.banner).toBeUndefined();
  });

  it("is set and taken off without rearranging anything", () => {
    const dressed = setViewBanner(start, "core.aurora");
    expect(dressed).toMatchObject({ banner: "core.aurora", preset: "myDay" });
    expect(setViewBanner(dressed, "core.aurora")).toBe(dressed);
    expect(setViewBanner(dressed, null)).not.toHaveProperty("banner");
    // Moving widgets keeps the banner on.
    expect(applyGrid(dressed, [{ i: "clock", x: 2, y: 0, w: 4, h: 4 }]).banner).toBe("core.aurora");
  });
});
