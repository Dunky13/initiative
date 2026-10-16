/**
 * One community-wide page of one tool's list, as the rows the tool table draws.
 *
 * The nine list endpoints agree on a shape — `{ items, total_count, has_next }`
 * keyed by `page`/`page_size` — so the tool is a value here rather than a hook
 * per tool, and the query comes from `TOOL_HOOKS`. Turning the answer into rows
 * is `lib/toolRows`, shared with the cross-community twin (`useMyToolRows`), so
 * both tables say the same thing about a tool.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { toolListQuery } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { buildToolRows, oneToolResponse, type ToolResponses, type ToolRow } from "@/lib/toolRows";
import { toolViewParams } from "@/lib/tools";

/** How the table is narrowed and ordered, in the terms every tool's list
 *  endpoint accepts. Always the tool's live view. */
export interface CommunityToolQuery {
  /** Case-insensitive substring of the name, searched across the whole set. */
  search?: string;
  /** One of `name`, `initiative`, `updated_at`. */
  sortBy?: string;
  sortDir?: "asc" | "desc";
  /** Rows carrying any of these tags. */
  tagIds?: number[];
}

export function useCommunityToolRows(
  tool: Tool,
  page: number,
  pageSize: number,
  view: CommunityToolQuery = {}
) {
  const { t } = useTranslation("communityHome");
  const communityId = useActiveCommunityId();

  // Search and sort go to the server, not to the rows already in hand: the
  // table holds one page of a community-wide list, and filtering that page
  // would answer "no matches" while the community holds matches on page 4. The
  // rows in hand stay up while a new page, search or order is in flight.
  const query = useQuery({
    ...toolListQuery(tool, communityId, {
      page,
      page_size: pageSize,
      ...(view.search ? { search: view.search } : {}),
      ...(view.sortBy ? { sort_by: view.sortBy, sort_dir: view.sortDir ?? "asc" } : {}),
      ...(view.tagIds?.length ? { tag_ids: view.tagIds } : {}),
      ...toolViewParams(tool, "active"),
    }),
    placeholderData: keepPreviousData,
  });

  const rows = useMemo<ToolRow[]>(
    () =>
      buildToolRows(
        tool,
        oneToolResponse(tool, query.data as ToolResponses[typeof tool]),
        t,
        communityId
      ),
    [tool, query.data, t, communityId]
  );

  return {
    rows,
    totalCount: query.data?.total_count ?? 0,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
