/**
 * A new person's first home page, made from why they signed up.
 *
 * The start flow's first question is what they came for — their own list, a
 * community to join, a community of their own, an invite — and that is the
 * same question the starting layouts answer. So the flow's answer picks the
 * layout, with getting started at the top and the widgets that read one
 * community or one list pointed at the ones the flow just made.
 *
 * It is written once, at the end of the flow, and only when the account has
 * no home of its own yet.
 */

import type { QueryClient } from "@tanstack/react-query";

import {
  listViewPreferences,
  putViewPreference,
} from "@/api/generated/user-view-preferences/user-view-preferences";
import { clampGrid, type HomeLayout, type HomeWidget } from "@/lib/home/layout";
import { type HomePresetId, presetLayout } from "@/lib/home/presets";
import { HOME_VIEWS_KEY, homeViewKey, MAIN_VIEW_ID } from "@/lib/home/views";
import { HOME_WIDGET_SIZES } from "@/lib/home/widgetTypes";
import type { StartPath } from "@/lib/startFlow";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/lib/viewPreferences";

/**
 * A list new tasks go into: where the tasks widget adds one. Where it is, and
 * nothing it says — its name is read from the list, so no community's words
 * are copied into the reader's preferences.
 */
export interface HomeTaskList {
  communityId: number;
  initiativeId: number;
  projectId: number;
}

export interface FirstHomeContext {
  /** The community the flow made or joined, when there is one yet. */
  communityId?: number | null;
  /** Personal: the list the flow made. */
  list?: HomeTaskList | null;
}

const PRESET_FOR: Record<StartPath, HomePresetId> = {
  personal: "myDay",
  shared: "owner",
  join: "community",
  invite: "community",
};

/** Getting started goes under the greeting, and everything below moves down to make room. */
const withGettingStarted = (layout: HomeLayout, path: StartPath): HomeLayout => {
  const greeting = layout.widgets.find((widget) => widget.type === "greeting");
  const top = greeting ? greeting.grid.y + greeting.grid.h : 0;
  const { h } = HOME_WIDGET_SIZES.gettingStarted;
  const moved = layout.widgets.map((widget) =>
    widget.grid.y >= top ? { ...widget, grid: { ...widget.grid, y: widget.grid.y + h } } : widget
  );
  const card: HomeWidget = {
    id: "gettingStarted",
    type: "gettingStarted",
    grid: clampGrid("gettingStarted", { x: 0, y: top, w: 12, h }),
    options: { path },
  };
  return { ...layout, widgets: [...moved, card] };
};

export const firstHomeLayout = (path: StartPath, context: FirstHomeContext = {}): HomeLayout => {
  const layout = withGettingStarted(presetLayout(PRESET_FOR[path]), path);
  return {
    ...layout,
    widgets: layout.widgets.map((widget) => {
      if (widget.type === "activity" && context.communityId) {
        return { ...widget, options: { ...widget.options, communityId: context.communityId } };
      }
      if (widget.type === "tasks" && context.list) {
        return { ...widget, options: { ...widget.options, addTo: context.list } };
      }
      if (widget.type === "gettingStarted" && context.list) {
        return { ...widget, options: { ...widget.options, list: context.list } };
      }
      return widget;
    }),
  };
};

/**
 * Save the first home page, unless the account already has one — somebody
 * signed in with no community left, starting again, keeps the page they made.
 * A failure is let go: the default page is still a page.
 */
export const seedFirstHome = async (
  queryClient: QueryClient,
  path: StartPath,
  context: FirstHomeContext = {}
): Promise<void> => {
  try {
    const { items } = await listViewPreferences();
    if (items?.[HOME_VIEWS_KEY] != null || items?.[homeViewKey(MAIN_VIEW_ID)] != null) return;
    await putViewPreference(homeViewKey(MAIN_VIEW_ID), { value: firstHomeLayout(path, context) });
    await queryClient.invalidateQueries({ queryKey: VIEW_PREFERENCES_QUERY_KEY });
  } catch {
    // The default home page stands in.
  }
};
