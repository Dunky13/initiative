import { useSyncExternalStore } from "react";

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

// One share at a time, in memory: it is on its way somewhere, and a newer one
// replaces it. Kept outside React so the share sheet's listener, which lives
// above the router, and the page it opens read the same one.
let pending: ReceivedShare | null = null;
const listeners = new Set<() => void>();

const notify = () => {
  for (const listener of listeners) listener();
};

export function setPendingShare(share: ReceivedShare | null) {
  pending = share;
  notify();
}

export function getPendingShare(): ReceivedShare | null {
  return pending;
}

/** Record that the share page is showing it, so signing in stops leading there. */
export function markPendingShareOpened() {
  if (!pending || pending.opened) return;
  pending = { ...pending, opened: true };
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
