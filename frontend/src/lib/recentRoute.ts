import type { FavoriteItemRead, RecentItemRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { communityPath } from "@/lib/communityUrl";
import { showsActivity, TOOLS, toolDetailRoute, toolRouteSegment } from "@/lib/tools";

export type RecentKey = {
  entityType: RecentItemRead["entity_type"];
  entityId: number;
  /** Community parsed from the URL prefix. */
  communityId: number;
  /** Initiative parsed from the URL, or null for a community-level entity. */
  initiativeId: number | null;
};

/**
 * Return the community-scoped detail-page route for a recent item — the tool's
 * registry route segment plus the entity id.
 *
 * The tabs bar is cross-community: each tab links into the entity's OWN community
 * (``item.community_id``), never the community the viewer happens to be in —
 * per-community entity ids collide across communities, so a tab opened under the
 * wrong community prefix would resolve to a different (or inaccessible) entity.
 * Navigating the link enters that community via the /c/$communityId layout.
 */
export function recentRoute(item: RecentItemRead | FavoriteItemRead): string {
  return communityPath(
    item.community_id,
    toolDetailRoute(item.entity_type as Tool, item.initiative_id, item.entity_id)
  );
}

/** Parse a decimal id from a path segment ("42" → 42, anything else → null). */
function parseId(segment: string | undefined): number | null {
  if (!segment || !/^\d+$/.test(segment)) {
    return null;
  }
  const id = Number.parseInt(segment, 10);
  return Number.isSafeInteger(id) && id >= 0 ? id : null;
}

/**
 * Parse the current location pathname into a ``RecentKey`` so the tabs bar can
 * highlight the active tab. Returns null when no entity detail page is open.
 *
 * Two shapes, because a tool entity is addressed inside its initiative but a
 * community-level one (only calendars have any) is not:
 *   /c/{communityId}/i/{initiativeId}/{toolSegment}/{entityId}/…
 *   /c/{communityId}/{toolSegment}/{entityId}/…
 */
export function getActiveRecentKey(pathname: string): RecentKey | null {
  const parts = pathname.split("/");
  if (parts[1] !== "c") {
    return null;
  }
  const communityId = parseId(parts[2]);
  if (communityId == null) {
    return null;
  }
  const nested = parts[3] === "i";
  const initiativeId = nested ? parseId(parts[4]) : null;
  if (nested && initiativeId == null) {
    return null;
  }
  const toolSegment = nested ? parts[5] : parts[3];
  const entityId = parseId(nested ? parts[6] : parts[4]);
  if (entityId == null) {
    return null;
  }
  for (const tool of TOOLS) {
    if (toolRouteSegment(tool) === toolSegment) {
      return { entityType: tool as RecentKey["entityType"], entityId, communityId, initiativeId };
    }
  }
  return null;
}

/**
 * Whether a recent item IS the active detail page. Matches on community too —
 * otherwise a community-A file tab would light up while viewing community B's
 * file that happens to share the id.
 */
export function recentKeyMatches(activeKey: RecentKey | null, item: RecentItemRead): boolean {
  if (!activeKey) {
    return false;
  }
  return (
    activeKey.entityType === item.entity_type &&
    activeKey.entityId === item.entity_id &&
    activeKey.communityId === item.community_id
  );
}

/** Where the activity drawer narrows to: one tool, or one initiative. */
export type ActivityScope =
  | { tool: Tool; toolId: number; initiativeId?: undefined }
  | { initiativeId: number; tool?: undefined; toolId?: undefined };

/**
 * What the activity drawer shows on this page, or null for none: the tool a
 * tool's page (or anything inside it, a project's task) belongs to, where that
 * tool carries the drawer, or the initiative whose own page this is.
 *   /c/{communityId}/i/{initiativeId}
 */
export function activityScope(pathname: string): ActivityScope | null {
  const open = getActiveRecentKey(pathname);
  if (open) {
    const tool = open.entityType as Tool;
    return showsActivity(tool) ? { tool, toolId: open.entityId } : null;
  }
  const parts = pathname.replace(/\/$/, "").split("/");
  const initiativeId = parts[3] === "i" && parts.length === 5 ? parseId(parts[4]) : null;
  return initiativeId == null ? null : { initiativeId };
}
