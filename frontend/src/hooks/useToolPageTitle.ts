/**
 * The browser tab names the tool you are in: "Sprint 3 - Initiative" on a
 * project, its tasks and its settings alike. Which tool comes from the path
 * (`toolInPath`) and its name from that tool's `TOOL_HOOKS` read, so every
 * tool is covered without a page setting it.
 */

import { useQuery } from "@tanstack/react-query";
import { useLocation } from "@tanstack/react-router";
import { useEffect } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { toolDetailQuery } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { toolInPath } from "@/lib/tools";

export const useToolPageTitle = () => {
  const communityId = useActiveCommunityId();
  const { pathname } = useLocation();
  const found = toolInPath(pathname);
  // A query is always asked, so the hook order holds; with no tool in the path
  // it is disabled and names nothing.
  const { tool, id } = found ?? { tool: Tool.project, id: 0 };
  const name = useQuery({
    ...toolDetailQuery(tool, communityId, id),
    enabled: found !== null,
  }).data?.name;
  const title = found && name ? name : null;

  useEffect(() => {
    if (!title) {
      return;
    }
    const previousTitle = document.title || "Initiative";
    document.title = `${title} - Initiative`;
    return () => {
      document.title = previousTitle;
    };
  }, [title]);
};
