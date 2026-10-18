import { Star } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ContentKind } from "@/api/generated/initiativeAPI.schemas";
import { useFollow } from "@/hooks/usePersonalItems";
import { cn } from "@/lib/utils";

interface FollowButtonProps {
  kind: ContentKind;
  entityId: number;
  /** The item's own community, where it is not the one the page is in. */
  communityId?: number;
  className?: string;
}

/** Follow any tool or anything inside one: what changes in it ranks higher in
 *  the reader's activity feed. Beside the bookmark on a tool's page, and in the
 *  actions of a page for something inside a tool. */
export const FollowButton = ({ kind, entityId, communityId, className }: FollowButtonProps) => {
  const { t } = useTranslation("common");
  const { following, ready, toggle } = useFollow(kind, entityId, communityId);
  const label = following ? t("follow.remove") : t("follow.add");

  return (
    <button
      type="button"
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-amber-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default",
        className
      )}
      aria-pressed={following}
      aria-label={label}
      title={label}
      disabled={!ready}
      onClick={toggle}
    >
      <Star
        className={cn("size-4", following && "text-amber-500")}
        fill={following ? "currentColor" : "none"}
        aria-hidden
      />
    </button>
  );
};
