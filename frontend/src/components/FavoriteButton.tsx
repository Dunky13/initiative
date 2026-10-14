import { Star } from "lucide-react";
import type { MouseEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useIsFavorite, useToggleFavorite } from "@/hooks/useFavorites";
import { cn } from "@/lib/utils";

interface FavoriteButtonProps {
  tool: Tool;
  entityId: number;
  /** What the sidebar shows for it until the server's answer arrives. */
  name?: string;
  initiativeId?: number | null;
  /** The tool's own community, where it is not the one the page is in. */
  communityId?: number;
  className?: string;
  /** On a card that is a link: the click stars, and does not open the card. */
  suppressNavigation?: boolean;
  iconSize?: "sm" | "md";
}

/** The star on any tool: on its page, its card and its row. */
export const FavoriteButton = ({
  tool,
  entityId,
  name,
  initiativeId,
  communityId,
  className,
  suppressNavigation = false,
  iconSize = "md",
}: FavoriteButtonProps) => {
  const { t } = useTranslation("common");
  const starred = useIsFavorite(tool, entityId, communityId);
  const toggle = useToggleFavorite();

  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    if (suppressNavigation) {
      event.preventDefault();
      event.stopPropagation();
    }
    toggle.mutate({ tool, entityId, next: !starred, name, initiativeId, communityId });
  };

  return (
    <button
      type="button"
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-amber-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        iconSize === "sm" ? "size-7" : "size-9",
        className
      )}
      aria-pressed={starred}
      aria-label={starred ? t("favorite.remove") : t("favorite.add")}
      title={starred ? t("favorite.remove") : t("favorite.add")}
      onClick={handleClick}
    >
      <Star
        className={cn("size-4", starred && "text-amber-500")}
        fill={starred ? "currentColor" : "none"}
        aria-hidden
      />
    </button>
  );
};
