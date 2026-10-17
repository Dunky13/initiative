/**
 * Targets on the chart, stat and progress widgets, through the path they take
 * in production: sandboxed module, validator, scene.
 *
 * The standing (reached, on track, behind, missed, or how far to go) is worked
 * out inside each module from the data it was given and the frozen clock, so
 * these pin it against a fixed "now".
 */
import { describe, expect, it } from "vitest";

import type { CellValue, TabularData } from "../dataShapes";
import { builtinWidgetSource } from "../registry";
import { renderInSandbox } from "../runtime/sandbox";
import type { MetricNode, ProgressNode, SeriesNode } from "../sceneSpec";
import { validateScene } from "../validateScene";

const at = (day: string) => Date.parse(`${day}T00:00:00Z`);

/** A Sunday after the weeks below, so a target due before it has passed. */
const NOW = at("2026-02-01");

const draw = async <T>(
  type: string,
  data: TabularData,
  config: Record<string, string>,
  slots: Record<string, number[]>
): Promise<T> => {
  const result = await renderInSandbox({
    source: builtinWidgetSource(type) as string,
    data,
    config,
    slots,
    now: NOW,
  });
  expect(result.ok, JSON.stringify(result)).toBe(true);
  if (!result.ok) throw new Error("render failed");
  const validation = validateScene(result.value);
  expect(validation.ok, JSON.stringify(validation)).toBe(true);
  if (!validation.ok) throw new Error("invalid scene");
  return validation.spec.scene as T;
};

const rows = (columns: [string, string][], body: CellValue[][], grain?: "week"): TabularData => ({
  source: "rows",
  columns: columns.map(([name, type], index) => ({
    name,
    type: type as never,
    ...(index === 0 && grain ? { grain } : {}),
  })),
  rows: body,
});

/** A burn-up: ten more every week for four weeks. */
const weeks = ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"].map(at);
const burnUp = (values: number[]) =>
  rows(
    [
      ["week", "date"],
      ["done", "number"],
    ],
    weeks.map((week, index) => [week, values[index]]),
    "week"
  );

describe("the chart", () => {
  const chart = (
    data: TabularData,
    config: Record<string, string>,
    slots?: Record<string, number[]>
  ) => draw<SeriesNode>("chart", data, config, slots ?? { label: [0], value: [1] });

  it.each([
    // Ten a week from 40 on Jan 26 reaches 100 by the end of March.
    ["2026-03-30", "On track"],
    // ...but not by Feb 9.
    ["2026-02-09", "Behind"],
  ])("projects the trend to %s", async (due, standing) => {
    const scene = await chart(burnUp([10, 20, 30, 40]), { target: "100", target_date: due });
    expect(scene.target).toBe(100);
    expect(scene.targetLabel).toBe(`Target 100 · ${standing}`);
  });

  it("says when the target is reached, and when its day passed without it", async () => {
    expect((await chart(burnUp([10, 20, 30, 40]), { target: "30" })).targetLabel).toBe(
      "Target 30 · Reached"
    );
    expect(
      (await chart(burnUp([10, 20, 30, 40]), { target: "100", target_date: "2026-01-31" }))
        .targetLabel
    ).toBe("Target 100 · Missed");
  });

  it("says how far is left without a day to project to", async () => {
    expect((await chart(burnUp([10, 20, 30, 40]), { target: "100" })).targetLabel).toBe(
      "Target 100 · 60 to go"
    );
  });

  it("reads a target below the start as one to come down to", async () => {
    const scene = await chart(burnUp([40, 30, 20, 10]), { target: "0", target_date: "2026-03-30" });
    expect(scene.targetLabel).toBe("Target 0 · On track");
  });

  it("reads a stack by its total", async () => {
    const split = rows(
      [
        ["week", "date"],
        ["status", "text"],
        ["done", "number"],
      ],
      weeks.flatMap((week, index) => [
        [week, "a", 5 * (index + 1)],
        [week, "b", 5 * (index + 1)],
      ]),
      "week"
    );
    const scene = await chart(
      split,
      { target: "40", stacked: "true" },
      { label: [0], value: [2], series: [1] }
    );
    expect(scene.targetLabel).toBe("Target 40 · Reached");
  });

  it("only marks the target where there is no one line to read", async () => {
    const sideBySide = rows(
      [
        ["week", "date"],
        ["a", "number"],
        ["b", "number"],
      ],
      weeks.map((week) => [week, 1, 2]),
      "week"
    );
    expect(
      (await chart(sideBySide, { target: "10" }, { label: [0], value: [1, 2] })).targetLabel
    ).toBe("Target 10");
    const categories = rows(
      [
        ["priority", "text"],
        ["n", "number"],
      ],
      [
        ["high", 3],
        ["low", 9],
      ]
    );
    expect((await chart(categories, { target: "5" })).targetLabel).toBe("Target 5");
  });

  it("reads the latest moment even where the category ceiling folds it", async () => {
    // Six weeks against a ceiling of five: the smallest, which is the latest,
    // is drawn inside "Other" but is still where the line stands.
    const sixWeeks = rows(
      [
        ["week", "date"],
        ["open", "number"],
      ],
      [60, 50, 40, 30, 20, 10].map((value, index) => [
        at("2026-01-05") + index * 7 * 86400000,
        value,
      ]),
      "week"
    );
    expect((await chart(sixWeeks, { target: "0", limit: "5" })).targetLabel).toBe(
      "Target 0 · 10 to go"
    );
  });

  it("draws no target on a pie", async () => {
    const scene = await chart(burnUp([10, 20, 30, 40]), { target: "30", mark: "pie" });
    expect(scene.target).toBeUndefined();
  });
});

