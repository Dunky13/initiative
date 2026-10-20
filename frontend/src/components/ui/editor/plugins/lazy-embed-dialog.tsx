import { lazy, Suspense } from "react";

import type { EmbedDialogProps } from "@/components/ui/editor/plugins/embed-dialog";
import { Skeleton } from "@/components/ui/skeleton";

// Lazy everywhere it is opened, so the dialog (and the task filters and
// layout fields it carries) stays out of the editor's chunk until someone
// asks for an embed. It also keeps the embed node, which draws the settings
// button, from importing the dialog that builds embed nodes.
const EmbedDialog = lazy(() =>
  import("@/components/ui/editor/plugins/embed-dialog").then((m) => ({ default: m.EmbedDialog }))
);

/** The embed dialog, loaded on first open. */
export function LazyEmbedDialog(props: EmbedDialogProps) {
  return (
    <Suspense fallback={<Skeleton className="h-40 w-full" />}>
      <EmbedDialog {...props} />
    </Suspense>
  );
}
