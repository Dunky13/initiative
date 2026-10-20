import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/share")({
  component: lazyRouteComponent(() =>
    import("@/pages/SharePage").then((m) => ({ default: m.SharePage }))
  ),
});
