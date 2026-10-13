/**
 * Home: where a signed-in person lands, laid out the way they want it.
 *
 * People are here for different things — their own list, a community they
 * follow, an organisation they run, work somebody handed them — so the page is
 * a canvas of widgets the reader arranges, starting from one of a few layouts
 * made for those reasons. Someone who is here for more than one keeps several
 * views — work on one, the scout group on another — and moves between them
 * with tabs. It began as My Tasks, and with nothing arranged it still is: a
 * greeting over the focus card and the tasks table.
 */

import { Check, LayoutTemplate, Pencil, Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { invalidate, q } from "@/api/query-keys";
import { AddHomeWidgetDialog } from "@/components/home/AddHomeWidgetDialog";
import { HomeCanvas } from "@/components/home/HomeCanvas";
import { type HomeLayoutChoice, HomeLayoutsDialog } from "@/components/home/HomeLayoutsDialog";
import { HomeViewTabs } from "@/components/home/HomeViewTabs";
import { HomeWidgetSettingsDialog } from "@/components/home/HomeWidgetSettingsDialog";
import { HomeActionsContext } from "@/components/home/homeActions";
import { PullToRefresh } from "@/components/PullToRefresh";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useHomeViews } from "@/hooks/useHomeViews";
import { atLeast, useRegionWidthClass } from "@/hooks/useWidthClass";
import {
  addWidget,
  applyGrid,
  HOME_LAYOUT_VERSION,
  type HomeLayout,
  moveWidget,
  removeWidget,
  setWidgetOptions,
} from "@/lib/home/layout";
import { presetLayout } from "@/lib/home/presets";

export const HomePage = () => {
  const { t } = useTranslation(["home", "common"]);
  const home = useHomeViews();
  const { layout, isLoaded, updateLayout } = home;
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [choosingLayout, setChoosingLayout] = useState<"new" | "fill" | null>(null);
  const [configuring, setConfiguring] = useState<string | null>(null);
  const [region, setRegion] = useState<HTMLDivElement | null>(null);
  // The grid needs room for two widgets side by side; narrower, they stack.
  const wide = atLeast(useRegionWidthClass(region), "md");

  const handleRefresh = useCallback(async () => {
    await invalidate(q.allTasks(), q.allCalendars(), q.userStats());
  }, []);

  const actions = useMemo(() => ({ customize: () => setEditing(true) }), []);

  const empty = layout.widgets.length === 0;
  const configuringWidget = layout.widgets.find((widget) => widget.id === configuring) ?? null;

  const pickLayout = (choice: HomeLayoutChoice) => {
    const start: HomeLayout =
      choice === "blank" ? { version: HOME_LAYOUT_VERSION, widgets: [] } : presetLayout(choice);
    if (choosingLayout === "fill") {
      updateLayout(() => start);
    } else {
      home.create(choice === "blank" ? t("views.blank.name") : t(`presets.${choice}.name`), start);
    }
  };

  return (
    <HomeActionsContext.Provider value={actions}>
      <PullToRefresh onRefresh={handleRefresh}>
        <div ref={setRegion} className="space-y-4">
          <h1 className="sr-only">{t("title")}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              {isLoaded ? (
                <HomeViewTabs
                  views={home.views}
                  activeId={home.activeId}
                  editing={editing}
                  onSelect={home.select}
                  onNew={() => setChoosingLayout("new")}
                  onRename={home.rename}
                  onDuplicate={home.duplicate}
                  onMove={home.move}
                  onDelete={home.remove}
                />
              ) : null}
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {editing ? (
                <>
                  <Button type="button" variant="outline" size="sm" onClick={() => setAdding(true)}>
                    <Plus className="size-4" aria-hidden="true" />
                    {t("addWidget")}
                  </Button>
                  <Button type="button" size="sm" onClick={() => setEditing(false)}>
                    <Check className="size-4" aria-hidden="true" />
                    {t("common:done")}
                  </Button>
                </>
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setEditing(true)}
                  disabled={!isLoaded}
                >
                  <Pencil className="size-4" aria-hidden="true" />
                  {t("customize")}
                </Button>
              )}
            </div>
          </div>
          {editing ? (
            <p className="text-muted-foreground text-sm">
              {wide ? t("editing.hint") : t("editing.hintStacked")}
            </p>
          ) : null}

          {!isLoaded ? (
            // The layout is the reader's own; drawing the default first would
            // mount a page of widgets only to swap them for theirs.
            <div className="space-y-4" aria-busy="true">
              <Skeleton className="h-24 w-full rounded-xl" />
              <Skeleton className="h-64 w-full rounded-xl" />
            </div>
          ) : empty ? (
            <Empty className="border border-dashed">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <LayoutTemplate />
                </EmptyMedia>
                <EmptyTitle>{t("empty.title")}</EmptyTitle>
                <EmptyDescription>{t("empty.description")}</EmptyDescription>
              </EmptyHeader>
              <EmptyContent className="flex-row flex-wrap justify-center">
                <Button type="button" onClick={() => setAdding(true)}>
                  <Plus className="size-4" aria-hidden="true" />
                  {t("addWidget")}
                </Button>
                <Button type="button" variant="outline" onClick={() => setChoosingLayout("fill")}>
                  <LayoutTemplate className="size-4" aria-hidden="true" />
                  {t("empty.fromLayout")}
                </Button>
              </EmptyContent>
            </Empty>
          ) : (
            <HomeCanvas
              // A view's grid starts from its own layout, not the last one's.
              key={home.activeId}
              layout={layout}
              editing={editing}
              wide={wide}
              onArrange={(placed) => updateLayout((current) => applyGrid(current, placed))}
              onMove={(id, step) => updateLayout((current) => moveWidget(current, id, step))}
              onRemove={(id) => updateLayout((current) => removeWidget(current, id))}
              onConfigure={setConfiguring}
              onOptionsChange={(id, options) =>
                updateLayout((current) => setWidgetOptions(current, id, options))
              }
            />
          )}
        </div>

        <AddHomeWidgetDialog
          open={adding}
          onOpenChange={setAdding}
          layout={layout}
          onAdd={(type) => updateLayout((current) => addWidget(current, type))}
        />
        <HomeLayoutsDialog
          open={choosingLayout !== null}
          onOpenChange={(open) => {
            if (!open) setChoosingLayout(null);
          }}
          mode={choosingLayout ?? "new"}
          onPick={pickLayout}
        />
        <HomeWidgetSettingsDialog
          widget={configuringWidget}
          onClose={() => setConfiguring(null)}
          onChange={(id, options) =>
            updateLayout((current) => setWidgetOptions(current, id, options))
          }
        />
      </PullToRefresh>
    </HomeActionsContext.Provider>
  );
};
