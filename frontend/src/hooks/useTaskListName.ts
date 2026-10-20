import { useQuery } from "@tanstack/react-query";

import { getReadProjectQueryKey, readProject } from "@/api/generated/projects/projects";
import type { HomeTaskList } from "@/lib/home/firstHome";

/**
 * The name of a list a home widget adds to, read from the list itself rather
 * than kept with the widget: the reader's preferences hold where it is, never
 * what anybody called it. Nothing comes back for a list that is gone or no
 * longer theirs to read, which is how a widget knows to stop offering it.
 */
export const useTaskListName = (list: HomeTaskList | null) =>
  useQuery({
    queryKey: list
      ? getReadProjectQueryKey(list.communityId, list.projectId)
      : ["home-task-list", "none"],
    queryFn: () =>
      readProject((list as HomeTaskList).communityId, (list as HomeTaskList).projectId),
    enabled: list !== null,
    staleTime: 5 * 60_000,
    retry: false,
    select: (project) => project.name,
  });
