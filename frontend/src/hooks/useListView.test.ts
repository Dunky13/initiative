import { act, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { keepViewPreferences } from "@/__tests__/helpers/viewPreferences";

import {
  keptView,
  LIST,
  NO_PART_VIEW,
  partOf,
  sanitizeListView,
  useListView,
  viewKey,
} from "./useListView";

const spec = {
  key: viewKey(4, "initiative", 2, "files"),
  read: (raw: unknown) => raw as { tag_ids: number[] },
  defaults: { filters: { tag_ids: [] }, ...NO_PART_VIEW, sorting: [{ id: "name", desc: false }] },
  carryOver: () => ({
    layout: "grid",
    parts: { [LIST]: { sorting: [{ id: "updated_at", desc: true }] } },
  }),
};

describe("a person's view of a list", () => {
  it("is kept under the community, then what names the list", () => {
    expect(spec.key).toBe("view:4:initiative:2:files");
  });

  it("reads what is kept, else what an older release kept", () => {
    const kept = { layout: "list", parts: { [LIST]: { filters: { tag_ids: [7] } } } };
    expect(keptView({ [spec.key]: kept }, spec).view.layout).toBe("list");
    expect(keptView({}, spec).view.layout).toBe("grid");
  });

  it("fills what a part keeps with the list's defaults", () => {
    const view = keptView({}, spec).view;
    expect(partOf(view, LIST, spec)).toEqual({
      filters: { tag_ids: [] },
      sorting: [{ id: "updated_at", desc: true }],
      grouping: [],
      columns: {},
    });
  });

  it("drops what has the wrong type rather than breaking the list", () => {
    const view = sanitizeListView({
      layout: 3,
      parts: { [LIST]: { sorting: [{ id: 1 }, { id: "name", desc: true }], grouping: "x" } },
    });
    expect(view.layout).toBeNull();
    expect(partOf(view, LIST, spec)).toMatchObject({
      sorting: [{ id: "name", desc: true }],
      grouping: [],
    });
  });

  it("applies a change made before it is in to it, and saves no change that leaves it as it was", async () => {
    const kept = keepViewPreferences();
    kept[spec.key] = { layout: "list" };
    let view!: ReturnType<typeof useListView<{ tag_ids: number[] }>>;
    const Probe = () => {
      view = useListView(spec);
      return null;
    };
    renderWithProviders(createElement(Probe));

    act(() => view.setMode("week"));
    await waitFor(() => expect(view.mode).toBe("week"));
    expect(view.layout).toBe("list");
    await waitFor(() => expect(kept[spec.key]).toMatchObject({ layout: "list", mode: "week" }));

    const saved = kept[spec.key];
    act(() => view.rememberLayout("list"));
    // Past the save's debounce: nothing more reached the server.
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(kept[spec.key]).toBe(saved);
  });
});
