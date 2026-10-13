import { createContext, useContext } from "react";

/** What the home page offers the widgets on it beyond their own options. */
export interface HomeActions {
  /** Puts the page into customizing, as its own button does. */
  customize: () => void;
}

export const HomeActionsContext = createContext<HomeActions>({ customize: () => undefined });

export const useHomeActions = () => useContext(HomeActionsContext);
