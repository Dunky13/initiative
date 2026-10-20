import { describe, expect, it } from "vitest";

import { HOME_GRID_COLUMNS, readHomeLayout } from "./layout";
import { DEFAULT_HOME_PRESET, HOME_PRESET_IDS, presetLayout } from "./presets";

describe.each(HOME_PRESET_IDS)("the %s starting layout", (id) => {
  const layout = presetLayout(id);

  it("reads back exactly as written, so nothing about it is clamped or dropped", () => {
    expect(readHomeLayout(JSON.parse(JSON.stringify(layout)))).toEqual(layout);
  });

  it("names itself, so the picker can mark it", () => {
    expect(layout.preset).toBe(id);
  });

  it("puts no widget on top of another, or past the edge", () => {
    const cells = new Set<string>();
    for (const { grid } of layout.widgets) {
      expect(grid.x + grid.w).toBeLessThanOrEqual(HOME_GRID_COLUMNS);
      for (let x = grid.x; x < grid.x + grid.w; x++) {
        for (let y = grid.y; y < grid.y + grid.h; y++) {
          const cell = `${x},${y}`;
          expect(cells.has(cell), `${cell} is taken twice`).toBe(false);
          cells.add(cell);
        }
      }
    }
  });
});

describe("the default home page", () => {
  it("is My Tasks as it was: the focus card over the tasks table", () => {
    const types = presetLayout(DEFAULT_HOME_PRESET).widgets.map((widget) => widget.type);
    expect(types).toEqual(expect.arrayContaining(["focus", "tasks"]));
    expect(types.indexOf("focus")).toBeLessThan(types.indexOf("tasks"));
  });
});

describe("the starting layouts, side by side", () => {
  // A preset that is another one with a widget missing is not a choice. The
  // default is the exception: it is My Tasks as it was, kept on purpose as the
  // plainest page there is.
  it("are each more than another one with something taken away", () => {
    const kinds = Object.fromEntries(
      HOME_PRESET_IDS.map((id) => [
        id,
        new Set(
          presetLayout(id).widgets.map((w) => `${w.type}:${JSON.stringify(w.options ?? {})}`)
        ),
      ])
    );
    for (const a of HOME_PRESET_IDS.filter((id) => id !== DEFAULT_HOME_PRESET)) {
      for (const b of HOME_PRESET_IDS) {
        if (a === b) continue;
        const contained = [...kinds[a]].every((kind) => kinds[b].has(kind));
        expect(contained, `${a} is ${b} with widgets taken away`).toBe(false);
      }
    }
  });
});
