import { useSyncExternalStore } from "react";

import { getItem, removeItem, setItem } from "@/lib/storage";

/** A file another app shared: where the device keeps it, and what it is. */
export interface SharedFile {
  /** A device path or data URL, as the share sheet handed it over. */
  uri: string;
  name: string;
  mimeType: string;
}

/** What the share sheet handed over, kept to what the app can land. */
export interface ReceivedShare {
  /** Tells one share from the next, so a newer one starts the page afresh. */
  id: number;
  title: string;
  texts: string[];
  files: SharedFile[];
  /** Whether the share page has shown it. Until it has, signing in leads there. */
  opened: boolean;
}

/** The plug-in's event, as it arrives. */
export interface ShareEvent {
  title?: string | null;
  texts?: (string | null)[] | null;
  files?: { uri: string; name: string; mimeType: string }[] | null;
}

let received = 0;

/** A picture goes into a body; any other file can only be uploaded. */
export const isImage = (file: SharedFile): boolean => file.mimeType.startsWith("image/");

/** The event, as something to land, with its blank texts dropped. */
export function receivedShare(event: ShareEvent): ReceivedShare | null {
  const texts = (event.texts ?? [])
    .map((text) => text?.trim() ?? "")
    .filter((text) => text.length > 0);
  const files = (event.files ?? [])
    .filter((file) => !!file?.uri)
    .map((file) => ({ ...file, mimeType: file.mimeType || "application/octet-stream" }));
  const title = event.title?.trim() ?? "";
  if (!title && texts.length === 0 && files.length === 0) return null;
  received += 1;
  return { id: received, title, texts, files, opened: false };
}

// One share at a time: it is on its way somewhere, and a newer one replaces it.
// Kept outside React so the share sheet's listener, which lives above the
// router, and the page it opens read the same one.
//
// Until the share page has shown it, it is kept on the device as well: signing
// in can send somebody to a browser, and the app may be closed behind them.
// The files it names are kept by the share plug-in for a day, so a share older
// than that is let go.
const STORAGE_KEY = "initiative-pending-share";
const KEPT_FOR_MS = 24 * 60 * 60 * 1000;

let pending: ReceivedShare | null | undefined;
const listeners = new Set<() => void>();

const notify = () => {
  for (const listener of listeners) listener();
};

/** The share kept on the device, read once: storage is ready by the first read. */
function restored(): ReceivedShare | null {
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return null;
    const { share, savedAt } = JSON.parse(raw) as { share: ReceivedShare; savedAt: number };
    if (!share || Date.now() - savedAt > KEPT_FOR_MS) {
      removeItem(STORAGE_KEY);
      return null;
    }
    received = Math.max(received, share.id);
    return { ...share, opened: false };
  } catch {
    removeItem(STORAGE_KEY);
    return null;
  }
}

export function setPendingShare(share: ReceivedShare | null) {
  pending = share;
  if (share && !share.opened) {
    setItem(STORAGE_KEY, JSON.stringify({ share, savedAt: Date.now() }));
  } else {
    removeItem(STORAGE_KEY);
  }
  notify();
}

export function getPendingShare(): ReceivedShare | null {
  if (pending === undefined) pending = restored();
  return pending;
}

/** Record that the share page is showing it, so signing in stops leading there. */
export function markPendingShareOpened() {
  const share = getPendingShare();
  if (!share || share.opened) return;
  pending = { ...share, opened: true };
  removeItem(STORAGE_KEY);
  notify();
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export function usePendingShare(): ReceivedShare | null {
  return useSyncExternalStore(subscribe, getPendingShare, getPendingShare);
}