describe("the stat", () => {
  const stat = (
    data: TabularData,
    config: Record<string, string>,
    slots: Record<string, number[]>
  ) => draw<MetricNode>("stat", data, config, slots);

  it("adds a time series up before projecting it", async () => {
    // Ten a week is 40 so far, and 100 by the end of March.
    const scene = await stat(
      burnUp([10, 10, 10, 10]),
      { target: "100", target_date: "2026-03-30" },
      { value: [1], label: [0] }
    );
    expect(scene.value).toBe(40);
    expect(scene.caption).toBe("Target 100 · On track");
    expect(scene.tone).toBe("positive");
  });

  it("says how far a single number is from its target", async () => {
    const one = rows([["n", "number"]], [[30]]);
    const scene = await stat(one, { target: "50" }, { value: [0] });
    expect(scene.caption).toBe("Target 50 · 20 to go");
    expect(scene.tone).toBeUndefined();
  });

  it("does not read a small target as nothing", async () => {
    const none = rows([["n", "number"]], [[0]]);
    const scene = await stat(none, { target: "0.001" }, { value: [0] });
    expect(scene.caption).toBe("Target 0.001 · 0.001 to go");
  });

  it("aims down when falling is good", async () => {
    const one = rows([["open", "number"]], [[30]]);
    const scene = await stat(one, { target: "50", direction: "down_good" }, { value: [0] });
    expect(scene.caption).toBe("Target 50 · Reached");
  });
});

describe("the progress bar", () => {
  const share = rows(
    [
      ["done", "number"],
      ["total", "number"],
    ],
    [[30, 100]]
  );

  it("marks the target on its track and says how far is left", async () => {
    const scene = await draw<ProgressNode>(
      "progress",
      share,
      { target: "50" },
      { value: [0], total: [1] }
    );
    expect(scene.target).toBe(50);
    expect(scene.caption).toBe("30 of 100 · Target 50 · 20 to go");
  });

  it("says the target was missed once its day has passed", async () => {
    const scene = await draw<ProgressNode>(
      "progress",
      share,
      { target: "50", target_date: "2026-01-15" },
      { value: [0], total: [1] }
    );
    expect(scene.caption).toBe("30 of 100 · Target 50 · Missed");
    expect(scene.tone).toBe("negative");
  });
});

describe("the helpers each module carries", () => {
  it("are the same in all three", () => {
    // Every module runs in a sandbox of its own and shares no code, so each
    // carries its own copy; this keeps the copies from drifting apart.
    const helpers = (type: string) => {
      const source = builtinWidgetSource(type) as string;
      return source.slice(
        source.indexOf("/** One day, in milliseconds. */"),
        source.indexOf("/**\n * Built-in:")
      );
    };
    expect(helpers("chart")).not.toBe("");
    expect(helpers("stat")).toBe(helpers("chart"));
    expect(helpers("progress")).toBe(helpers("chart"));
  });
});
