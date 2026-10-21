import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/task-types"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectSettingsTaskTypesPage").then((m) => ({
      default: m.ProjectSettingsTaskTypesPage,
    }))
  ),
});
