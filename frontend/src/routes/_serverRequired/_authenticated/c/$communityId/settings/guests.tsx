import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/guests"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityGuestsPage").then((m) => ({
      default: m.SettingsCommunityGuestsPage,
    }))
  ),
});
