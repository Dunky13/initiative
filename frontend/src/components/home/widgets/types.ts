import type { LucideIcon } from "lucide-react";
import type { ComponentType } from "react";

import type { HomeWidget, HomeWidgetOptions } from "@/lib/home/layout";

export interface HomeWidgetProps {
  widget: HomeWidget;
  /** The widget's own options; `{}` when it has none saved. */
  options: HomeWidgetOptions;
  /** Saves new options into the layout — for a widget whose content is its
   *  options (a note). */
  onOptionsChange: (next: HomeWidgetOptions) => void;
  /** In the narrow stack, where a widget is as tall as its content and nobody
   *  resizes it; on the grid otherwise, filling the cell it was given. */
  stacked: boolean;
  /** Opens the widget's settings, for a widget that points the reader at them. */
  onConfigure: () => void;
  /** Takes the widget off the page, for one that is finished with (getting started). */
  onRemove: () => void;
}

export interface HomeWidgetSettingsProps {
  options: HomeWidgetOptions;
  onChange: (next: HomeWidgetOptions) => void;
}

export interface HomeWidgetDefinition {
  icon: LucideIcon;
  Component: ComponentType<HomeWidgetProps>;
  /** The form for the widget's options, when it has any. */
  Settings?: ComponentType<HomeWidgetSettingsProps>;
}
