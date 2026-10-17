import { Capacitor } from "@capacitor/core";
import { CapacitorShareTarget } from "@capgo/capacitor-share-target";
import { useLocation, useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { useServer } from "@/hooks/useServer";
import { receivedShare, setPendingShare, usePendingShare } from "@/lib/share/pendingShare";

export const SHARE_PATH = "/share";

/**
 * Receives what another app shares to this one from the system share sheet,
 * and opens the share page with it.
 *
 * Mounted above the sign-in guard: a share can be what starts the app, and it
 * has to be held while somebody signs in. The plug-in keeps an event until a
 * listener is registered, so one that launched the app is not lost to the
 * time the app takes to start.
 */
export function useShareTarget() {
  const router = useRouter();
  const { isNativePlatform } = useServer();
  // The desktop app is native too, but nothing shares to it.
  const receives = isNativePlatform && Capacitor.getPlatform() !== "electron";

  useEffect(() => {
    if (!receives) return;
    const listener = CapacitorShareTarget.addListener("shareReceived", (event) => {
      const share = receivedShare(event);
      if (!share) return;
      setPendingShare(share);
      void router.navigate({ to: SHARE_PATH });
    });
    return () => {
      void listener.then((handle) => handle.remove());
    };
  }, [receives, router]);
}

/**
 * Leads back to a share the share page has not shown yet. A share that arrives
 * signed out is sent through sign-in, and not every way of signing in comes
 * back to where it set out from.
 */
export function useResumePendingShare() {
  const router = useRouter();
  const pathname = useLocation({ select: (location) => location.pathname });
  const share = usePendingShare();
  const waiting = !!share && !share.opened;

  useEffect(() => {
    if (waiting && pathname !== SHARE_PATH) {
      void router.navigate({ to: SHARE_PATH });
    }
  }, [waiting, pathname, router]);
}
