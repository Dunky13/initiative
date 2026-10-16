/**
 * The reader's home views and the one on screen: its layout, and every change
 * to either, read from and written to their preferences.
 *
 * Which view is shown is the address's `?view=` when it names one of theirs,
 * else the view they had last, else the first.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearch } from "@tanstack/react-router";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import { useViewPreference, writeViewPreference } from "@/hooks/useViewPreference";
import { type HomeLayout, layoutFits, readHomeLayout } from "@/lib/home/layout";
import { DEFAULT_HOME_PRESET, presetLayout } from "@/lib/home/presets";
import {
  addView,
  canAddView,
  HOME_VIEWS_KEY,
  type HomeViews,
  homeViewKey,
  initialHomeViews,
  moveView,
  newViewId,
  readHomeViews,
  removeView,
  renameView,
} from "@/lib/home/views";
import { toast } from "@/lib/mascotToast";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/lib/viewPreferences";

export function useHomeViews() {
  const { t } = useTranslation("home");
  const queryClient = useQueryClient();
  const router = useRouter();
  const search = useSearch({ strict: false }) as { view?: string };
  const [storedViews, , { isLoaded, items }] = useViewPreference<unknown>(HOME_VIEWS_KEY, null);

  const defaultName = t("views.defaultName");
  const views = useMemo(
    () => readHomeViews(storedViews) ?? initialHomeViews(defaultName),
    [storedViews, defaultName]
  );
  const has = (id: string | undefined) => views.views.some((view) => view.id === id);
  const activeId = has(search.view)
    ? (search.view as string)
    : has(views.current)
      ? (views.current as string)
      : views.views[0].id;

  const storedLayout = items?.[homeViewKey(activeId)];
  const savedLayout = useMemo(() => readHomeLayout(storedLayout), [storedLayout]);
  const layout = useMemo(() => savedLayout ?? presetLayout(DEFAULT_HOME_PRESET), [savedLayout]);

  // Every change reads the cache rather than the render, so two in one tick
  // (a drag that also compacts its neighbours) compose.
  const cached = useCallback(
    (key: string) =>
      queryClient.getQueryData<UserViewPreferencesMap>(VIEW_PREFERENCES_QUERY_KEY)?.items?.[key],
    [queryClient]
  );
  const currentViews = useCallback(
    () => readHomeViews(cached(HOME_VIEWS_KEY)) ?? initialHomeViews(defaultName),
    [cached, defaultName]
  );
  const layoutOf = useCallback(
    (id: string) => readHomeLayout(cached(homeViewKey(id))) ?? presetLayout(DEFAULT_HOME_PRESET),
    [cached]
  );
  const writeViews = useCallback(
    (next: HomeViews) => writeViewPreference(queryClient, HOME_VIEWS_KEY, next),
    [queryClient]
  );
  // Home, on that view: from Home itself a tab switch, and from anywhere else
  // (a layout added in the marketplace) the way to the view just made. A table
  // page belongs to the view it was turned in, so none is carried.
  const show = useCallback(
    (id: string) =>
      void router.navigate({ href: `/?view=${encodeURIComponent(id)}`, replace: true }),
    [router]
  );
  const tooLarge = useCallback(
    () => toast.error(t("tooLarge"), { id: "home-layout-too-large" }),
    [t]
  );

  /** Change the view on screen, unless the result would not fit where it is kept. */
  const updateLayout = useCallback(
    (change: (current: HomeLayout) => HomeLayout) => {
      const current = layoutOf(activeId);
      const next = change(current);
      if (next === current) return;
      if (!layoutFits(next)) {
        tooLarge();
        return;
      }
      writeViewPreference(queryClient, homeViewKey(activeId), next);
    },
    [activeId, layoutOf, queryClient, tooLarge]
  );

  const select = useCallback(
    (id: string) => {
      const list = currentViews();
      if (list.current !== id) writeViews({ ...list, current: id });
      show(id);
    },
    [currentViews, writeViews, show]
  );

  /** A new view beside the one on screen, opened. */
  const create = useCallback(
    (name: string, startWith: HomeLayout) => {
      const list = currentViews();
      if (!canAddView(list)) return;
      if (!layoutFits(startWith)) {
        tooLarge();
        return;
      }
      const id = newViewId(list);
      writeViewPreference(queryClient, homeViewKey(id), startWith);
      writeViews(addView(list, { id, name }, activeId));
      show(id);
    },
    [activeId, currentViews, queryClient, show, tooLarge, writeViews]
  );

  const duplicate = useCallback(
    (id: string) => {
      const view = currentViews().views.find((each) => each.id === id);
      if (view) create(t("views.copyName", { name: view.name }), layoutOf(id));
    },
    [create, currentViews, layoutOf, t]
  );

  const rename = useCallback(
    (id: string, name: string) => writeViews(renameView(currentViews(), id, name)),
    [currentViews, writeViews]
  );

  const remove = useCallback(
    (id: string) => {
      const { views: next, next: shown } = removeView(currentViews(), id);
      if (next.views.some((view) => view.id === id)) return;
      writeViews(next);
      // The preference has no delete; an emptied one reads as no layout.
      writeViewPreference(queryClient, homeViewKey(id), null);
      if (id === activeId) show(shown);
    },
    [activeId, currentViews, queryClient, show, writeViews]
  );

  const move = useCallback(
    (id: string, step: -1 | 1) => writeViews(moveView(currentViews(), id, step)),
    [currentViews, writeViews]
  );

  return {
    views,
    activeId,
    activeView: views.views.find((view) => view.id === activeId) ?? views.views[0],
    layout,
    isLoaded,
    updateLayout,
    select,
    create,
    duplicate,
    rename,
    remove,
    move,
  };
}
