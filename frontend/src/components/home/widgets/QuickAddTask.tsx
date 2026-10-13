/**
 * One line to add a task to a list, from the home page: the shortest way to a
 * first task, and to the next one. The task is the reader's own, so it lands
 * in their tasks straight away.
 */

import { Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { useCreateTaskInCommunity } from "@/hooks/useTasks";
import type { HomeTaskList } from "@/lib/home/firstHome";
import { toast } from "@/lib/mascotToast";

export const QuickAddTask = ({ list, name }: { list: HomeTaskList; name: string }) => {
  const { t } = useTranslation("home");
  const { user } = useAuth();
  const [title, setTitle] = useState("");
  const create = useCreateTaskInCommunity();
  const clean = title.trim();

  return (
    <form
      className="flex gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!clean || create.isPending) return;
        create.mutate(
          {
            communityId: list.communityId,
            data: {
              title: clean,
              project_id: list.projectId,
              ...(user ? { assignee_ids: [user.id] } : {}),
            },
          },
          {
            onSuccess: () => {
              setTitle("");
              toast.success(t("widgets.tasks.added", { list: name }));
            },
          }
        );
      }}
    >
      <Input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder={t("widgets.tasks.addPlaceholder", { list: name })}
        aria-label={t("widgets.tasks.addPlaceholder", { list: name })}
        disabled={create.isPending}
      />
      <Button type="submit" disabled={!clean || create.isPending}>
        <Plus className="size-4" aria-hidden="true" />
        {t("widgets.tasks.add")}
      </Button>
    </form>
  );
};
