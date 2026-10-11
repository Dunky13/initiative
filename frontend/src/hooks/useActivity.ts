import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";

import { getReadActivityQueryKey, readActivity } from "@/api/generated/activity/activity";
import type { ActivityFeedPage, ReadActivityParams } from "@/api/generated/initiativeAPI.schemas";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";

/**
 * The community's activity feed, page by page as somebody asks for more.
 *
 * It is not refreshed by the realtime bus: every change in a busy community
 * would refetch the feed of everyone looking at it. It is read when the page
 * opens, and again when the reader comes back to it.
 */
export const useActivityFeed = (params?: ReadActivityParams) => {
  const communityId = useActiveCommunityId();
  return useInfiniteQuery({
    queryKey: getReadActivityQueryKey(communityId, params),
    queryFn: ({ pageParam }) => readActivity(communityId, { ...params, page: pageParam as number }),
    initialPageParam: 1,
    getNextPageParam: (last: ActivityFeedPage) => (last.has_next ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
    staleTime: 60 * 1000,
  });
};
