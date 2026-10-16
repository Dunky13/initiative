import { UserMinus, UserPlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { TaskAssigneeStack } from "@/components/projects/TaskAssigneeList";
import { Button } from "@/components/ui/button";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { RowActionsMenu } from "@/components/ui/row-actions-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useUpdateTaskInCommunity } from "@/hooks/useTasks";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

/**
 * Putting yourself on a task, or taking yourself off it, without opening it.
 * Whoever else is on it stays on it.
 */
const useAssignMe = (task: TaskListRead) => {
  const { t } = useTranslation("projects");
  const { user } = useAuth();
  const activeCommunityId = useActiveCommunityId();
  const update = useUpdateTaskInCommunity({
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:quickActions.assignError"));
    },
  });
  const assigneeIds = task.assignees.map((assignee) => assignee.id);
  const assigned = user ? assigneeIds.includes(user.id) : false;
  const change = (assign: boolean) => {
    if (!user) return;
    update.mutate(
      {
        communityId: task.community_id ?? activeCommunityId,
        taskId: task.id,
        data: {
          assignee_ids: assign
            ? [...assigneeIds, user.id]
            : assigneeIds.filter((id) => id !== user.id),
        },
      },
      {
        onSuccess: () =>
          toast.success(t(assign ? "quickActions.assigned" : "quickActions.unassigned")),
      }
    );
  };
  return { canAssign: user !== null, assigned, change, pending: update.isPending };
};

/** A table's assignees cell: who is on the task, or, where nobody is and the
 *  reader may change it, a button to take it. */
export const TaskAssigneesCell = ({ task, canEdit }: { task: TaskListRead; canEdit: boolean }) => {
  if (task.assignees.length > 0) {
    return <TaskAssigneeStack assignees={task.assignees} />;
  }
  return canEdit ? (
    <AssignMeButton task={task} />
  ) : (
    <span className="text-muted-foreground text-sm">&mdash;</span>
  );
};

const AssignMeButton = ({ task }: { task: TaskListRead }) => {
  const { t } = useTranslation("projects");
  const { canAssign, change, pending } = useAssignMe(task);
  if (!canAssign) return null;
  // An empty avatar's place, quiet until it is pointed at.
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 rounded-full border border-muted-foreground/40 border-dashed text-muted-foreground hover:border-solid hover:text-foreground"
            disabled={pending}
            onClick={() => change(true)}
            aria-label={t("quickActions.assignToMeFor", { title: task.title })}
          >
            <UserPlus className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t("quickActions.assignToMe")}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

/** The menu beside a card's title on a board its reader may change. */
export const TaskCardActions = ({ item: task }: { item: TaskListRead }) => {
  const { t } = useTranslation("projects");
  const { canAssign, assigned, change, pending } = useAssignMe(task);
  return (
    <RowActionsMenu subject={task.title} className="-mt-1.5 -mr-1.5 shrink-0">
      {canAssign ? (
        <DropdownMenuItem disabled={pending} onSelect={() => change(!assigned)}>
          {assigned ? <UserMinus /> : <UserPlus />}
          {t(assigned ? "quickActions.unassignMe" : "quickActions.assignToMe")}
        </DropdownMenuItem>
      ) : null}
    </RowActionsMenu>
  );
};
