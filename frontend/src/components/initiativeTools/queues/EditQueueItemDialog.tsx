import { Copy, Loader2, MoreHorizontal, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { type QueueItemRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useReadQueueItem } from "@/api/generated/queues/queues";
import { ModerationMenu } from "@/components/moderation/ModerationMenu";
import { ReportButton } from "@/components/moderation/ReportButton";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { usePendingShown } from "@/hooks/useFieldSave";
import { queueItemSaves, useDeleteQueueItem, useDuplicateQueueItem } from "@/hooks/useQueues";
import { detailLayoutOf, instanceTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import type { StoredRegions } from "@/lib/layouts/detailLayout";
import { usePluginMenuActions } from "@/lib/layouts/plugins";
import { QueueItemLayoutView } from "@/lib/layouts/queueItemLayout";
import { toast } from "@/lib/mascotToast";
import type { DialogProps } from "@/types/dialog";

type EditQueueItemDialogProps = DialogProps & {
  queueId: number;
  initiativeId: number;
  item: QueueItemRead;
  readOnly?: boolean;
  /** Whether this reader moderates the queue's initiative. */
  canModerate?: boolean;
  onSuccess?: () => void;
};

/** A queue item, drawn as its queue lays it out, each field saved on its own. */
export const EditQueueItemDialog = ({
  open,
  onOpenChange,
  queueId,
  initiativeId,
  item: listed,
  readOnly = false,
  canModerate = false,
  onSuccess,
}: EditQueueItemDialogProps) => {
  const { t } = useTranslation(["queues", "common"]);
  const communityId = useActiveCommunityId();
  const read = useReadQueueItem(communityId, listed.id, undefined, {
    query: { initialData: listed, enabled: open },
  });
  const item = usePendingShown(queueItemSaves(queueId), listed.id, read.data) ?? listed;
  const layouts = useToolLayouts(open ? instanceTarget(Tool.queue, queueId) : null);
  const pluginActions = usePluginMenuActions("queue_item", item.id, initiativeId);
  const leaving = useRef(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  const close = () => {
    leaving.current = true;
    onOpenChange(false);
    onSuccess?.();
  };
  const deleteItem = useDeleteQueueItem(queueId, {
    onSuccess: () => {
      toast.success(t("itemRemoved"));
      setDeleteConfirmOpen(false);
      close();
    },
  });
  const duplicateItem = useDuplicateQueueItem(queueId, {
    onSuccess: () => {
      toast.success(t("common:subToolDuplicate.done"));
      close();
    },
  });
  const menuPending = deleteItem.isPending || duplicateItem.isPending;

  const actions = (
    <div className="flex shrink-0 items-center gap-1">
      <ReportButton targetType="queue_item" targetId={item.id} authorId={item.created_by} />
      {/* Taken down or held, the item is off the queue, so the dialog about it
          closes. */}
      <ModerationMenu
        targetType="queue_item"
        targetId={item.id}
        canModerate={canModerate}
        onGone={close}
      />
      {!readOnly || pluginActions.items.length > 0 ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={t("common:toolbar.moreActions")}
              aria-busy={menuPending}
            >
              {menuPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <MoreHorizontal className="h-4 w-4" />
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {readOnly ? null : (
              <DropdownMenuItem
                disabled={duplicateItem.isPending}
                onSelect={() => duplicateItem.mutate(item.id)}
              >
                <Copy className="h-4 w-4" />
                {t("common:subToolDuplicate.action")}
              </DropdownMenuItem>
            )}
            {!readOnly && pluginActions.items.length > 0 ? <DropdownMenuSeparator /> : null}
            {pluginActions.items}
            {readOnly ? null : (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  disabled={deleteItem.isPending}
                  onSelect={() => setDeleteConfirmOpen(true)}
                >
                  <Trash2 className="h-4 w-4" />
                  {t("removeItem")}
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="w-full rounded-2xl border bg-card shadow-2xl sm:max-w-3xl">
          <DialogTitle className="sr-only">{t("editItem")}</DialogTitle>
          <DialogDescription className="sr-only">{item.label}</DialogDescription>
          <QueueItemLayoutView
            item={item}
            layout={detailLayoutOf(layouts.data, "queue_item") as StoredRegions | null}
            context={{ readOnly, queueId, initiativeId, leaving, actions }}
          />
        </DialogContent>
      </Dialog>
      {pluginActions.dialog}
      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title={t("removeItem")}
        description={t("removeItemConfirm")}
        confirmLabel={t("removeItem")}
        cancelLabel={t("common:cancel")}
        onConfirm={() => deleteItem.mutate(item.id)}
        isLoading={deleteItem.isPending}
        destructive
      />
    </>
  );
};
