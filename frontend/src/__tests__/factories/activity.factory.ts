import type { ActivityEntry } from "@/api/generated/initiativeAPI.schemas";

import { buildUserPublic } from "./user.factory";

/** An entry of the community's activity feed (`GET /activity/`): a task one
 *  person commented on, unless told otherwise. */
export function buildActivityEntry(overrides: Partial<ActivityEntry> = {}): ActivityEntry {
  return {
    entity_type: "task",
    entity_id: 4,
    title: "Fuel check",
    initiative_id: 5,
    initiative_name: "Apollo",
    tool: "project",
    tool_id: 1,
    tool_title: "Lunar Lander",
    latest: "2026-01-15T00:00:00.000Z",
    verbs: ["commented"],
    actors: [buildUserPublic({ display_name: "Ada" })],
    actor_count: 1,
    ...overrides,
  };
}
