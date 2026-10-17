import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { getCountTasksByStatusQueryOptions } from "@/api/generated/tasks/tasks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { listLayouts, useInstanceLayouts } from "@/hooks/useToolLayouts";

/** The most a column may be limited to, as the server holds a layout to. */
export const MAX_COLUMN_LIMIT = 10_000;

/** How full a project's board columns are, where its board limits them. */
export type ColumnRoom = {
  /** The most open tasks the column takes, where it is limited. */
  limitOf: (statusId: number) => number | undefined;
  /** How many open tasks it holds, whatever the reader's filters show. */
  countOf: (statusId: number) => number;
  /** Whether the column takes `entering` more tasks (one by default). */
  hasRoom: (statusId: number, entering?: number) => boolean;
  /** The counts are in, where a column is limited: until then every column
   *  reads as having room. */
  ready: boolean;
};

/** Every column takes every task: a project whose board limits none. */
export const ROOM_EVERYWHERE: ColumnRoom = {
  limitOf: () => undefined,
  countOf: () => 0,
  hasRoom: () => true,
  ready: true,
};

/**
 * The project's column limits, from its board's layout, and how many open
 * tasks each limited column holds, counted by the server. The count is asked
 * only where a column is limited, and refetched with the project's tasks.
 */
export const useColumnRoom = (projectId: number | null): ColumnRoom => {
  const communityId = useActiveCommunityId();
  const layouts = useInstanceLayouts(Tool.project, projectId).data;
  const limits = useMemo(() => {
    const board = listLayouts(layouts).find((layout) => layout.kind === "board");
    return new Map((board?.definition.limits ?? []).map((each) => [each.status_id, each.limit]));
  }, [layouts]);
  const counts = useQuery({
    ...getCountTasksByStatusQueryOptions(communityId, { project_id: projectId ?? 0 }),
    enabled: projectId !== null && limits.size > 0,
  }).data;
  return useMemo(() => {
    if (limits.size === 0) return ROOM_EVERYWHERE;
    const held = new Map((counts ?? []).map((each) => [each.task_status_id, each.count]));
    const countOf = (statusId: number) => held.get(statusId) ?? 0;
    return {
      limitOf: (statusId) => limits.get(statusId),
      ready: counts !== undefined,
      countOf,
      hasRoom: (statusId, entering = 1) => {
        const limit = limits.get(statusId);
        return limit === undefined || countOf(statusId) + entering <= limit;
      },
    };
  }, [limits, counts]);
};
