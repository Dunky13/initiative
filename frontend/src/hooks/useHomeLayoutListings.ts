import { useQuery } from "@tanstack/react-query";

import {
  getListHomeLayoutsQueryKey,
  listHomeLayouts,
} from "@/api/generated/home-layouts/home-layouts";

/** The home layouts the marketplace offers, all at once: one shelf. */
export const useHomeLayoutListings = (options?: { enabled?: boolean }) =>
  useQuery({
    queryKey: getListHomeLayoutsQueryKey(),
    queryFn: ({ signal }) => listHomeLayouts(undefined, signal),
    staleTime: 5 * 60_000,
    enabled: options?.enabled ?? true,
    select: (data) => data.items,
  });
