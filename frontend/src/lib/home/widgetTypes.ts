/**
 * The widgets a home page can hold, and how big each may be.
 *
 * Kept apart from the components that draw them so the layout helpers and the
 * starting layouts can be read (and tested) without pulling in every widget.
 * `components/home/widgets` maps each type to its component, and its test
 * holds the two lists together.
 */

export const HOME_WIDGET_TYPES = [
  "greeting",
  "gettingStarted",
  "focus",
  "tasks",
  "comingUp",
  "calendar",
  "recent",
  "bookmarks",
  "activity",
  "communities",
  "progress",
  "clock",
] as const;

export type HomeWidgetType = (typeof HOME_WIDGET_TYPES)[number];

export interface HomeWidgetSize {
  /** Default width and height, in columns and rows. */
  w: number;
  h: number;
  minW: number;
  minH: number;
  /** At most one on a page: the widget keeps its state in one place of the
   *  reader's own (the calendar's view, the focus card's pins). */
  single?: boolean;
}

export const HOME_WIDGET_SIZES: Record<HomeWidgetType, HomeWidgetSize> = {
  greeting: { w: 12, h: 2, minW: 4, minH: 2, single: true },
  gettingStarted: { w: 12, h: 5, minW: 4, minH: 4, single: true },
  focus: { w: 12, h: 5, minW: 4, minH: 3, single: true },
  // Each keeps its own columns; the filters and sort are the reader's, shared.
  tasks: { w: 12, h: 10, minW: 5, minH: 5 },
  comingUp: { w: 4, h: 8, minW: 3, minH: 4 },
  // One calendar view and one set of filters, the reader's own, as on My Calendar.
  calendar: { w: 12, h: 11, minW: 5, minH: 7, single: true },
  recent: { w: 4, h: 6, minW: 3, minH: 3 },
  bookmarks: { w: 4, h: 6, minW: 3, minH: 3 },
  activity: { w: 8, h: 9, minW: 3, minH: 4 },
  communities: { w: 12, h: 6, minW: 4, minH: 5, single: true },
  progress: { w: 12, h: 3, minW: 4, minH: 2, single: true },
  clock: { w: 4, h: 4, minW: 2, minH: 3 },
};
