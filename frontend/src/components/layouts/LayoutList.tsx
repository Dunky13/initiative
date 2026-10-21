import { Star } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DetailLayoutRead, ListLayoutRead } from "@/api/generated/initiativeAPI.schemas";
import { layoutLook } from "@/components/projects/projectTasksConfig";
import { formatDateTime } from "@/lib/formatDate";

/**
 * A target's layouts, each with when it was last changed, or a dash while it
 * is drawn as shipped, and the list it opens on marked. A project's task pages
 * are one per task type, each named for its type.
 */
export const LayoutList = ({ layouts }: { layouts: (ListLayoutRead | DetailLayoutRead)[] }) => {
  const { t } = useTranslation(["projects", "layouts", "common"]);
  return (
    <ul className="divide-y rounded-md border text-sm">
      {layouts.map((layout) => {
        const { icon: Icon, labelKey } = layoutLook(layout.kind);
        const typed = "task_type_id" in layout ? layout.task_type_id : null;
        const name =
          typed && "task_type_name" in layout
            ? t("layouts:typedTaskLayout", { name: layout.task_type_name })
            : t(labelKey as never);
        return (
          <li
            key={typed ? `${layout.kind}:${typed}` : layout.kind}
            className="flex items-center justify-between gap-3 px-3 py-2"
          >
            <span className="flex min-w-0 items-center gap-2">
              <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <span className="truncate">{name}</span>
              {"is_default" in layout && layout.is_default ? (
                <Star
                  className="h-3 w-3 shrink-0 fill-current text-muted-foreground"
                  aria-label={t("layouts:opensFirst")}
                  role="img"
                />
              ) : null}
            </span>
            <span className="shrink-0 text-muted-foreground text-xs">
              {layout.updated_at ? (
                <time dateTime={layout.updated_at}>{formatDateTime(layout.updated_at)}</time>
              ) : (
                <span role="img" aria-label={t("layouts:asShipped")}>
                  —
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
};
