import { FocusSummary } from "@/components/tasks/FocusSummary";
import { useFocusSummary } from "@/hooks/useFocusSummary";
import { useMyTaskStatusChanges } from "@/hooks/useMyTaskStatusChanges";

import type { HomeWidgetProps } from "./types";

/**
 * The focus card: what needs doing now, with today's wins kept in view.
 *
 * On the grid it fills its cell, which the reader sizes instead. Stacked on a
 * narrow screen nothing sizes it, so it folds away as it did on My Tasks, and
 * stays as the reader left it.
 */
export const FocusWidget = ({ stacked }: HomeWidgetProps) => {
  const focus = useFocusSummary();
  const status = useMyTaskStatusChanges();
  return (
    <FocusSummary
      fill={!stacked}
      focus={focus}
      activeCommunityId={null}
      changeTaskStatus={status.changeTaskStatus}
      isUpdatingTask={status.isUpdatingTask}
    />
  );
};
