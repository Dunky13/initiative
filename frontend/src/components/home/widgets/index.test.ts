import { describe, expect, it } from "vitest";

import { HOME_PRESET_IDS } from "@/lib/home/presets";
import { HOME_WIDGET_TYPES } from "@/lib/home/widgetTypes";

import en from "../../../../public/locales/en/home.json";
import { HOME_WIDGETS } from ".";

describe("home widgets", () => {
  it.each(HOME_WIDGET_TYPES)("%s is drawn and named", (type) => {
    expect(HOME_WIDGETS[type].Component).toBeTypeOf("function");
    const strings = (en.widgets as Record<string, { title?: string; description?: string }>)[type];
    expect(strings?.title).toBeTruthy();
    expect(strings?.description).toBeTruthy();
  });

  it("draws nothing that is not a home widget type", () => {
    expect(Object.keys(HOME_WIDGETS).sort()).toEqual([...HOME_WIDGET_TYPES].sort());
  });

  it.each(HOME_PRESET_IDS)("the %s layout is named and described", (id) => {
    expect(en.presets[id].name).toBeTruthy();
    expect(en.presets[id].description).toBeTruthy();
  });
});
